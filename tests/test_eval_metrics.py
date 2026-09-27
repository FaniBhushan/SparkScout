"""Quantitative report metrics preserve missing-output distinctions."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.analysis.metrics import summarize, summarize_quality


class MetricsTests(unittest.TestCase):
    def test_recovery_counts_prior_gate_failures_without_double_counting(self):
        initial = {"evaluation_id": "initial", "hard_gates": [{"passed": False}]}
        recovered = {"evaluation_id": "replacement", "hard_gates": [{"passed": True}]}
        result = {"critic": {"evaluations": [recovered]},
                  "recovery_history": [{"previous_evaluations": [initial, recovered]}]}
        metrics = summarize({"cases": [{"result": result}]})
        self.assertEqual(metrics["hard_gates"], {"passed": 1, "failed": 1, "not_evaluated": False})

    def test_reports_yield_coverage_citations_gates_and_cost(self):
        report = {
            "mode": "sequential", "execution": "paid_model", "model": "test",
            "fixture_kind": "synthetic", "max_cost_usd": 0.05,
            "suite_budget_usage": {"model_tokens": 100, "estimated_cost_usd": 0.01},
            "cases": [{
                "case_id": "case-a", "outcome": "partial", "duration_seconds": 2.0,
                "proposal_counts": {"requested": 3, "returned": 1, "target_met": False},
                "checks": {"citation_integrity": True},
                "result": {
                    "source_manifest": [{"retrieval_status": "success", "source_type": "web"}],
                    "prepared_run": {"search": {"required_source_types": ["web", "github"]}},
                    "critic": {"evaluations": [{"hard_gates": [
                        {"passed": True}, {"passed": False},
                    ]}]},
                },
            }, {
                "case_id": "case-b", "outcome": "failed", "duration_seconds": 4.0,
                "proposal_counts": {"requested": 2, "returned": 0, "target_met": False},
                "checks": {"citation_integrity": None}, "result": None,
            }],
        }
        metrics = summarize(report)
        self.assertEqual(metrics["proposal_yield"]["returned"], 1)
        self.assertEqual(metrics["proposal_yield"]["requested"], 5)
        self.assertEqual(metrics["source_coverage"]["required_source_types_covered"], 1)
        self.assertEqual(metrics["citation_integrity"]["cases_not_evaluated"], 1)
        self.assertEqual(metrics["hard_gates"], {"passed": 1, "failed": 1, "not_evaluated": False})
        self.assertEqual(metrics["usage"]["estimated_cost_usd"], 0.01)

    def test_quality_review_deduplicates_resumed_rows_and_compares_human_scores(self):
        review = {"dimensions": {"usefulness": {"score": 4, "reason": "Reason."}}, "issues": []}
        earlier = {"reviewer": "model_review", "model": "gpt-4o-mini", "reviews": [{
            "report": "r.json", "case_id": "c", "run_id": "run", "proposal_id": "p",
            "mode": "sequential",
            "review": review, "prompt_sha256": "hash",
        }], "budget_usage": {"model_tokens": 10, "estimated_cost_usd": 0.01}}
        later = {**earlier, "reviews": earlier["reviews"],
                 "budget_usage": {"model_tokens": 5, "estimated_cost_usd": 0.005}}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scores.csv"
            path.write_text("case_id,run_id,proposal_id,usefulness\nc,run,p,3\n", encoding="utf-8")
            metrics = summarize_quality(
                [(Path("first.json"), earlier), (Path("resume.json"), later)], [path]
            )
        self.assertEqual(metrics["reviewed_count"], 1)
        self.assertEqual(metrics["dimensions_by_mode"]["sequential"]["usefulness"]["n"], 1)
        self.assertEqual(metrics["budget_usage_across_reports"]["estimated_cost_usd"], 0.015)
        agreement = metrics["human_agreement"]
        self.assertEqual(agreement["matched_dimension_scores"], 1)
        self.assertEqual(agreement["by_dimension"]["usefulness"]["exact_agreement"], 0.0)
        self.assertEqual(agreement["by_dimension"]["usefulness"]["disagreements"][0]["human"], 3)


if __name__ == "__main__":
    unittest.main()
