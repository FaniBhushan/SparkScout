"""Verify gold/scorer wiring offline; these tests do not measure a real model."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from evals.claim_support import (
    Prediction, assessment_label, collect_predictions, load_cases, main, score_predictions,
)
from src.models import CandidateAssessment
from src.budgets import BudgetExceeded


def assessment(case, label):
    stance = {"supported": "supporting", "unsupported": "missing", "contradictory": "contradicting"}[label]
    ref = {"source_id": case.id, "chunk_id": f"{case.id}-c0", "stance": stance}
    return CandidateAssessment.model_validate({
        "criteria": {"claim_support": {"score": 5 if label == "supported" else 0,
                                      "rationale": "Synthetic judgment", "evidence": [ref]}},
        "hard_gates": {"supported_claim": {"passed": label == "supported",
                                          "rationale": "Synthetic judgment", "evidence": [ref]}},
    })


class ClaimSupportTests(unittest.IsolatedAsyncioTestCase):
    def test_offline_cli_scores_saved_predictions_without_model_calls(self):
        dataset = load_cases()
        predictions = [{"id": case.id, "label": "unsupported"} for case in dataset.cases]
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.json"
            path.write_text(json.dumps(predictions))
            with (patch("sys.argv", ["claim_support", "--predictions", str(path)]),
                  patch("src.llm.client.OpenAITextClient") as client,
                  redirect_stdout(output)):
                self.assertEqual(main(), 0)
                client.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual(report["metrics"]["count"], 9)
        self.assertAlmostEqual(report["metrics"]["accuracy"], 1 / 3)
        self.assertIsNone(report["model"])

    def test_gold_has_three_labels_and_adversarial_examples(self):
        dataset = load_cases()
        self.assertEqual(len(dataset.cases), 9)
        self.assertEqual({case.expected for case in dataset.cases},
                         {"supported", "unsupported", "contradictory"})
        self.assertTrue(any("Ignore" in case.evidence for case in dataset.cases))

    def test_held_out_dataset_uses_distinct_missing_and_contradictory_examples(self):
        held_out = load_cases(Path(__file__).parents[1] / "evals" / "guardrails" / "claim_support_held_out.json")
        development_ids = {case.id for case in load_cases().cases}
        self.assertEqual(len(held_out.cases), 6)
        self.assertTrue({case.id for case in held_out.cases}.isdisjoint(development_ids))
        self.assertEqual({case.expected for case in held_out.cases}, {"unsupported", "contradictory"})

    def test_metrics_penalize_false_support_and_invalid_outputs(self):
        dataset = load_cases()
        predictions = [Prediction(id=case.id, label="supported") for case in dataset.cases]
        metrics = score_predictions(dataset, predictions)
        self.assertAlmostEqual(metrics["accuracy"], 1 / 3)
        self.assertEqual(metrics["false_support_rate"], 1)
        predictions[0].label = "invalid"
        self.assertEqual(score_predictions(dataset, predictions)["confusion"]["supported"]["invalid"], 1)
        with self.assertRaises(ValueError):
            score_predictions(dataset, predictions[:-1])
        with self.assertRaises(ValueError):
            score_predictions(dataset, [*predictions[:-1], predictions[0]])

    def test_unknown_citation_and_gate_inconsistency_are_invalid(self):
        case = load_cases().cases[0]
        output = assessment(case, "supported")
        output.criteria["claim_support"].evidence[0].source_id = "invented"
        self.assertEqual(assessment_label(output, case), "invalid")
        output = assessment(case, "unsupported")
        output.hard_gates["supported_claim"].passed = True
        self.assertEqual(assessment_label(output, case), "invalid")

    async def test_runner_uses_existing_judge_without_exposing_gold_labels(self):
        dataset = load_cases()
        by_id = {case.id: case for case in dataset.cases}
        calls = []

        class FakeJudge:
            async def assess(self, request, candidate, evidence, rubric):
                calls.append(candidate.candidate_id)
                self_test.assertNotIn("expected", candidate.model_dump())
                self_test.assertEqual(evidence[0].chunk.text, by_id[candidate.candidate_id].evidence)
                # Deliberately fixed, imperfect prediction: never report test scores as model quality.
                return assessment(by_id[candidate.candidate_id], "unsupported")

        self_test = self
        predictions = await collect_predictions(dataset, FakeJudge())
        self.assertEqual(len(calls), 9)
        self.assertAlmostEqual(score_predictions(dataset, predictions)["accuracy"], 1 / 3)


class PaidEvaluationBudgetTests(unittest.TestCase):
    def test_paid_run_requires_valid_explicit_budget_and_rates(self):
        for options in ([], ["--max-cost-usd", "nan", "--input-rate", "0.15", "--output-rate", "0.6"]):
            with patch("sys.argv", ["eval", "--model", "gpt-4o-mini", *options]), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    main()

    def test_insufficient_budget_blocks_first_model_call_and_closes_client(self):
        argv = ["eval", "--model", "gpt-4o-mini", "--max-cost-usd", "0.00000001",
                "--input-rate", "0.15", "--output-rate", "0.6"]
        with (patch("sys.argv", argv), patch("src.environment.load_local_environment"),
              patch("src.llm.client.OpenAITextClient") as factory):
            factory.return_value.complete = AsyncMock()
            factory.return_value.sdk_client.close = AsyncMock()
            with self.assertRaises(BudgetExceeded):
                main()
            factory.return_value.complete.assert_not_awaited()
            factory.return_value.sdk_client.close.assert_awaited_once()
            self.assertEqual(factory.call_args.kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
