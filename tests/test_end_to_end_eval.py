"""The evaluator must expose pipeline failures and never manufacture quality scores."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from evals.end_to_end.cases import DEFAULT_CASES, load_cases
from evals.end_to_end.checks import check_result
from evals.end_to_end.reports import write_report
from evals.end_to_end.runner import run_cases
from src.budgets import BudgetExceeded
from src.demo import OfflineDemoClient
from src.models import OrchestrationResult


class EndToEndEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_accepts_partial_count_and_exports_review(self):
        cases = load_cases([DEFAULT_CASES[0]])
        records = await run_cases(cases, OfflineDemoClient())
        record = records[0]
        self.assertEqual(record["outcome"], "passed")
        self.assertTrue(record["checks"]["proposal_count"])
        self.assertEqual(record["result"]["status"], "partial")
        self.assertEqual(record["proposal_counts"], {"requested": 3, "returned": 1, "target_met": False})
        self.assertTrue(record["checks"]["citation_integrity"])
        result = OrchestrationResult.model_validate(record["result"])
        result.final_proposals[0].citations[0].references[0].source_id = "invented"
        self.assertFalse(check_result(cases[0][0], result)["citation_integrity"])
        result.critic.evaluations[0].criteria[0].__dict__["weighted_score"] = 99
        self.assertFalse(check_result(cases[0][0], result)["scoring_consistency"])
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report"
            report = {"execution": "offline_demo", "mode": "sequential", "cases": records}
            write_report(destination, report)
            self.assertEqual(len(json.loads((destination / "results.json").read_text())["cases"]), 1)
            self.assertIn("proposal_id", (destination / "human_scores.csv").read_text())
            with self.assertRaises(FileExistsError):
                write_report(destination, report)

    async def test_failure_is_recorded_and_later_cases_are_skipped(self):
        with patch("evals.end_to_end.runner.run_research", AsyncMock(side_effect=BudgetExceeded("cap"))) as run:
            records = await run_cases(load_cases(list(DEFAULT_CASES)), OfflineDemoClient())
        self.assertEqual([record["outcome"] for record in records], ["error", "skipped", "skipped"])
        self.assertEqual(run.await_count, 1)

    def test_rejects_unknown_duplicate_and_interpretation_cases(self):
        for ids in (["unknown"], [DEFAULT_CASES[0]] * 2, ["missing-time-limit-01"]):
            with self.assertRaises(ValueError):
                load_cases(ids)
