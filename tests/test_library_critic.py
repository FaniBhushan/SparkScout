"""Focused contract tests for the Library and Critic workers."""

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
    ResolvedSearchConfiguration,
    SourceQuery,
    SourceRecord,
)
from src.models.common import EvidenceReference
from src.models.source_record import RetrievalStatus
from src.adapters.http_json import SourceRateLimitError
from src.retrieval import InMemoryRetriever
from src.workers.critic_worker import CriticWorker
from src.workers.library_worker import LibraryWorker


class Planner:
    async def plan(self, request, search):
        return [
            SourceQuery(
                query_id="library-1",
                provider_id="fixture",
                text="accessible capstone datasets",
                source_types=["dataset"],
                content_types=["text"],
                max_results=2,
            )
        ]


class Adapter:
    async def search(self, query):
        return [
            SourceRecord(
                source_id="source-1",
                provider="fixture",
                source_type="dataset",
                title="Accessible capstone dataset",
                captured_at=datetime.now(timezone.utc),
                canonical_url="https://example.org/dataset",
                query_id=query.query_id,
                abstract_or_snippet="Accessible capstone dataset for testing evaluation methods.",
                content_hash="source-hash",
                retrieval_status=RetrievalStatus.SUCCESS,
            )
        ]


class Judge:
    async def assess(self, request, candidate, evidence, rubric):
        ref = EvidenceReference(
            source_id=evidence[0].chunk.source_id,
            chunk_id=evidence[0].chunk.chunk_id,
        )
        return CandidateAssessment(
            criteria={
                key: CriterionJudgment(score=4, rationale="Supported by dataset.", evidence=[ref])
                for key in rubric.criteria
            },
            hard_gates={
                key: GateJudgment(passed=True, rationale="Passes constraint.", evidence=[ref])
                for key in rubric.hard_gates
            },
        )


class LibraryCriticTests(unittest.TestCase):
    def setUp(self):
        self.request = InputRequest(domain="AI engineering", time_limit_days=30)
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
        self.candidate = CandidateIdea(
            candidate_id="candidate-1",
            title="Accessible capstone",
            problem_statement="Test a capstone dataset with clear evaluation methods.",
            target_users=["Students"],
            proposed_outcome="Evaluated prototype",
            why_it_matters="Shows practical performance",
        )

    def test_library_and_critic_apply_configured_weights(self):
        library = asyncio.run(
            LibraryWorker({"fixture": Adapter()}, Planner()).run(self.request, self.search)
        )
        self.assertEqual(len(library.chunks), 1)
        rubric = load_evaluation_configuration()
        result = asyncio.run(
            CriticWorker(InMemoryRetriever(library.chunks), Judge()).run(
                self.request, [self.candidate], library, rubric
            )
        )
        evaluation = result.evaluations[0]
        self.assertEqual(evaluation.total_score, 80)
        self.assertTrue(evaluation.gate_passed)
        self.assertEqual(
            {item.criterion_id: item.weight for item in evaluation.criteria},
            {key: item.weight for key, item in rubric.criteria.items()},
        )

    def test_custom_weights_allow_zero_but_must_total_100(self):
        balanced = load_evaluation_configuration()
        self.assertEqual(balanced.criteria["real_world_pain_point"].weight, 10)
        for preset in ("balanced", "feasibility-first", "innovation-first", "evidence-first"):
            configured = load_evaluation_configuration(preset)
            self.assertIn("real_world_pain_point", configured.criteria)
            self.assertEqual(sum(item.weight for item in configured.criteria.values()), 100)
        weights = {key: 0 for key in balanced.criteria}
        weights["feasibility"] = 100
        custom = load_evaluation_configuration(weights=weights)
        self.assertEqual(custom.criteria["novelty"].weight, 0)
        weights["feasibility"] = 99
        with self.assertRaises(ValueError):
            load_evaluation_configuration(weights=weights)

    def test_critic_skips_candidate_with_citations_outside_retrieved_context(self):
        class BadJudge(Judge):
            async def assess(self, request, candidate, evidence, rubric):
                assessment = await super().assess(request, candidate, evidence, rubric)
                assessment.criteria["feasibility"].evidence = [
                    EvidenceReference(source_id="unseen", chunk_id="unseen-c0")
                ]
                return assessment

        library = asyncio.run(
            LibraryWorker({"fixture": Adapter()}, Planner()).run(self.request, self.search)
        )
        result = asyncio.run(
            CriticWorker(InMemoryRetriever(library.chunks), BadJudge()).run(
                self.request, [self.candidate], library, load_evaluation_configuration()
            )
        )
        self.assertEqual(result.evaluations, [])
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("citation check failed", result.warnings[0])

    def test_critic_normalizes_source_id_from_an_exact_retrieved_chunk(self):
        class MismatchedSourceJudge(Judge):
            async def assess(self, request, candidate, evidence, rubric):
                assessment = await super().assess(request, candidate, evidence, rubric)
                ref = assessment.criteria["feasibility"].evidence[0]
                ref.source_id = "incorrect-source"
                return assessment

        library = asyncio.run(
            LibraryWorker({"fixture": Adapter()}, Planner()).run(self.request, self.search)
        )
        result = asyncio.run(
            CriticWorker(InMemoryRetriever(library.chunks), MismatchedSourceJudge()).run(
                self.request, [self.candidate], library, load_evaluation_configuration()
            )
        )
        self.assertEqual(len(result.evaluations), 1)
        self.assertTrue(any("citation reference was normalized" in item
                            for item in result.warnings))

    def test_library_keeps_optional_provider_rate_limit_local(self):
        class LimitedAdapter:
            async def search(self, query):
                raise SourceRateLimitError("github", "limited", status=429)

        class GitHubPlanner:
            async def plan(self, request, search):
                return [SourceQuery(
                    query_id="github-query", provider_id="github",
                    text="accessible capstone datasets", source_types=["dataset"],
                    content_types=["text"], max_results=2,
                )]

        github_provider = self.search.providers[0].model_copy(update={"provider_id": "github"})
        search = self.search.model_copy(update={"providers": [github_provider]})
        result = asyncio.run(
            LibraryWorker({"github": LimitedAdapter()}, GitHubPlanner()).run(self.request, search)
        )
        self.assertFalse(result.sources)
        self.assertTrue(any("continuing with other available sources" in item
                            for item in result.warnings))

    def test_failed_hard_gate_disqualifies_a_high_scoring_candidate(self):
        class FailingJudge(Judge):
            async def assess(self, request, candidate, evidence, rubric):
                assessment = await super().assess(request, candidate, evidence, rubric)
                assessment.hard_gates["data_access"].passed = False
                assessment.hard_gates["data_access"].rationale = "Data access is not confirmed."
                return assessment

        library = asyncio.run(
            LibraryWorker({"fixture": Adapter()}, Planner()).run(self.request, self.search)
        )
        result = asyncio.run(
            CriticWorker(InMemoryRetriever(library.chunks), FailingJudge()).run(
                self.request, [self.candidate], library, load_evaluation_configuration()
            )
        )
        evaluation = result.evaluations[0]
        self.assertEqual(evaluation.total_score, 80)
        self.assertFalse(evaluation.gate_passed)
        self.assertIn("data_access", evaluation.rejection_reasons[0])


if __name__ == "__main__":
    unittest.main()
