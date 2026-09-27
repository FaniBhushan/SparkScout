"""Research workers enforce provider-specific query permissions."""

import unittest

from src.models import InputRequest, ResolvedSearchConfiguration, ScoutQuery, SourceQuery
from src.workers.library_worker import LibraryWorker
from src.workers.scout_worker import ScoutWorker


class FixedPlanner:
    def __init__(self, query: SourceQuery) -> None:
        self.query = query

    async def plan(self, request, search):
        return [self.query]


class PermissionCheckingAdapter:
    def __init__(self, provider):
        self.provider = provider

    async def search(self, query):
        # Recovery may issue a new, valid query after the invalid plan is skipped.
        assert query.provider_id == self.provider.provider_id
        assert set(query.content_types).issubset(self.provider.content_types)
        assert set(query.source_types).issubset(self.provider.source_types)
        return []


class UncalledGenerator:
    async def generate(self, request, sources):
        raise AssertionError("invalid query reached candidate generation")


class QueryPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.request = InputRequest(domain="AI engineering", time_limit_days=30)
        self.search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[
                {
                    "provider_id": "github",
                    "source_types": ["code_repository"],
                    "content_types": ["metadata"],
                },
                {
                    "provider_id": "tavily",
                    "source_types": ["web_article"],
                    "content_types": ["metadata", "page_snippet"],
                },
            ],
            content_types=["metadata", "page_snippet"],
            max_queries=2,
            max_results_per_query=2,
            max_sources=2,
        )
        self.adapters = {provider.provider_id: PermissionCheckingAdapter(provider)
                         for provider in self.search.providers}

    async def test_scout_skips_content_unavailable_from_selected_provider(self) -> None:
        query = ScoutQuery(
            query_id="scout-q-01",
            provider_id="github",
            text="find capstone repositories",
            source_types=["code_repository"],
            content_types=["page_snippet"],
            max_results=2,
        )
        worker = ScoutWorker(self.adapters, FixedPlanner(query), UncalledGenerator())

        result = await worker.run(self.request, self.search)
        self.assertIn("no allowed source/content types", " ".join(result.warnings))

    async def test_library_skips_content_unavailable_from_selected_provider(self) -> None:
        query = SourceQuery(
            query_id="library-q-01",
            provider_id="github",
            text="find capstone repositories",
            source_types=["code_repository"],
            content_types=["page_snippet"],
            max_results=2,
        )
        worker = LibraryWorker(self.adapters, FixedPlanner(query))

        result = await worker.run(self.request, self.search)
        self.assertIn("no allowed source/content types", " ".join(result.warnings))


if __name__ == "__main__":
    unittest.main()
