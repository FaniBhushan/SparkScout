"""Coordinator-owned retrieval is isolated to each run's Library evidence."""

import asyncio
import unittest
from datetime import datetime, timezone

from src.evaluation import load_evaluation_configuration
from src.models import (
    CandidateAssessment,
    CandidateIdea,
    CriterionJudgment,
    GateJudgment,
    InputRequest,
    LibraryResult,
    ResolvedSearchConfiguration,
    ScoutResult,
    SourceChunk,
    SourceRecord,
)
from src.models.common import EvidenceReference
from src.models.source_record import RetrievalStatus
from src.orchestration.coordinator import Orchestrator
from src.retrieval import InMemoryRetriever
from src.workers.critic_worker import CriticWorker


class Scout:
    async def run(self, request, search):
        topic = request.interests[0]
        return ScoutResult(candidates=[CandidateIdea(
            candidate_id=f"candidate-{topic}",
            title=f"{topic} project",
            problem_statement=f"Research the {topic} problem with available evidence.",
            target_users=["Students"],
            proposed_outcome=f"An evaluated {topic} prototype",
            why_it_matters="Helps students complete a useful capstone.",
        )])


class Library:
    async def run(self, request, search):
        topic = request.interests[0]
        source_id = f"source-{topic}"
        return LibraryResult(
            sources=[SourceRecord(
                source_id=source_id,
                provider="fixture",
                source_type="dataset",
                title=f"{topic} dataset",
                captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                canonical_url=f"https://example.org/{topic}",
                query_id=f"query-{topic}",
                abstract_or_snippet=f"Evidence for the {topic} project.",
                content_hash=f"hash-{topic}",
                retrieval_status=RetrievalStatus.SUCCESS,
            )],
            chunks=[SourceChunk(
                chunk_id=f"{source_id}-c0",
                source_id=source_id,
                ordinal=0,
                text=f"Evidence for the {topic} project.",
                content_hash=f"chunk-hash-{topic}",
            )],
        )


class RecordingJudge:
    def __init__(self):
        self.evidence_by_topic = {}

    async def assess(self, request, candidate, evidence, rubric):
        topic = request.interests[0]
        self.evidence_by_topic[topic] = [hit.chunk.source_id for hit in evidence]
        reference = EvidenceReference(
            source_id=evidence[0].chunk.source_id,
            chunk_id=evidence[0].chunk.chunk_id,
        )
        return CandidateAssessment(
            criteria={
                key: CriterionJudgment(score=4, rationale="Supported.", evidence=[reference])
                for key in rubric.criteria
            },
            hard_gates={
                key: GateJudgment(passed=True, rationale="Supported.", evidence=[reference])
                for key in rubric.hard_gates
            },
        )


class RunRetrievalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[{
                "provider_id": "fixture",
                "source_types": ["dataset"],
                "content_types": ["text"],
            }],
            content_types=["text"],
            max_queries=2,
            max_results_per_query=2,
            max_sources=2,
        )
        self.rubric = load_evaluation_configuration()

    @staticmethod
    def request(topic):
        return InputRequest(
            domain="AI engineering",
            interests=[topic],
            time_limit_days=30,
            desired_candidate_count=1,
            finalist_count=1,
        )

    async def test_sequential_and_parallel_runs_use_only_their_own_chunks(self):
        for mode in ("sequential", "parallel"):
            with self.subTest(mode=mode):
                judge = RecordingJudge()
                template_critic = CriticWorker(InMemoryRetriever([]), judge)
                coordinator = Orchestrator(Scout(), Library(), template_critic)

                first = await coordinator.run(self.request("alpha"), self.search, self.rubric, mode=mode)
                second = await coordinator.run(self.request("beta"), self.search, self.rubric, mode=mode)

                self.assertEqual(judge.evidence_by_topic, {
                    "alpha": ["source-alpha"],
                    "beta": ["source-beta"],
                })
                self.assertNotEqual(first.run_id, second.run_id)
                self.assertEqual(first.retrieval_index.indexed_chunk_count, 1)
                self.assertEqual(second.retrieval_index.backend, "lexical_in_memory")
                self.assertEqual(second.retrieval_index.retention, "run_only")
                self.assertEqual(second.retrieval_index.retrieval_top_k, self.rubric.retrieval_top_k)
                self.assertEqual(template_critic.retriever.chunks, [])

    async def test_insufficient_coverage_skips_index_creation(self):
        judge = RecordingJudge()
        coordinator = Orchestrator(
            Scout(), Library(), CriticWorker(InMemoryRetriever([]), judge)
        )
        strict_search = self.search.model_copy(update={"minimum_source_count": 2})

        result = await coordinator.run(self.request("alpha"), strict_search, self.rubric)

        self.assertEqual(result.status, "insufficient_coverage")
        self.assertIsNone(result.retrieval_index)
        self.assertEqual(judge.evidence_by_topic, {})

    async def test_concurrent_runs_on_one_coordinator_keep_indexes_separate(self):
        judge = RecordingJudge()
        coordinator = Orchestrator(
            Scout(), Library(), CriticWorker(InMemoryRetriever([]), judge)
        )

        first, second = await asyncio.gather(
            coordinator.run(self.request("alpha"), self.search, self.rubric),
            coordinator.run(self.request("beta"), self.search, self.rubric),
        )

        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")
        self.assertEqual(judge.evidence_by_topic, {
            "alpha": ["source-alpha"],
            "beta": ["source-beta"],
        })

    async def test_retriever_snapshots_library_chunks(self):
        library = await Library().run(self.request("alpha"), self.search)
        retriever = InMemoryRetriever(library.chunks)
        library.chunks[0].text = "Changed after indexing."

        hits = await retriever.search("alpha", 1)

        self.assertEqual(hits[0].chunk.text, "Evidence for the alpha project.")


if __name__ == "__main__":
    unittest.main()
