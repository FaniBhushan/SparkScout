"""Contract checks for provider-specific resolved search permissions."""

import unittest

from pydantic import ValidationError

from src.models import ResolvedSearchConfiguration


class ResolvedSearchConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.configuration = {
            "domain": "AI engineering",
            "providers": [
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
            "content_types": ["metadata", "page_snippet"],
            "max_queries": 8,
            "max_results_per_query": 10,
            "max_sources": 40,
        }

    def test_keeps_content_permissions_per_provider(self) -> None:
        resolved = ResolvedSearchConfiguration.model_validate(self.configuration)

        self.assertEqual(resolved.providers[0].content_types, ["metadata"])
        self.assertEqual(
            resolved.providers[1].content_types, ["metadata", "page_snippet"]
        )

    def test_rejects_provider_without_content_types(self) -> None:
        self.configuration["providers"][0].pop("content_types")

        with self.assertRaises(ValidationError):
            ResolvedSearchConfiguration.model_validate(self.configuration)

    def test_rejects_global_content_types_that_differ_from_providers(self) -> None:
        self.configuration["content_types"] = ["metadata"]

        with self.assertRaisesRegex(ValidationError, "must match"):
            ResolvedSearchConfiguration.model_validate(self.configuration)

    def test_rejects_duplicate_provider_ids(self) -> None:
        self.configuration["providers"][1]["provider_id"] = "github"

        with self.assertRaisesRegex(ValidationError, "must be unique"):
            ResolvedSearchConfiguration.model_validate(self.configuration)


if __name__ == "__main__":
    unittest.main()
