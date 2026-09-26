"""Run budgets must hold across parallel model and provider calls."""

import asyncio
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from src.budgets import BudgetExceeded, BudgetedLLMClient, BudgetedSourceAdapter, RunBudget
from src.llm.client import ModelPricing, ModelReply
from src.models import (
    BudgetSelection,
    InputRequest,
    PreparedRun,
    RunBudgetLimits,
    SourceRecord,
    SubmittedRunConfiguration,
)
from src.preflight import prepare_run


class ModelStub:
    def __init__(self, *, report_usage=True):
        self.calls = 0
        self.report_usage = report_usage

    async def complete(self, prompt, *, max_output_tokens):
        self.calls += 1
        await asyncio.sleep(0)
        return ModelReply(
            text="{}", model="stub",
            input_tokens=20 if self.report_usage else None,
            output_tokens=10 if self.report_usage else None,
        )


class SourceStub:
    def __init__(self, records=None):
        self.calls = 0
        self.records = records or []

    async def search(self, query):
        self.calls += 1
        return self.records


class RunBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_model_calls_share_reservations(self):
        limits = RunBudgetLimits(
            max_elapsed_seconds=30, max_model_tokens=600,
        )
        stub = ModelStub()
        client = BudgetedLLMClient(stub, RunBudget(limits))

        outcomes = await asyncio.gather(
            client.complete("short", max_output_tokens=500),
            client.complete("short", max_output_tokens=500),
            return_exceptions=True,
        )

        self.assertEqual(stub.calls, 1)
        self.assertEqual(sum(isinstance(item, BudgetExceeded) for item in outcomes), 1)

    async def test_missing_usage_fails_closed(self):
        client = BudgetedLLMClient(
            ModelStub(report_usage=False),
            RunBudget(RunBudgetLimits(max_elapsed_seconds=30, max_model_tokens=1000)),
        )
        with self.assertRaisesRegex(BudgetExceeded, "not reported"):
            await client.complete("short", max_output_tokens=100)

    async def test_cost_limit_requires_rates_and_is_checked_before_call(self):
        limits = RunBudgetLimits(
            max_elapsed_seconds=30,
            max_model_tokens=1000,
            max_estimated_cost_usd=0.0001,
        )
        with self.assertRaisesRegex(ValueError, "requires configured"):
            RunBudget(limits)

        stub = ModelStub()
        budget = RunBudget(limits, pricing=ModelPricing(1, 1))
        client = BudgetedLLMClient(stub, budget)
        with self.assertRaisesRegex(BudgetExceeded, "cost budget"):
            await client.complete("short", max_output_tokens=100)
        self.assertEqual(stub.calls, 0)

    async def test_provider_allowance_is_shared_across_wrappers(self):
        budget = RunBudget(RunBudgetLimits(
            max_elapsed_seconds=30, max_model_tokens=1000,
            provider_call_limits={"github": 1},
        ))
        stub = SourceStub()
        scout_adapter = BudgetedSourceAdapter(stub, "github", budget)
        library_adapter = BudgetedSourceAdapter(stub, "github", budget)

        self.assertEqual(await scout_adapter.search(None), [])
        with self.assertRaisesRegex(BudgetExceeded, "call budget exhausted"):
            await library_adapter.search(None)
        self.assertEqual(stub.calls, 1)
        self.assertEqual(budget.snapshot()["provider_calls"], {"github": 1})

    async def test_source_bytes_are_shared_and_rejected_before_worker_receives_records(self):
        record = SourceRecord(
            source_id="example", provider="github", source_type="code_repository",
            title="Example", captured_at=datetime.now(timezone.utc),
            canonical_url="https://example.com/example", query_id="query",
            abstract_or_snippet="A source description", content_hash="abc",
            retrieval_status="success",
        )
        size = len(record.model_dump_json().encode("utf-8"))
        budget = RunBudget(RunBudgetLimits(
            max_elapsed_seconds=30, max_model_tokens=1000,
            max_source_bytes=size, provider_call_limits={"github": 2},
        ))
        adapter = BudgetedSourceAdapter(SourceStub([record]), "github", budget)
        self.assertEqual(await adapter.search(None), [record])
        with self.assertRaisesRegex(BudgetExceeded, "source byte budget exceeded"):
            await adapter.search(None)
        self.assertEqual(budget.snapshot()["source_bytes"], size * 2)

    async def test_preflight_rejects_ceiling_and_checksums_budget(self):
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        adapters = {"github": SourceStub(), "tavily": SourceStub()}
        with self.assertRaisesRegex(ValueError, "operator ceiling"):
            prepare_run(SubmittedRunConfiguration(
                request=request,
                budgets=BudgetSelection(max_model_tokens=100001),
            ), adapters)
        with self.assertRaisesRegex(ValueError, "operator ceiling"):
            prepare_run(SubmittedRunConfiguration(
                request=request,
                budgets=BudgetSelection(max_source_bytes=10_000_001),
            ), adapters)

        prepared = prepare_run(SubmittedRunConfiguration(
            request=request,
            budgets=BudgetSelection(max_model_tokens=50000),
        ), adapters)
        self.assertEqual(prepared.budgets.max_model_tokens, 50000)
        self.assertEqual(prepared.budgets.provider_call_limits["github"], 5)
        prepared.budgets.max_model_tokens = 60000
        with self.assertRaisesRegex(ValidationError, "checksum"):
            PreparedRun.model_validate(prepared.model_dump(mode="python"))


if __name__ == "__main__":
    unittest.main()
