"""Public source identity, receipt preservation, and stable evidence citations."""

import unittest
from datetime import datetime, timezone
from itertools import permutations
from unittest.mock import AsyncMock, patch

from src.models.source_record import RetrievalStatus, SourceRecord
from src.orchestration.coordinator import Orchestrator
from src.sources.merge import canonical_source_url, capture_excerpts, merge_source_records
from src.workers.evidence import build_source_chunks
from src.evaluation import load_evaluation_configuration
from src.models import CriticResult, InputRequest, LibraryResult, ResolvedSearchConfiguration, ScoutResult
from src.models.scout_query import SourceQuery
from src.adapters.tavily import TavilyAdapter


def record(query="query-1", text="First excerpt", **updates):
    values = dict(
        source_id="web-test", provider="tavily", source_type="web_article",
        title=f"Title for {query}", canonical_url="https://example.org/paper?id=42",
        captured_at=datetime(2026, 9, 27, tzinfo=timezone.utc), query_id=query,
        abstract_or_snippet=text, content_hash=f"hash-{query}",
        retrieval_status=RetrievalStatus.SUCCESS,
    )
    return SourceRecord(**(values | updates))


class SourceMergeTests(unittest.TestCase):
    def test_url_normalization_preserves_content_parameters(self):
        self.assertEqual(canonical_source_url(
            "https://EXAMPLE.org/paper?id=42&utm_source=test&lang=en#section"
        ), "https://example.org/paper?id=42&lang=en")
        self.assertNotEqual(canonical_source_url("https://example.org/?id=1"),
                            canonical_source_url("https://example.org/?id=2"))

    def test_distinct_excerpts_survive_serialization_and_keep_citations(self):
        merged = merge_source_records(record(), record("query-2", "Second excerpt"))
        restored = SourceRecord.model_validate_json(merged.model_dump_json())
        self.assertEqual(len(restored.excerpts), 2)
        original_chunks = build_source_chunks([capture_excerpts(record())])
        merged_chunks = build_source_chunks([restored])
        self.assertIn(original_chunks[0].chunk_id, {chunk.chunk_id for chunk in merged_chunks})
        self.assertEqual({chunk.text for chunk in merged_chunks}, {"First excerpt", "Second excerpt"})
        self.assertTrue(all(chunk.source_id == merged.source_id for chunk in merged_chunks))

    def test_identical_text_has_one_chunk_but_keeps_both_receipts(self):
        merged = merge_source_records(record(), record("query-2"))
        self.assertEqual(len(merged.excerpts), 1)
        self.assertEqual(len(merged.excerpts[0].receipts), 2)
        self.assertEqual(len(build_source_chunks([merged])), 1)

    def test_merge_is_independent_of_order_and_grouping(self):
        records = [record(), record("query-2", "Second excerpt"), record("query-3")]
        expected = Orchestrator._merge_sources(records)[0].model_dump()
        for ordered in permutations(records):
            self.assertEqual(Orchestrator._merge_sources(list(ordered))[0].model_dump(), expected)
            combined = merge_source_records(merge_source_records(*ordered[:2]), ordered[2])
            self.assertEqual(combined.model_dump(), expected)

    def test_conflicting_identity_cannot_be_merged(self):
        with self.assertRaisesRegex(ValueError, "conflicting records"):
            merge_source_records(record(), record(canonical_url="https://example.org/other"))

    def test_github_repository_id_survives_repository_rename(self):
        first = record(provider="github", source_type="code_repository", provider_record_id="123")
        second = record("query-2", "New description", provider="github", source_type="code_repository",
                        provider_record_id="123", canonical_url="https://github.com/new/name")
        self.assertEqual(len(merge_source_records(first, second).excerpts), 2)

    def test_private_upload_text_is_not_added_to_serialized_excerpts(self):
        upload = record(provider="user_upload", full_text="Private document")
        captured = capture_excerpts(upload)
        self.assertEqual(captured.excerpts, [])
        self.assertNotIn("Private document", captured.model_dump_json())


class SourceJoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_tavily_tracking_urls_get_the_same_source_id(self):
        payload = {"results": [
            {"title": "Paper", "url": "https://example.org/paper?id=42&utm_source=test#part",
             "content": "First excerpt"},
            {"title": "Paper result", "url": "https://example.org/paper?id=42",
             "content": "Second excerpt"},
        ]}
        with patch("src.adapters.tavily.request_json", new=AsyncMock(return_value=payload)):
            records = await TavilyAdapter(api_key="test-placeholder").search(SourceQuery(
                query_id="query-1", provider_id="tavily", text="research",
                source_types=["web_article"], content_types=["page_snippet"], max_results=2,
            ))
        self.assertEqual(records[0].source_id, records[1].source_id)
        self.assertEqual(len(merge_source_records(*records).excerpts), 2)

    async def run_join(self, scout_source, library_source, mode):
        class Scout:
            async def run(self, request, search):
                return ScoutResult(sources=[scout_source])

        class Library:
            async def run(self, request, search):
                return LibraryResult(sources=[library_source], chunks=build_source_chunks([library_source]))

        class Critic:
            def with_retriever(self, retriever):
                return self

            async def run(self, request, candidates, library, rubric):
                return CriticResult()

        search = ResolvedSearchConfiguration(
            domain="ai_engineering", providers=[{"provider_id": "tavily",
                "source_types": ["web_article"], "content_types": ["page_snippet"]}],
            content_types=["page_snippet"], minimum_source_count=1,
            max_queries=2, max_results_per_query=2, max_sources=4,
        )
        return await Orchestrator(Scout(), Library(), Critic()).run(
            InputRequest(domain="ai_engineering", time_limit_days=30), search,
            load_evaluation_configuration(), mode=mode,
        )

    async def test_both_modes_index_scout_and_library_excerpts_with_stable_ids(self):
        scout = capture_excerpts(record(text="Scout evidence for evaluation"))
        library = capture_excerpts(record("query-2", "Library evidence for evaluation"))
        original_id = build_source_chunks([library])[0].chunk_id
        runs = [await self.run_join(scout, library, mode) for mode in ("sequential", "parallel")]
        for result in runs:
            self.assertEqual({chunk.text for chunk in result.library.chunks},
                             {"Scout evidence for evaluation", "Library evidence for evaluation"})
            self.assertIn(original_id, {chunk.chunk_id for chunk in result.library.chunks})
        self.assertEqual(runs[0].library, runs[1].library)

    async def test_identity_collision_is_quarantined_and_coverage_is_rechecked(self):
        result = await self.run_join(record(), record(canonical_url="https://example.org/other"), "parallel")
        self.assertFalse(result.source_manifest)
        self.assertFalse(result.library.chunks)
        self.assertEqual(result.status, "insufficient_coverage")
        self.assertTrue(any("quarantined" in warning for warning in result.warnings))

    async def test_legacy_library_chunks_keep_their_id_without_duplicate_text(self):
        library = record("query-2", "Library evidence")
        result = await self.run_join(record(), library, "sequential")
        self.assertEqual(sum(chunk.text == "Library evidence" for chunk in result.library.chunks), 1)
        self.assertIn("web-test-c0", {chunk.chunk_id for chunk in result.library.chunks})
