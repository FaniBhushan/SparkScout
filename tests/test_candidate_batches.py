"""Bound candidate responses while preserving valid work and shared budgets."""

import json
import unittest
from datetime import datetime, timezone

from src.budgets import BudgetExceeded
from src.llm.client import ModelReply, ModelResponseError, ModelTransportError
from src.llm.scout_llm import LLMCandidateGenerator
from src.models import InputRequest, SourceRecord
from test_application import prompt_json


def idea(label):
    return {"candidate_id": "reused-id", "title": label, "problem_statement": label,
            "proposed_outcome": label, "target_users": ["Students"],
            "why_it_matters": "A hypothesis to test.", "evidence": [{"source_id": "source-1"}]}


class BatchClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def complete(self, prompt, *, max_output_tokens):
        self.calls.append((prompt, max_output_tokens))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return ModelReply(text=json.dumps(response), model="offline-test",
                          input_tokens=50, output_tokens=50)


class CandidateBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = SourceRecord(source_id="source-1", provider="fixture", source_type="dataset",
            title="Research fixture", captured_at=datetime.now(timezone.utc), query_id="q1",
            content_hash="fixture", retrieval_status="success", abstract_or_snippet="Evidence.")

    async def generate(self, client, count=8):
        return await LLMCandidateGenerator(client, max_output_tokens=3000).generate(
            InputRequest(domain="AI engineering", time_limit_days=30,
                         desired_candidate_count=count, finalist_count=min(3, count)), [self.source])

    async def test_batches_fill_request_with_unique_ids_and_compact_prior_ideas(self):
        labels = ["Weather alerts", "Harvest queues", "Disease images", "Crop watering",
                  "Machine repair", "Seed tracking", "Soil sampling", "Market prices"]
        client = BatchClient([[idea(label) for label in labels[index:index + 3]]
                              for index in range(0, 8, 3)])
        result = await self.generate(client)
        self.assertEqual([item.title for item in result], labels)
        self.assertEqual([item.candidate_id for item in result], [f"candidate-{n:02d}" for n in range(1, 9)])
        plans = [prompt_json(prompt, "Batch instructions:\n") for prompt, _ in client.calls]
        self.assertEqual([plan["requested_count"] for plan in plans], [3, 3, 2])
        self.assertEqual([len(plan["existing_ideas"]) for plan in plans], [0, 3, 6])
        self.assertTrue(all(limit == 3000 for _, limit in client.calls))
        self.assertNotIn("evidence", plans[1]["existing_ideas"][0])

    async def test_later_truncated_batch_retains_previous_candidates(self):
        error = ModelResponseError("incomplete", reply=ModelReply(text="[", model="offline-test"))
        client = BatchClient([[idea("Weather alerts"), idea("Harvest queues"), idea("Disease images")], error])
        result = await self.generate(client)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(client.calls), 2)

    async def test_initial_truncation_gets_one_smaller_attempt(self):
        error = ModelResponseError("incomplete", reply=ModelReply(text="[", model="offline-test"))
        client = BatchClient([error, [idea("Weather alerts")]])
        result = await self.generate(client, count=3)
        self.assertEqual(len(result), 1)
        self.assertEqual([prompt_json(p, "Batch instructions:\n")["requested_count"]
                          for p, _ in client.calls], [3, 1])
        repeated = BatchClient([error, error])
        with self.assertRaises(ModelResponseError):
            await self.generate(repeated, count=3)
        self.assertEqual(len(repeated.calls), 2)

    async def test_no_progress_stops_and_bad_references_are_discarded(self):
        wrong = idea("Missing source")
        wrong["evidence"] = [{"source_id": "unknown"}]
        client = BatchClient([[idea("Weather alerts"), wrong], [idea("Weather alerts")]])
        result = await self.generate(client)
        self.assertEqual([item.title for item in result], ["Weather alerts"])
        self.assertEqual(len(client.calls), 2)

    async def test_budget_and_unknown_transport_usage_still_propagate(self):
        for error in (BudgetExceeded("limit"), ModelTransportError("connection")):
            with self.subTest(error=type(error).__name__):
                client = BatchClient([[idea("Weather alerts")], error])
                with self.assertRaises(type(error)):
                    await self.generate(client)

    async def test_synthetic_ideas_remain_internal_and_can_guide_later_batches(self):
        synthetic = idea("Synthetic exploration")
        synthetic["origin"] = "synthetic"
        synthetic["evidence"] = []
        client = BatchClient([[synthetic], [idea("Weather alerts")]])
        result = await self.generate(client, count=4)
        self.assertEqual([item.title for item in result], ["Weather alerts"])
        prior = prompt_json(client.calls[1][0], "Batch instructions:\n")["existing_ideas"]
        self.assertEqual(prior[0]["origin"], "synthetic")
        from src.models import CandidateIdea, ScoutResult
        from pydantic import ValidationError
        with self.assertRaisesRegex(ValidationError, "must not appear"):
            ScoutResult(candidates=[CandidateIdea.model_validate(synthetic)])

    async def test_uncited_ideas_are_internal_even_without_synthetic_label(self):
        uncited = idea("Unsupported exploration")
        uncited["evidence"] = []
        client = BatchClient([[uncited], [idea("Weather alerts")]])
        result = await self.generate(client, count=4)
        self.assertEqual([item.title for item in result], ["Weather alerts"])
        prior = prompt_json(client.calls[1][0], "Batch instructions:\n")["existing_ideas"]
        self.assertEqual(prior[0]["origin"], "synthetic")

    async def test_synthetic_only_batch_does_not_create_a_user_candidate(self):
        synthetic = idea("Internal idea with a real source reference")
        synthetic["origin"] = "synthetic"
        client = BatchClient([[synthetic]])
        self.assertEqual(await self.generate(client, count=1), [])


if __name__ == "__main__":
    unittest.main()
