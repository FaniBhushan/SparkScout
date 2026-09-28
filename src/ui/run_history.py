"""Small local history for reopening completed demo runs in Streamlit."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.models import OrchestrationResult


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_HISTORY_DIR = Path(__file__).resolve().parents[2] / "runs" / "ui_results"


@dataclass(frozen=True)
class SavedRun:
    """A saved run's identifier and local save time for the UI picker."""

    run_id: str
    saved_at: datetime


def list_saved_runs() -> list[SavedRun]:
    """Return saved results newest first; unavailable storage means no history."""

    try:
        paths = _HISTORY_DIR.glob("*.json")
        return [
            SavedRun(path.stem, datetime.fromtimestamp(path.stat().st_mtime))
            for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)
            if _RUN_ID.fullmatch(path.stem)
        ]
    except OSError:
        return []


def has_saved_run(run_id: str) -> bool:
    """Check whether this run already has a local snapshot."""

    return bool(_RUN_ID.fullmatch(run_id)) and (_HISTORY_DIR / f"{run_id}.json").is_file()


def save_run_result(result: OrchestrationResult) -> Path:
    """Atomically store a validated result in the Git-ignored local run folder."""

    if not _RUN_ID.fullmatch(result.run_id):
        raise ValueError("run ID is not safe for a local history filename")
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    destination = _HISTORY_DIR / f"{result.run_id}.json"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=_HISTORY_DIR,
            prefix=f".{result.run_id}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(result.model_dump_json(indent=2))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination


def load_run_result(run_id: str) -> OrchestrationResult:
    """Load and contract-validate a previously saved run result."""

    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run ID is not valid")
    path = _HISTORY_DIR / f"{run_id}.json"
    return OrchestrationResult.model_validate_json(path.read_text(encoding="utf-8"))
