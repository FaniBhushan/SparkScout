"""Frozen passages must reach Critic without extra model calls or stale replay."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.adapters import FrozenFixtureAdapter
from src.application import LLMOutputLimits, run_research
from src.budgets import BudgetExceeded, BudgetedSourceAdapter, RunBudget
from src.models import InputRequest, SourceQuery, SubmittedRunConfiguration
from src.models.run_budget import RunBudgetLimits
from src.persistence.identity import run_identity
from src.preflight import prepare_run
from src.workers.evidence import build_source_chunks
from src.workers.source_filter import same_source_content
from test_application import FakeLLMClient, prompt_json


FIXTURES = Path(__file__).resolve().parents[1] / "evals/frozen_sources"


def dataset_query(content_types=None):
    return SourceQuery(query_id="q1", provider_id="frozen_fixture", text="crop dataset access",
                       source_types=["official_dataset"],
                       content_types=content_types or ["snippet"], max_results=1)


class CapturingClient(FakeLLMClient):
    def __init__(self):
        super().__init__()
        self.evidence = []
        self.scout_sources = []

    async def complete(self, prompt, *, max_output_tokens):
        if "evidence-based candidate assessor" in prompt:
            self.evidence = prompt_json(prompt, "Retrieved evidence chunks:\n")
        if "idea-discovery worker" in prompt:
            self.scout_sources = prompt_json(prompt, "Source records:\n")
        return await super().complete(prompt, max_output_tokens=max_output_tokens)


class FrozenEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_passages_and_summaries_reach_critic_in_both_modes(self):
        request = InputRequest(domain="robotics", time_limit_days=30,
                               desired_candidate_count=1, finalist_count=1)
        fixture_chunks = json.loads((FIXTURES / "robotics_agriculture_01/chunks.json").read_text())
        data_passage = next(c for c in fixture_chunks if c["source_id"] == "rbt-data-001")
        for mode in ("sequential", "parallel"):
            with self.subTest(mode=mode):
                client = CapturingClient()
                result = await run_research(request, client, {
                    "frozen_fixture": FrozenFixtureAdapter("robotics_agriculture_01")
                }, mode=mode)
                chunks = {c.chunk_id: c for c in result.library.chunks}
                self.assertEqual(chunks[data_passage["chunk_id"]].text, data_passage["text"])
                self.assertIn("rbt-data-001-c0", chunks)  # Summary is retained as well.
                sent = {c["chunk_id"]: c for c in client.evidence}
                self.assertEqual(sent[data_passage["chunk_id"]]["text"], data_passage["text"])
                self.assertEqual(sent[data_passage["chunk_id"]]["source_id"], "rbt-data-001")
                self.assertLessEqual(len(sent), result.retrieval_index.max_context_chunks)
                self.assertLessEqual(sum(max(1, len(c["text"]) // 4) for c in sent.values()),
                                     result.retrieval_index.max_context_tokens)
                self.assertTrue(all("evidence_chunks" not in s for s in client.scout_sources))
                self.assertEqual(len(client.calls), 5)

    async def test_metadata_only_does_not_release_passages_and_calls_are_isolated(self):
        adapter = FrozenFixtureAdapter("robotics_agriculture_01")
        metadata = (await adapter.search(dataset_query(["metadata"])))[0]
        self.assertEqual(build_source_chunks([metadata]), [])
        first = (await adapter.search(dataset_query()))[0]
        original = first.evidence_chunks[0].text
        first.evidence_chunks[0].text = "Changed evidence"
        second = (await adapter.search(dataset_query()))[0]
        self.assertEqual(second.evidence_chunks[0].text, original)
        self.assertFalse(same_source_content(first, second))

    async def test_passages_count_towards_source_byte_budget(self):
        adapter = FrozenFixtureAdapter("robotics_agriculture_01")
        receipt = (await adapter.search(dataset_query()))[0]
        budget = RunBudget(RunBudgetLimits(max_elapsed_seconds=30, max_model_tokens=1000,
            max_source_bytes=len(receipt.model_dump_json().encode()),
            provider_call_limits={"frozen_fixture": 1}))
        with self.assertRaisesRegex(BudgetExceeded, "source"):
            await BudgetedSourceAdapter(adapter, "frozen_fixture", budget).search(dataset_query())

    def test_invalid_passage_references_are_rejected(self):
        original = json.loads((FIXTURES / "robotics_agriculture_01/chunks.json").read_text())
        variants = [(original + [original[0]], "unique"),
                    ([{**original[0], "source_id": "unknown"}], "unknown source")]
        for passages, message in variants:
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory) / "fixture"
                shutil.copytree(FIXTURES / "robotics_agriculture_01", folder)
                (folder / "chunks.json").write_text(json.dumps(passages))
                with self.assertRaisesRegex(ValueError, message):
                    FrozenFixtureAdapter("fixture", fixture_root=directory)

    def test_changing_passages_invalidates_resume_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "fixture"
            shutil.copytree(FIXTURES / "robotics_agriculture_01", folder)
            adapters = {"frozen_fixture": FrozenFixtureAdapter("fixture", fixture_root=directory)}
            prepared = prepare_run(SubmittedRunConfiguration(request=InputRequest(
                domain="robotics", time_limit_days=30)), adapters)
            def identity():
                return run_identity(prepared, FakeLLMClient(), adapters, LLMOutputLimits(),
                                    "sequential", None, 0)
            before = identity()
            chunks = json.loads((folder / "chunks.json").read_text())
            chunks[0]["text"] += " Additional captured evidence."
            (folder / "chunks.json").write_text(json.dumps(chunks))
            self.assertNotEqual(before["providers_sha256"], identity()["providers_sha256"])


if __name__ == "__main__":
    unittest.main()
