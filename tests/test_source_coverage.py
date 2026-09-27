"""Coverage recovery uses actual receipts and stays inside approved search caps."""

import unittest

from src.adapters import FrozenFixtureAdapter
from src.models import InputRequest, ResolvedSearchConfiguration, SourceQuery
from src.workers.source_coverage import recover_source_coverage


class CoverageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = InputRequest(domain="robotics", time_limit_days=30)
        self.search = ResolvedSearchConfiguration(domain="robotics", providers=[{
            "provider_id": "frozen_fixture", "source_types": ["official_dataset",
                "scholarly_article", "code_repository", "community_signal"],
            "content_types": ["snippet"]}], content_types=["snippet"],
            max_queries=4, max_results_per_query=4, max_sources=4,
            minimum_source_count=3, required_source_types=["community_signal"])
        self.adapter = FrozenFixtureAdapter("robotics_agriculture_01")

    async def initial_sources(self):
        return await self.adapter.search(SourceQuery(query_id="q1", provider_id="frozen_fixture",
            text="crop images", source_types=["official_dataset", "community_signal"],
            content_types=["snippet"], max_results=4))

    async def test_actual_receipts_not_planned_types_trigger_recovery(self):
        initial = await self.initial_sources()
        self.assertEqual(len(initial), 2)
        sources, warnings = await recover_source_coverage(self.request, self.search, initial,
            {"frozen_fixture": self.adapter}, planned_queries=3, stage="library")
        self.assertGreaterEqual(len(sources), 3)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len({source.source_id for source in sources}), len(sources))

    async def test_exhausted_query_allowance_never_calls_adapter(self):
        class ForbiddenAdapter:
            async def search(self, query):
                raise AssertionError("budget exceeded")
        initial = await self.initial_sources()
        sources, warnings = await recover_source_coverage(self.request, self.search, initial,
            {"frozen_fixture": ForbiddenAdapter()}, planned_queries=4, stage="library")
        self.assertEqual(sources, initial)
        self.assertFalse(warnings)
