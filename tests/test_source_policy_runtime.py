"""Both branches apply resolved per-type caps and published-date limits."""

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from src.adapters import build_available_adapters
from src.models import InputRequest, ResolvedSearchConfiguration, ScoutQuery, SourceQuery, SourceRecord
from src.models.source_record import RetrievalStatus
from src.orchestration.coordinator import Orchestrator
from src.workers.library_worker import LibraryWorker
from src.workers.scout_worker import ScoutWorker


class Adapter:
    async def search(self, query):
        records = []
        for number, published in enumerate((date(2020, 1, 1), date(2026, 1, 1), date(2026, 2, 1))):
            records.append(SourceRecord(
                source_id=f"article-{number}",
                provider=query.provider_id,
                source_type="web_article",
                title=f"Article {number}",
                captured_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
                published_at=published,
                canonical_url=f"https://example.org/article-{number}",
                query_id=query.query_id,
                abstract_or_snippet="Current research evidence.",
                content_hash=f"hash-{number}",
                retrieval_status=RetrievalStatus.SUCCESS,
            ))
        return records[:query.max_results]


class Planner:
    def __init__(self, query_type):
        self.query_type = query_type

    async def plan(self, request, search):
        return [self.query_type(
            query_id="query-1",
            provider_id="fixture",
            text="current research",
            source_types=["web_article"],
            content_types=["metadata"],
            max_results=3,
        )]


class Generator:
    async def generate(self, request, sources):
        return []


class SourcePolicyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_queries_deduplicate_but_changed_content_is_rejected(self):
        class RepeatedPlanner(Planner):
            async def plan(self, request, search):
                first = (await super().plan(request, search))[0]
                return [first, first.model_copy(update={"query_id": "query-2"})]

        class ChangingAdapter(Adapter):
            async def search(self, query):
                records = await super().search(query)
                if query.query_id == "query-2":
                    records[0].abstract_or_snippet = "Different source content"
                return records

        search = ResolvedSearchConfiguration(
            domain="AI engineering", providers=[{"provider_id": "fixture",
                "source_types": ["web_article"], "content_types": ["metadata"]}],
            content_types=["metadata"], max_queries=2, max_results_per_query=3, max_sources=6,
        )
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        for worker, query_type in ((ScoutWorker, ScoutQuery), (LibraryWorker, SourceQuery)):
            def build(adapter):
                args = [{"fixture": adapter}, RepeatedPlanner(query_type)]
                if worker is ScoutWorker:
                    args.append(Generator())
                return worker(*args)
            result = await build(Adapter()).run(request, search)
            self.assertEqual(len(result.sources), 3)
            with self.assertRaisesRegex(ValueError, "conflicting records"):
                await build(ChangingAdapter()).run(request, search)

    async def test_tavily_query_snippets_deduplicate_by_canonical_url(self):
        class TavilyAdapter:
            async def search(self, query):
                snippet = f"Query-specific result excerpt for {query.query_id}."
                return [SourceRecord(
                    source_id="web-same-page", provider="tavily", source_type="web_article",
                    title=f"Query-specific title {query.query_id}",
                    canonical_url="https://example.org/research",
                    query_id=query.query_id, abstract_or_snippet=snippet,
                    content_hash=f"hash-{query.query_id}",
                    captured_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
                    retrieval_status=RetrievalStatus.SUCCESS,
                )]

        class TavilyPlanner:
            async def plan(self, request, search):
                return [ScoutQuery(
                    query_id=f"query-{number}", provider_id="tavily", text="research",
                    source_types=["web_article"], content_types=["page_snippet"], max_results=1,
                ) for number in (1, 2)]

        class TavilyLibraryPlanner:
            async def plan(self, request, search):
                return [SourceQuery(
                    query_id=f"query-{number}", provider_id="tavily", text="research",
                    source_types=["web_article"], content_types=["page_snippet"], max_results=1,
                ) for number in (1, 2)]

        search = ResolvedSearchConfiguration(
            domain="AI engineering", providers=[{"provider_id": "tavily",
                "source_types": ["web_article"], "content_types": ["page_snippet"]}],
            content_types=["page_snippet"], max_queries=2, max_results_per_query=1,
            max_sources=3, minimum_source_count=1,
        )
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        scout = await ScoutWorker({"tavily": TavilyAdapter()}, TavilyPlanner(), Generator()).run(
            request, search
        )
        library = await LibraryWorker({"tavily": TavilyAdapter()}, TavilyLibraryPlanner()).run(
            request, search
        )
        self.assertEqual(len(scout.sources), 1)
        self.assertEqual(len(library.sources), 1)
        merged = Orchestrator._merge_sources(scout.sources, library.sources)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0].excerpts), 2)
        self.assertEqual({chunk.text for chunk in library.chunks}, {
            "Query-specific result excerpt for query-1.",
            "Query-specific result excerpt for query-2.",
        })

    async def test_both_workers_apply_type_and_age_caps(self):
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[{
                "provider_id": "fixture",
                "source_types": ["web_article"],
                "content_types": ["metadata"],
            }],
            content_types=["metadata"],
            max_queries=2,
            max_results_per_query=3,
            max_sources=3,
            max_records_by_type={"web_article": 1},
            max_age_days_by_type={"web_article": 365},
            as_of_date=date(2026, 9, 25),
        )
        adapter = {"fixture": Adapter()}

        scout = await ScoutWorker(adapter, Planner(ScoutQuery), Generator()).run(request, search)
        library = await LibraryWorker(adapter, Planner(SourceQuery)).run(request, search)

        self.assertEqual([source.source_id for source in scout.sources], ["article-1"])
        self.assertEqual([source.source_id for source in library.sources], ["article-1"])

    def test_adapter_registry_requires_explicit_live_mode_and_credentials(self):
        self.assertEqual(build_available_adapters(), {})
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            self.assertEqual(set(build_available_adapters(include_live=True)), {"github"})
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            self.assertEqual(set(build_available_adapters(include_live=True)),
                             {"github", "tavily"})


if __name__ == "__main__":
    unittest.main()
