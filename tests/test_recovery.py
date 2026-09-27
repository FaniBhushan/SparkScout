"""Focused tests for safe recovery from deterministic model-output mistakes."""

import json
import unittest

from src.models import ResolvedSearchConfiguration, ScoutQuery
from src.prompts import parse_model_output, repair_known_candidate_field
from src.workers.query_limits import bound_query_plan


class RecoveryTests(unittest.TestCase):
    def test_query_plan_clamps_result_count_and_trims_excess_queries(self):
        search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[{"provider_id": "fixture", "source_types": ["dataset"], "content_types": ["text"]}],
            content_types=["text"], max_queries=1, max_results_per_query=3, max_sources=3,
        )
        queries = [
            ScoutQuery(query_id=f"q-{index}", provider_id="fixture", text="dataset",
                       source_types=["dataset"], content_types=["text"], max_results=8)
            for index in (1, 2)
        ]

        bounded, warnings = bound_query_plan(queries, search)

        self.assertEqual(len(bounded), 1)
        self.assertEqual(bounded[0].query_id, "q-1")
        self.assertEqual(bounded[0].max_results, 3)
        self.assertEqual(len(warnings), 2)

    def test_query_plan_drops_unavailable_types_and_keeps_allowed_work(self):
        search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[{"provider_id": "fixture", "source_types": ["dataset"], "content_types": ["text"]}],
            content_types=["text"], max_queries=2, max_results_per_query=3, max_sources=3,
        )
        query = ScoutQuery(
            query_id="q-1", provider_id="fixture", text="dataset",
            source_types=["not_allowed", "dataset"],
            content_types=["unsupported", "text"], max_results=2,
        )

        bounded, warnings = bound_query_plan([query], search)

        self.assertEqual(bounded[0].source_types, ["dataset"])
        self.assertEqual(bounded[0].content_types, ["text"])
        self.assertTrue(any("provider-approved types" in warning for warning in warnings))

    def test_query_plan_broadens_with_approved_types_for_minimum_coverage(self):
        search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[{"provider_id": "fixture", "source_types": ["dataset", "repository", "paper"], "content_types": ["text"]}],
            content_types=["text"], max_queries=2, max_results_per_query=3,
            max_sources=3, minimum_source_count=3,
        )
        query = ScoutQuery(
            query_id="q-1", provider_id="fixture", text="dataset",
            source_types=["dataset"], content_types=["text"], max_results=3,
        )

        bounded, warnings = bound_query_plan([query], search)

        self.assertEqual(set(bounded[0].source_types), {"dataset", "repository", "paper"})
        self.assertTrue(any("minimum source coverage" in warning for warning in warnings))

    def test_known_candidate_field_typo_is_repaired_and_other_errors_remain_errors(self):
        candidate = {
            "candidate_id": "candidate-01", "title": "Example project",
            "problem_statement": "A specific unmet need.", "target_users": ["students"],
            "proposed_outcome": "A small tool.", "why_it.matters": "It saves time.",
        }
        raw = json.dumps([candidate])
        repaired = repair_known_candidate_field(raw)

        self.assertIsNotNone(repaired)
        parsed = parse_model_output("scout_candidate_generator", raw)
        self.assertEqual(parsed[0].why_it_matters, "It saves time.")
        self.assertIsNone(repair_known_candidate_field(json.dumps([{"title": "incomplete"}])))


if __name__ == "__main__":
    unittest.main()
