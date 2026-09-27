"""Transient failures consume per-attempt budgets and expose safe categories."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from openai import APITimeoutError, RateLimitError

from src.adapters.http_json import SourceRateLimitError
from src.runtime.budgets import BudgetExceeded, BudgetedLLMClient, BudgetedSourceAdapter, RunBudget
from src.llm.client import ModelRateLimitError, ModelReply, ModelTimeoutError, OpenAITextClient
from src.models import RunBudgetLimits
from src.runtime.retry import retry_after_seconds


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def budget(self, provider_calls=2):
        budget = RunBudget(RunBudgetLimits(max_elapsed_seconds=30, max_model_tokens=1000,
                                          provider_call_limits={"github": provider_calls}))
        budget.retry_limit = 1
        return budget

    async def test_provider_retry_consumes_another_allowance(self):
        failure = SourceRateLimitError("github", "rate limited", status=429)
        failure.retry_after = 0
        for allowance in (1, 2):
            budget = self.budget(allowance)
            adapter = SimpleNamespace(search=AsyncMock(side_effect=[failure, []]))
            wrapped = BudgetedSourceAdapter(adapter, "github", budget)
            if allowance == 1:
                with self.assertRaises(BudgetExceeded):
                    await wrapped.search(None)
            else:
                self.assertEqual(await wrapped.search(None), [])
            self.assertEqual(adapter.search.await_count, allowance)

    async def test_unknown_model_usage_stays_reserved_after_retry(self):
        failure = ModelRateLimitError("limited")
        failure.retry_after = 0
        budget = self.budget()
        client = SimpleNamespace(complete=AsyncMock(side_effect=[failure, ModelReply("{}", "fake", 10, 5)]))
        result = await BudgetedLLMClient(client, budget).complete("short", max_output_tokens=100)
        self.assertEqual(result.input_tokens, 10)
        self.assertEqual(client.complete.await_count, 2)
        self.assertGreater(budget.snapshot()["reserved_model_tokens"], 0)

    async def test_long_retry_after_is_not_ignored(self):
        failure = ModelRateLimitError("limited")
        failure.retry_after = 1000
        client = SimpleNamespace(complete=AsyncMock(side_effect=failure))
        with self.assertRaises(ModelRateLimitError):
            await BudgetedLLMClient(client, self.budget()).complete("short", max_output_tokens=100)
        self.assertEqual(client.complete.await_count, 1)
        self.assertIsNone(retry_after_seconds("not-a-delay"))

    async def test_sdk_timeout_and_rate_limit_are_safe_typed_failures(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        errors = [(APITimeoutError(request=request), ModelTimeoutError),
                  (RateLimitError("private provider body", response=httpx.Response(429, request=request),
                                  body={"code": "rate_limit_exceeded"}), ModelRateLimitError)]
        for error, expected in errors:
            sdk = Mock()
            sdk.responses.create = AsyncMock(side_effect=error)
            with self.assertRaises(expected) as caught:
                await OpenAITextClient("fake", sdk_client=sdk).complete("prompt", max_output_tokens=100)
            self.assertNotIn("private provider body", str(caught.exception))
