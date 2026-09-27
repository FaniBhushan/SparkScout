"""Resolution of source catalog, presets, routes, and request policy."""

import unittest

from src.configuration.loader import load_source_configuration, resolve_search_configuration
from src.models import DomainRoute, InputRequest, SearchLimits


class ReadyAdapter:
    async def search(self, query):
        return []


class SearchResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = InputRequest(domain="AI engineering", time_limit_days=30)
        self.adapters = {
            "github": ReadyAdapter(),
            "tavily": ReadyAdapter(),
            "openalex": ReadyAdapter(),
        }

    def test_preset_selects_only_enabled_ready_providers(self) -> None:
        resolved = resolve_search_configuration(self.request, self.adapters)

        self.assertEqual(
            [provider.provider_id for provider in resolved.providers],
            ["github", "tavily"],
        )
        self.assertEqual(resolved.providers[0].source_types, ["code_repository"])
        self.assertEqual(resolved.providers[0].content_types, ["metadata"])
        self.assertEqual(resolved.providers[1].content_types, ["metadata", "page_snippet"])
        self.assertEqual(resolved.content_types, ["metadata", "page_snippet"])
        self.assertEqual((resolved.max_queries, resolved.max_sources), (8, 40))
        self.assertEqual(resolved.minimum_source_count, 3)
        self.assertEqual(resolved.max_age_days_by_type["code_repository"], 1095)
        self.assertIsNotNone(resolved.as_of_date)
        self.assertEqual(resolved.domain, self.request.domain)

    def test_unavailable_adapter_and_excluded_type_are_removed(self) -> None:
        request = self.request.model_copy(
            update={"source_policy": self.request.source_policy.model_copy(
                update={"exclude_types": ["web_article"]}
            )}
        )
        resolved = resolve_search_configuration(request, {"github": ReadyAdapter()})

        self.assertEqual([provider.provider_id for provider in resolved.providers], ["github"])
        self.assertEqual(resolved.content_types, ["metadata"])

    def test_route_uses_fallback_to_cover_required_type(self) -> None:
        sources = load_source_configuration().model_copy(deep=True)
        sources.routes["ai_engineering"] = DomainRoute(
            providers=["github"],
            fallback_providers=["tavily"],
            required_types=["web_article"],
        )

        resolved = resolve_search_configuration(
            self.request, self.adapters, sources=sources
        )

        self.assertEqual(
            [provider.provider_id for provider in resolved.providers],
            ["github", "tavily"],
        )
        self.assertEqual(resolved.required_source_types, ["web_article"])

    def test_missing_required_type_fails_before_research(self) -> None:
        request = self.request.model_copy(
            update={"source_policy": self.request.source_policy.model_copy(
                update={"required_types": ["official_dataset"]}
            )}
        )

        with self.assertRaisesRegex(ValueError, "official_dataset"):
            resolve_search_configuration(request, self.adapters)

    def test_unknown_domain_and_preset_fail(self) -> None:
        request = self.request.model_copy(update={"domain": "unknown domain"})
        with self.assertRaisesRegex(ValueError, "unknown source domain"):
            resolve_search_configuration(request, self.adapters)
        with self.assertRaisesRegex(ValueError, "unknown search preset"):
            resolve_search_configuration(self.request, self.adapters, preset_name="missing")

    def test_requested_limits_cannot_exceed_hard_limits_or_lower_coverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "hard limit"):
            resolve_search_configuration(
                self.request,
                self.adapters,
                requested_limits=SearchLimits(
                    max_queries=13, max_results_per_query=10, max_sources=40
                ),
            )
        with self.assertRaisesRegex(ValueError, "minimum_source_count"):
            resolve_search_configuration(
                self.request,
                self.adapters,
                requested_limits=SearchLimits(
                    max_queries=8, max_results_per_query=10, max_sources=2
                ),
            )

    def test_requested_limits_within_hard_limits_are_used(self) -> None:
        resolved = resolve_search_configuration(
            self.request,
            self.adapters,
            requested_limits=SearchLimits(
                max_queries=4, max_results_per_query=5, max_sources=12
            ),
        )

        self.assertEqual(
            (resolved.max_queries, resolved.max_results_per_query, resolved.max_sources),
            (4, 5, 12),
        )

    def test_per_type_record_caps_override_catalog_defaults(self) -> None:
        request = self.request.model_copy(
            update={"source_policy": self.request.source_policy.model_copy(
                update={"max_records_by_type": {"web_article": 2}}
            )}
        )

        resolved = resolve_search_configuration(request, self.adapters)

        self.assertEqual(resolved.max_records_by_type["web_article"], 2)
        self.assertEqual(resolved.max_records_by_type["code_repository"], 10)

    def test_record_cap_for_unavailable_type_is_rejected(self) -> None:
        request = self.request.model_copy(
            update={"source_policy": self.request.source_policy.model_copy(
                update={"max_records_by_type": {"official_dataset": 2}}
            )}
        )

        with self.assertRaisesRegex(ValueError, "unavailable source types"):
            resolve_search_configuration(request, self.adapters)


if __name__ == "__main__":
    unittest.main()
