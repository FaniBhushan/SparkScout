"""Run-scoped reservations and accounting for shared model/source budgets."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from time import monotonic

from src.adapters.base import SourceAdapter
from src.guardrails import check_privacy, emit_advisories
from src.llm.client import LLMClient, ModelPricing, ModelReply, ModelResponseError
from src.models import RunBudgetLimits
from src.models.scout_query import SourceQuery
from src.models.source_record import SourceRecord
from src.observability import RunTracer
from src.runtime.failures import RetryableFailure
from src.runtime.retry import wait_before_retry


class BudgetExceeded(ModelResponseError):
    """A configured limit prevents the next action or invalidates its result."""


class ModelAllowanceExceeded(BudgetExceeded):
    """A pre-call reservation did not fit; no generation request was sent."""


class ProviderCallBudgetExceeded(BudgetExceeded):
    """One provider's allowance is spent; other configured sources may continue."""


class StageAllowanceExceeded(ModelAllowanceExceeded):
    """Research must stop so remaining tokens can be used for finalization."""


class RunBudget:
    """Coordinate run-wide limits across concurrent and later workflow stages.

    Reservations happen before provider calls so parallel branches cannot each
    spend the same remaining allowance. Unknown usage keeps its reserved amount
    rather than optimistically refunding tokens that may have been consumed.
    """

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
        self.retry_limit = 0
        self.checkpoint = None

    def remaining_seconds(self) -> float:
        return max(0, self.limits.max_elapsed_seconds - (monotonic() - self.started_at))

    def restore(self, values: dict) -> None:
        """Resume counts including unknown usage; offline time is not execution time."""
        from src.models.run_budget import RunBudgetUsage
        usage = RunBudgetUsage.model_validate(values)
        self._used_tokens = usage.model_tokens
        self._used_cost = usage.estimated_cost_usd or 0
        self._reserved_tokens = usage.reserved_model_tokens
        self._reserved_cost = usage.reserved_cost_usd
        self._source_bytes = usage.source_bytes
        self._provider_calls = Counter(usage.provider_calls)
        self.started_at = monotonic() - usage.elapsed_seconds

    def persist(self) -> None:
        if self.checkpoint:
            self.checkpoint.save_budget(self.snapshot())

    def check_time(self) -> None:
        if monotonic() - self.started_at >= self.limits.max_elapsed_seconds:
            raise BudgetExceeded("run time budget exhausted")

    def output_allowance_fits(self, max_output_tokens: int, headroom_tokens: int = 0) -> bool:
        """Skip token-count requests when even a zero-input call cannot fit."""
        tokens_fit = (self._used_tokens + self._reserved_tokens + max_output_tokens
                      <= self.limits.max_model_tokens - headroom_tokens)
        cap = self.limits.max_estimated_cost_usd
        cost_fits = cap is None or (
            self._used_cost + self._reserved_cost + self._cost(0, max_output_tokens) <= cap)
        return tokens_fit and cost_fits

    async def reserve_model_call(self, prompt: str, max_output_tokens: int,
                                 *, input_tokens: int | None = None,
                                 headroom_tokens: int = 0) -> tuple[int, float]:
        """Reserve a conservative text-input estimate plus all possible output."""

        if type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")

        # Every UTF-8 byte is counted as a potential token, with small framing
        # headroom. Reported API usage replaces this estimate after the call.
        if input_tokens is not None and (type(input_tokens) is not int or input_tokens < 0):
            raise ValueError("input_tokens must be a non-negative integer")
        input_ceiling = len(prompt.encode("utf-8")) + 32 if input_tokens is None else input_tokens
        reserved_tokens = input_ceiling + max_output_tokens
        reserved_cost = self._cost(input_ceiling, max_output_tokens)
        async with self._lock:
            self.check_time()
            if headroom_tokens and self._used_tokens + self._reserved_tokens + reserved_tokens > self.limits.max_model_tokens - headroom_tokens:
                raise StageAllowanceExceeded("research stopped to retain finalization token allowance")
            if self._used_tokens + self._reserved_tokens + reserved_tokens > self.limits.max_model_tokens:
                raise ModelAllowanceExceeded("run model token budget would be exceeded")
            cost_limit = self.limits.max_estimated_cost_usd
            if cost_limit is not None and self._used_cost + self._reserved_cost + reserved_cost > cost_limit:
                raise ModelAllowanceExceeded("run estimated cost budget would be exceeded")
            self._reserved_tokens += reserved_tokens
            self._reserved_cost += reserved_cost
            self.persist()
        return reserved_tokens, reserved_cost

    async def settle_model_call(
        self,
        reply: ModelReply | None,
        reservation: tuple[int, float],
    ) -> ModelReply | None:
        """Settle known usage; retain allowance when provider usage is unknown.

        A transport failure or cancellation does not prove the provider did no
        billable work. Keep its conservative reservation unavailable to siblings.
        """

        async with self._lock:
            if reply is None:
                return None
            if reply.input_tokens is None or reply.output_tokens is None:
                raise BudgetExceeded("model token usage was not reported", reply=reply)
            if any(type(value) is not int or value < 0 for value in (
                reply.input_tokens, reply.output_tokens
            )):
                raise BudgetExceeded("model token usage was invalid", reply=reply)
            self._reserved_tokens -= reservation[0]
            self._reserved_cost = max(0.0, self._reserved_cost - reservation[1])
            if self._reserved_tokens == 0:
                # Parallel settlements can leave a sub-cent floating-point
                # remainder. No pending tokens means no pending cost either.
                self._reserved_cost = 0.0
            tokens = reply.input_tokens + reply.output_tokens
            self._used_tokens += tokens
            cost = self._cost(reply.input_tokens, reply.output_tokens)
            self._used_cost += cost
            self.persist()
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
                raise ProviderCallBudgetExceeded(f"provider {provider_id!r} has no run call allowance")
            if self._provider_calls[provider_id] >= limit:
                raise ProviderCallBudgetExceeded(f"provider {provider_id!r} call budget exhausted")
            self._provider_calls[provider_id] += 1
            self.persist()
            if self.tracer:
                self.tracer.budget("run", f"provider_calls:{provider_id}", self._provider_calls[provider_id], limit)

    async def account_source_bytes(self, byte_count: int) -> None:
        """Charge normalized provider records before they reach either worker."""

        async with self._lock:
            self.check_time()
            self._source_bytes += byte_count
            self.persist()
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
            "reserved_model_tokens": self._reserved_tokens,
            "reserved_cost_usd": self._reserved_cost,
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

    def __init__(self, client: LLMClient, budget: RunBudget, *, headroom_tokens: int = 0) -> None:
        if type(headroom_tokens) is not int or headroom_tokens < 0:
            raise ValueError("headroom_tokens must be a non-negative integer")
        self.client = client
        self.budget = budget
        self.headroom_tokens = headroom_tokens
        self.model = getattr(client, "model", type(client).__module__ + "." + type(client).__qualname__)

    async def complete(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        for attempt in range(self.budget.retry_limit + 1):
            try:
                return await self._attempt(prompt, max_output_tokens=max_output_tokens)
            except RetryableFailure as error:
                if attempt >= self.budget.retry_limit:
                    raise
                if self.budget.tracer:
                    self.budget.tracer.event("model", "retry", count=attempt + 1)
                await wait_before_retry(error, self.budget)

    async def _attempt(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        try:
            reservation = await self.budget.reserve_model_call(
                prompt, max_output_tokens, headroom_tokens=self.headroom_tokens)
        except ModelAllowanceExceeded as original:
            # Only near the limit: count the real request, not bytes. Recheck
            # under the lock because another branch may spend while we count.
            if not self.budget.output_allowance_fits(max_output_tokens, self.headroom_tokens):
                raise
            try:
                count = await asyncio.wait_for(self.count_input_tokens(prompt),
                                               timeout=self.budget.remaining_seconds())
            except (ModelResponseError, asyncio.TimeoutError):
                raise original from None
            reservation = await self.budget.reserve_model_call(
                prompt, max_output_tokens, input_tokens=count, headroom_tokens=self.headroom_tokens)
            if self.budget.tracer:
                self.budget.tracer.event("model", "exact_input_reservation", count=count)
        try:
            reply = await asyncio.wait_for(
                self.client.complete(prompt, max_output_tokens=max_output_tokens),
                timeout=self.budget.remaining_seconds(),
            )
        except asyncio.TimeoutError:
            raise BudgetExceeded("run time budget exhausted") from None
        except ModelResponseError as error:
            error.reply = await self.budget.settle_model_call(error.reply, reservation)
            raise
        except BaseException:
            await self.budget.settle_model_call(None, reservation)
            raise
        accounted = await self.budget.settle_model_call(reply, reservation)
        assert accounted is not None
        return accounted

    async def count_input_tokens(self, prompt: str) -> int:
        """Delegate through nested run/suite wrappers without a generation call."""
        counter = getattr(self.client, "count_input_tokens", None)
        if counter is None:
            raise ModelResponseError("input token counting unavailable")
        return await counter(prompt)


class BudgetedSourceAdapter:
    """Count attempted provider calls even when the provider fails."""

    def __init__(self, adapter: SourceAdapter, provider_id: str, budget: RunBudget) -> None:
        self.adapter = adapter
        self.provider_id = provider_id
        self.budget = budget

    async def search(self, query: SourceQuery) -> list[SourceRecord]:
        for attempt in range(self.budget.retry_limit + 1):
            try:
                return await self._attempt(query)
            except RetryableFailure as error:
                if attempt >= self.budget.retry_limit:
                    raise
                if self.budget.tracer:
                    self.budget.tracer.event("provider", "retry", provider_id=self.provider_id, count=attempt + 1)
                await wait_before_retry(error, self.budget)

    async def _attempt(self, query: SourceQuery) -> list[SourceRecord]:
        emit_advisories(check_privacy(query))
        await self.budget.reserve_provider_call(self.provider_id)
        try:
            records = await asyncio.wait_for(self.adapter.search(query), timeout=self.budget.remaining_seconds())
        except asyncio.TimeoutError:
            raise BudgetExceeded("run time budget exhausted") from None
        await self.budget.account_source_bytes(sum(
            len(record.model_dump_json().encode("utf-8"))
            + len((record.full_text or "").encode("utf-8"))
            + sum(len(chunk.model_dump_json().encode("utf-8")) for chunk in record.evidence_chunks)
            for record in records
        ))
        return records
