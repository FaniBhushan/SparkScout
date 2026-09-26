"""Shared UI/CLI choices resolve through one reviewed configuration path."""

import unittest
from datetime import date

from src.models import (
    InputRequest,
    PromptInterpretationDraft,
    PromptSuggestions,
    RequestSuggestions,
    SearchConfiguration,
    SourcePolicy,
    SubmittedRunConfiguration,
)
from src.preflight import prepare_run
from src.ui.configuration import interface_catalog, submitted_from_controls
from src.workers.source_filter import source_is_within_age_limit


class NoSearchAdapter:
    async def search(self, query):
        raise AssertionError("configuration must not research")


class InterfaceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.adapters = {"github": NoSearchAdapter(), "tavily": NoSearchAdapter()}

    def test_catalog_shows_only_ready_capabilities(self):
        catalog = interface_catalog({"github": NoSearchAdapter()})

        self.assertEqual(catalog.providers, ["github"])
        self.assertEqual(catalog.source_types, ["code_repository"])
        self.assertEqual(catalog.content_types, ["metadata"])
        self.assertNotIn("scholarly_article", catalog.source_types)
        self.assertNotIn("full_text", catalog.content_types)

    def test_simple_and_advanced_equivalent_choices_share_checksum(self):
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        simple = prepare_run(SubmittedRunConfiguration(request=request), self.adapters)
        advanced = prepare_run(SubmittedRunConfiguration(
            request=request, search=SearchConfiguration(mode="advanced")
        ), self.adapters)

        self.assertEqual(simple.configuration_checksum, advanced.configuration_checksum)

    def test_confirmed_deduction_beats_untouched_control_default(self):
        draft = PromptInterpretationDraft(
            original_prompt="AI engineering in 20 days; prioritize evidence",
            suggestions=PromptSuggestions(
                request=RequestSuggestions(domain="AI engineering", time_limit_days=20),
                evaluation={"rubric_preset": "evidence-first"},
            ),
        )
        values = {
            "request.domain": "AI engineering",
            "request.time_limit_days": 30,
            "evaluation.rubric_preset": "balanced",
        }
        submitted = submitted_from_controls(
            values, set(), prompt=draft.original_prompt, draft=draft,
            accepted_paths={
                "request.domain", "request.time_limit_days", "evaluation.rubric_preset"
            },
        )

        self.assertEqual(submitted.request.time_limit_days, 20)
        self.assertEqual(submitted.evaluation.rubric_preset, "evidence-first")
        self.assertEqual(submitted.field_origins["request.time_limit_days"], "deduced")

        corrected = submitted_from_controls(
            values, {"request.time_limit_days"}, prompt=draft.original_prompt, draft=draft,
            accepted_paths={"request.domain", "request.time_limit_days"},
        )
        self.assertEqual(corrected.request.time_limit_days, 30)
        self.assertEqual(corrected.field_origins["request.time_limit_days"], "explicit")

    def test_unreviewed_prompt_and_conflicting_source_rules_fail(self):
        values = {"request.domain": "AI engineering", "request.time_limit_days": 30}
        with self.assertRaisesRegex(ValueError, "interpreted and reviewed"):
            submitted_from_controls(values, set(), prompt="Use peer-reviewed articles")
        with self.assertRaisesRegex(ValueError, "included and excluded"):
            submitted_from_controls({
                **values,
                "search.source_policy": {
                    "include_types": ["web_article"], "exclude_types": ["web_article"]
                },
            }, {"search.source_policy"})

    def test_date_tier_recency_and_fallback_are_enforced(self):
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        prepared = prepare_run(SubmittedRunConfiguration(
            request=request,
            search=SearchConfiguration(
                evidence_tiers=["scholarly"],
                recency_days=365,
                published_from=date(2026, 1, 1),
            ),
        ), self.adapters)
        self.assertEqual(
            [provider.provider_id for provider in prepared.search.providers], ["github"]
        )
        self.assertEqual(prepared.request.source_policy.include_types, ["code_repository"])
        self.assertTrue(prepared.search.require_published_date)

        from src.models import SourceRecord
        source = SourceRecord.model_validate({
            "source_id": "repo-1", "provider": "github", "source_type": "code_repository",
            "title": "Example", "captured_at": "2026-09-25T00:00:00Z",
            "query_id": "q-1", "content_hash": "a" * 64,
            "canonical_url": "https://example.org/repo", "retrieval_status": "success",
        })
        self.assertFalse(source_is_within_age_limit(source, prepared.search))
        with self.assertRaisesRegex(ValueError, "enabled providers are unavailable"):
            prepare_run(SubmittedRunConfiguration(
                request=request,
                search=SearchConfiguration(fallback_policy="fail_if_unavailable"),
            ), {"github": NoSearchAdapter()})


if __name__ == "__main__":
    unittest.main()
