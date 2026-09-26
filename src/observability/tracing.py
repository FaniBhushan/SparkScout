"""Write one structured JSON trace per run."""

from __future__ import annotations

import json
import logging
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterator
from uuid import uuid4

from src.models.usage_record import UsageRecord


class _ConsoleFormatter(logging.Formatter):
    """Show the important trace fields as readable terminal logs."""

    def format(self, record: logging.LogRecord) -> str:
        data = json.loads(record.getMessage())
        prefix = f"[{record.levelname}] run={data['run_id']} stage={data['stage']}"
        event = data["event"]
        if event == "budget":
            return (
                f"{prefix} budget {data['metric']}={data['used']}/{data['limit']} "
                f"remaining={data['remaining']}"
            )
        if event == "usage":
            token_detail = (
                f"prompt_tokens={data['prompt_tokens']} "
                f"completion_tokens={data['completion_tokens']}"
                if data.get("token_usage_available", True)
                else "tokens=unreported"
            )
            return (
                f"{prefix} usage {token_detail} "
                f"cost_usd={data.get('estimated_cost_usd', 'unconfigured')}"
            )
        details = [event]
        for key in ("provider_id", "query_id", "count", "duration_ms", "error_type"):
            if key in data:
                details.append(f"{key}={data[key]}")
        return f"{prefix} {' '.join(details)}"


class RunTracer:
    """Record timed stages and budget snapshots without logging research text."""

    def __init__(
        self,
        run_id: str,
        log_dir: Path | str = "runs",
        *,
        console: bool = True,
        on_record: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
            raise ValueError("run_id must be a safe file name")

        self.run_id = run_id
        self.on_record = on_record
        self.trace_path = Path(log_dir) / run_id / "trace.jsonl"
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self._active_span: ContextVar[str | None] = ContextVar(
            f"scoutspark_span_{run_id}", default=None
        )
        self._logger = logging.getLogger(f"scoutspark.trace.{run_id}.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._file_handler = logging.FileHandler(self.trace_path, encoding="utf-8")
        self._file_handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(self._file_handler)
        self._console_handler: logging.Handler | None = None
        if console:
            self._console_handler = logging.StreamHandler()
            self._console_handler.setFormatter(_ConsoleFormatter())
            self._logger.addHandler(self._console_handler)

    def event(
        self,
        stage: str,
        event: str,
        *,
        task_id: str | None = None,
        provider_id: str | None = None,
        query_id: str | None = None,
        count: int | None = None,
    ) -> None:
        """Record an event using bounded metadata only."""

        self._write(
            stage=stage,
            event=event,
            task_id=task_id,
            provider_id=provider_id,
            query_id=query_id,
            count=count,
            span_id=self._active_span.get(),
        )

    def budget(
        self,
        stage: str,
        metric: str,
        used: int | float,
        limit: int | float,
        *,
        task_id: str | None = None,
    ) -> None:
        """Record current use against a configured limit."""

        if not all(math.isfinite(value) and value >= 0 for value in (used, limit)):
            raise ValueError("budget used and limit must be finite, non-negative numbers")
        self._write(
            stage=stage,
            event="budget",
            task_id=task_id,
            span_id=self._active_span.get(),
            metric=metric,
            used=used,
            limit=limit,
            remaining=max(limit - used, 0),
            exceeded=used > limit,
        )

    def usage(
        self,
        stage: str,
        usage: UsageRecord,
        *,
        task_id: str | None = None,
    ) -> None:
        """Record model and provider use for a task or individual call."""

        self._write(
            stage=stage,
            event="usage",
            task_id=task_id,
            span_id=self._active_span.get(),
            **usage.model_dump(exclude={"schema_version"}),
        )

    @contextmanager
    def span(
        self,
        stage: str,
        *,
        task_id: str | None = None,
        provider_id: str | None = None,
        query_id: str | None = None,
    ) -> Iterator[None]:
        """Trace a synchronous or asynchronous block and its elapsed time."""

        span_id = uuid4().hex
        parent_span_id = self._active_span.get()
        token = self._active_span.set(span_id)
        started = perf_counter()
        self._write(
            stage=stage,
            event="start",
            task_id=task_id,
            provider_id=provider_id,
            query_id=query_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
        )
        try:
            yield
        except BaseException as error:
            self._write(
                stage=stage,
                event="error",
                task_id=task_id,
                provider_id=provider_id,
                query_id=query_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                error_type=type(error).__name__,
            )
            raise
        else:
            self._write(
                stage=stage,
                event="end",
                task_id=task_id,
                provider_id=provider_id,
                query_id=query_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
        finally:
            self._active_span.reset(token)

    def close(self) -> None:
        """Flush and close the run's trace file."""

        self._logger.removeHandler(self._file_handler)
        self._file_handler.close()
        if self._console_handler is not None:
            self._logger.removeHandler(self._console_handler)
            self._console_handler.close()

    def _write(self, *, stage: str, event: str, **fields: object) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "stage": stage,
            "event": event,
        }
        record.update({key: value for key, value in fields.items() if value is not None})
        level = logging.ERROR if event == "error" else logging.INFO
        if event == "budget" and record.get("exceeded"):
            level = logging.WARNING
        self._logger.log(level, json.dumps(record, allow_nan=False, separators=(",", ":")))
        if self.on_record is not None:
            try:
                self.on_record(record)
            except Exception:
                # A presentation subscriber must not stop or alter research.
                logging.getLogger(__name__).warning("trace progress callback failed")
