"""Run-scoped reservations and accounting for shared model/source budgets."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from time import monotonic

from src.adapters.base import SourceAdapter
from src.llm.client import LLMClient, ModelPricing, ModelReply, ModelResponseError
from src.models import RunBudgetLimits
from src.models.scout_query import SourceQuery
from src.models.source_record import SourceRecord
from src.observability import RunTracer


class BudgetExceeded(ModelResponseError):
    """A configured limit prevents the next action or invalidates its result."""


class RunBudget:
    """One shared counter for both branches and final proposal writing."""

    def __init__(
        self,
        limits: RunBudgetLimits,
        *,
        pricing: ModelPricing | None = None,
        tracer: RunTracer | None = None,
    ) -> None:
        if limits.max_estimated_cost_usd is not None and pricing is None:
            raise ValueError("a cost cap requires configured model input/output pricing")
        self.limits = limits
        self.pricing = pricing
        self.tracer = tracer
        self.started_at = monotonic()
        self._lock = asyncio.Lock()
        self._used_tokens = 0
        self._source_bytes = 0
        self._reserved_tokens = 0
        self._used_cost = 0.0
        self._reserved_cost = 0.0
        self._provider_calls: Counter[str] = Counter()

    def check_time(self) -> None:
        if monotonic() - self.started_at >= self.limits.max_elapsed_seconds:
            raise BudgetExceeded("run time budget exhausted")

    async def reserve_model_call(self, prompt: str, max_output_tokens: int) -> tuple[int, float]:
        """Reserve a conservative text-input estimate plus all possible output."""

        # Every UTF-8 byte is counted as a potential token, with small framing
        # headroom. Reported API usage replaces this estimate after the call.
        input_ceiling = len(prompt.encode("utf-8")) + 32
        reserved_tokens = input_ceiling + max_output_tokens
        reserved_cost = self._cost(input_ceiling, max_output_tokens)
        async with self._lock:
            self.check_time()
            if self._used_tokens + self._reserved_tokens + reserved_tokens > self.limits.max_model_tokens:
                raise BudgetExceeded("run model token budget would be exceeded")
            cost_limit = self.limits.max_estimated_cost_usd
            if cost_limit is not None and self._used_cost + self._reserved_cost + reserved_cost > cost_limit:
                raise BudgetExceeded("run estimated cost budget would be exceeded")
            self._reserved_tokens += reserved_tokens
            self._reserved_cost += reserved_cost
        return reserved_tokens, reserved_cost

    async def settle_model_call(
        self,
        reply: ModelReply | None,
        reservation: tuple[int, float],
    ) -> ModelReply | None:
        """Count reported usage even for incomplete responses, then release reserve."""

        async with self._lock:
            self._reserved_tokens -= reservation[0]
            self._reserved_cost -= reservation[1]
            if reply is None:
                return None
            if reply.input_tokens is None or reply.output_tokens is None:
                raise BudgetExceeded("model token usage was not reported", reply=reply)
            tokens = reply.input_tokens + reply.output_tokens
            self._used_tokens += tokens
            cost = self._cost(reply.input_tokens, reply.output_tokens)
            self._used_cost += cost
            if self.tracer:
                self.tracer.budget("run", "model_tokens", self._used_tokens, self.limits.max_model_tokens)
                if self.limits.max_estimated_cost_usd is not None:
                    self.tracer.budget(
                        "run", "estimated_cost_usd", self._used_cost,
                        self.limits.max_estimated_cost_usd,
                    )
            accounted = replace(reply, estimated_cost_usd=cost if self.pricing else None)
            if self._used_tokens > self.limits.max_model_tokens:
                raise BudgetExceeded("run model token budget exceeded", reply=accounted)
            if (
                self.limits.max_estimated_cost_usd is not None
                and self._used_cost > self.limits.max_estimated_cost_usd
            ):
                raise BudgetExceeded("run estimated cost budget exceeded", reply=accounted)
            return accounted

    async def reserve_provider_call(self, provider_id: str) -> None:
        async with self._lock:
            self.check_time()
            limit = self.limits.provider_call_limits.get(provider_id)
            if limit is None:
                raise BudgetExceeded(f"provider {provider_id!r} has no run call allowance")
            if self._provider_calls[provider_id] >= limit:
                raise BudgetExceeded(f"provider {provider_id!r} call budget exhausted")
            self._provider_calls[provider_id] += 1
            if self.tracer:
                self.tracer.budget("run", f"provider_calls:{provider_id}", self._provider_calls[provider_id], limit)

    async def account_source_bytes(self, byte_count: int) -> None:
        """Charge normalized provider records before they reach either worker."""

        async with self._lock:
            self.check_time()
            self._source_bytes += byte_count
            if self.tracer:
                self.tracer.budget(
                    "run", "source_bytes", self._source_bytes, self.limits.max_source_bytes
                )
            if self._source_bytes > self.limits.max_source_bytes:
                raise BudgetExceeded("run source byte budget exceeded")

    def snapshot(self) -> dict[str, object]:
        """Return bounded, non-secret numbers for the final result."""

        return {
            "model_tokens": self._used_tokens,
            "source_bytes": self._source_bytes,
            "estimated_cost_usd": self._used_cost if self.pricing else None,
            "provider_calls": dict(self._provider_calls),
            "elapsed_seconds": round(monotonic() - self.started_at, 3),
        }

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        if self.pricing is None:
            return 0.0
        return (
            input_tokens * self.pricing.input_per_million
            + output_tokens * self.pricing.output_per_million
        ) / 1_000_000


class BudgetedLLMClient:
    """Reserve before each model call, including parallel branch calls."""

    def __init__(self, client: LLMClient, budget: RunBudget) -> None:
        self.client = client
        self.budget = budget

    async def complete(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        reservation = await self.budget.reserve_model_call(prompt, max_output_tokens)
        try:
            reply = await self.client.complete(prompt, max_output_tokens=max_output_tokens)
        except ModelResponseError as error:
            error.reply = await self.budget.settle_model_call(error.reply, reservation)
            raise
        except BaseException:
            await self.budget.settle_model_call(None, reservation)
            raise
        accounted = await self.budget.settle_model_call(reply, reservation)
        assert accounted is not None
        return accounted


class BudgetedSourceAdapter:
    """Count attempted provider calls even when the provider fails."""

    def __init__(self, adapter: SourceAdapter, provider_id: str, budget: RunBudget) -> None:
        self.adapter = adapter
        self.provider_id = provider_id
        self.budget = budget

    async def search(self, query: SourceQuery) -> list[SourceRecord]:
        await self.budget.reserve_provider_call(self.provider_id)
        records = await self.adapter.search(query)
        await self.budget.account_source_bytes(sum(
            len(record.model_dump_json().encode("utf-8"))
            + len((record.full_text or "").encode("utf-8"))
            for record in records
        ))
        return records
