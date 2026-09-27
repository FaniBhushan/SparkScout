"""Both scheduling modes must select the same evidence-backed finalists."""

import json
import unittest
from dataclasses import replace

from src.adapters import FrozenFixtureAdapter
from src.application import run_research
from src.models import InputRequest
from test_application import FakeLLMClient, prompt_json


class FrozenModel(FakeLLMClient):
    """Three fixed candidates: two tied passers and one high-scoring gate failure."""

    async def complete(self, prompt, *, max_output_tokens):
        reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
        data = json.loads(reply.text)
        if "idea-discovery worker" in prompt:
            first = data[0]
            second = {**first, "candidate_id": "candidate-02", "title": "Access audit",
                      "problem_statement": "Researchers cannot track approval conditions across datasets.",
                      "proposed_outcome": "An access policy inventory and audit trail",
                      "target_users": ["Research administrators"]}
            third = {**first, "candidate_id": "candidate-03", "title": "Annotation consistency",
                     "problem_statement": "Annotators disagree about ambiguous document labels.",
                     "proposed_outcome": "An annotation comparison interface",
                     "target_users": ["Annotators"]}
            data = [third, second, first]  # Discovery order must not break score ties.
        elif "evidence-based candidate assessor" in prompt:
            candidate = prompt_json(prompt, "Candidate:\n")
            if candidate["candidate_id"] == "candidate-02":
                for score in data["criteria"].values():
                    score["score"] = 5
                next(iter(data["hard_gates"].values()))["passed"] = False
        return replace(reply, text=json.dumps(data))


def stable(value):
    """Ignore only scheduling/identity metadata, retaining all evidence and scores."""
    if isinstance(value, list):
        return [stable(item) for item in value]
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key not in {
            "run_id", "mode", "index_id", "evaluated_at", "completed_at", "elapsed_seconds"}}
    return value


class EquivalenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_pipeline_matches_with_ties_and_failed_gates(self):
        request = InputRequest(domain="AI engineering", time_limit_days=30,
                               desired_candidate_count=3, finalist_count=2)
        results = []
        for mode in ("sequential", "parallel"):
            adapters = {"frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")}
            result = await run_research(request, FrozenModel(), adapters, mode=mode)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.finalist_candidate_ids, ["candidate-01", "candidate-03"])
            self.assertEqual([row.candidate_id for row in result.ranking],
                             ["candidate-01", "candidate-03", "candidate-02"])
            self.assertFalse(result.ranking[-1].gate_passed)
            self.assertGreater(result.ranking[-1].total_score, result.ranking[0].total_score)
            sources = {source.source_id for source in result.source_manifest}
            chunks = {chunk.chunk_id: chunk.source_id for chunk in result.library.chunks}
            for proposal in result.final_proposals:
                for claim in proposal.citations:
                    for ref in claim.references:
                        self.assertIn(ref.source_id, sources)
                        self.assertEqual(chunks[ref.chunk_id], ref.source_id)
            results.append(stable(result.model_dump(mode="json")))
        self.assertEqual(*results)
