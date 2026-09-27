"""The reviewed search and rubric must be valid before research can start."""

import unittest

from pydantic import ValidationError

from src.models import (
    EvaluationSelection,
    InputRequest,
    PreparedRun,
    SearchConfiguration,
    SearchLimits,
    SourcePolicy,
    SubmittedRunConfiguration,
)
from src.application.preflight import prepare_run


class ReadyAdapter:
    async def search(self, query):
        raise AssertionError("preflight must not search sources")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.request = InputRequest(domain="AI engineering", time_limit_days=30)
        self.adapters = {"github": ReadyAdapter(), "tavily": ReadyAdapter()}

    def test_preflight_resolves_defaults_and_records_origins(self):
        prepared = prepare_run(
            SubmittedRunConfiguration(request=self.request), self.adapters
        )

        self.assertEqual(
            [provider.provider_id for provider in prepared.search.providers],
            ["github", "tavily"],
        )
        self.assertEqual(prepared.evaluation.preset, "balanced")
        self.assertEqual(prepared.field_origins["request.domain"], "explicit")
        self.assertEqual(prepared.field_origins["search.preset"], "preset")
        self.assertEqual(prepared.field_origins["evaluation.weights"], "preset")
        self.assertEqual(len(prepared.configuration_checksum), 64)

    def test_equivalent_modes_have_the_same_effective_checksum(self):
        simple = prepare_run(
            SubmittedRunConfiguration(request=self.request), self.adapters
        )
        advanced = prepare_run(
            SubmittedRunConfiguration(
                request=self.request,
                search=SearchConfiguration(mode="advanced"),
            ),
            self.adapters,
        )

        self.assertEqual(simple.configuration_checksum, advanced.configuration_checksum)

    def test_explicit_provider_content_limits_and_weights_are_resolved(self):
        weights = {
            key: criterion.weight
            for key, criterion in prepare_run(
                SubmittedRunConfiguration(request=self.request), self.adapters
            ).evaluation.criteria.items()
        }
        submitted = SubmittedRunConfiguration(
            request=self.request,
            search=SearchConfiguration(
                mode="advanced",
                provider_ids=["tavily"],
                content_types=["page_snippet"],
                source_policy=SourcePolicy(include_types=["web_article"]),
                limits=SearchLimits(
                    max_queries=4, max_results_per_query=5, max_sources=10
                ),
            ),
            evaluation=EvaluationSelection(weights=weights),
        )

        prepared = prepare_run(submitted, self.adapters)

        self.assertEqual([provider.provider_id for provider in prepared.search.providers], ["tavily"])
        self.assertEqual(prepared.search.content_types, ["page_snippet"])
        self.assertEqual(prepared.search.max_sources, 10)
        self.assertEqual(prepared.request.source_policy.include_types, ["web_article"])
        self.assertEqual(prepared.evaluation.preset, "custom")
        self.assertEqual(prepared.field_origins["evaluation.weights"], "explicit")

    def test_unavailable_choices_and_conflicting_policies_fail_preflight(self):
        choices = (
            SearchConfiguration(provider_ids=["openalex"]),
            SearchConfiguration(content_types=["readme"]),
            SearchConfiguration(
                provider_ids=["github"], content_types=["page_snippet"]
            ),
        )
        for search in choices:
            with self.subTest(search=search.model_dump(mode="json")):
                with self.assertRaises(ValueError):
                    prepare_run(
                        SubmittedRunConfiguration(request=self.request, search=search),
                        self.adapters,
                    )

        request = self.request.model_copy(update={
            "source_policy": SourcePolicy(include_types=["code_repository"])
        })
        with self.assertRaisesRegex(ValueError, "source policies conflict"):
            prepare_run(
                SubmittedRunConfiguration(
                    request=request,
                    search=SearchConfiguration(
                        source_policy=SourcePolicy(include_types=["web_article"])
                    ),
                ),
                self.adapters,
            )

    def test_content_choice_drops_incompatible_default_provider(self):
        prepared = prepare_run(
            SubmittedRunConfiguration(
                request=self.request,
                search=SearchConfiguration(content_types=["page_snippet"]),
            ),
            self.adapters,
        )

        self.assertEqual(
            [provider.provider_id for provider in prepared.search.providers], ["tavily"]
        )
        self.assertEqual(prepared.search.content_types, ["page_snippet"])

    def test_other_domain_requires_explicit_opt_in(self):
        request = InputRequest(domain="Urban ecology", time_limit_days=30)
        with self.assertRaisesRegex(ValueError, "unknown source domain"):
            prepare_run(SubmittedRunConfiguration(request=request), self.adapters)

        prepared = prepare_run(
            SubmittedRunConfiguration(
                request=request,
                search=SearchConfiguration(allow_other_domain=True),
            ),
            self.adapters,
        )
        self.assertEqual(prepared.search.domain, "Urban ecology")
        self.assertEqual(
            [provider.provider_id for provider in prepared.search.providers],
            ["github", "tavily"],
        )

    def test_prepared_snapshot_detects_mutated_effective_choices(self):
        prepared = prepare_run(
            SubmittedRunConfiguration(request=self.request), self.adapters
        )
        prepared.search.max_sources = 41

        with self.assertRaisesRegex(ValidationError, "checksum"):
            PreparedRun.model_validate(prepared.model_dump(mode="python"))

    def test_weight_total_is_validated_before_resolution(self):
        with self.assertRaisesRegex(ValidationError, "total 100"):
            EvaluationSelection(weights={"problem_value": 50})

    def test_uninterpreted_instructions_cannot_be_silently_ignored(self):
        submitted = SubmittedRunConfiguration(
            request=self.request,
            search=SearchConfiguration(custom_instructions="Avoid blogs"),
        )
        with self.assertRaisesRegex(ValueError, "require interpretation"):
            prepare_run(submitted, self.adapters)

    def test_field_origins_reference_real_fields_and_deductions_need_a_prompt(self):
        with self.assertRaisesRegex(ValidationError, "unknown field"):
            SubmittedRunConfiguration(
                request=self.request,
                field_origins={"search.unlisted": "explicit"},
            )
        with self.assertRaisesRegex(ValidationError, "original prompt"):
            SubmittedRunConfiguration(
                request=self.request,
                field_origins={"request.domain": "deduced"},
            )


if __name__ == "__main__":
    unittest.main()
