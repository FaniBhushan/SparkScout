"""Verify gold/scorer wiring offline; these tests do not measure a real model."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from evals.claim_support import (
    Prediction, assessment_label, collect_predictions, load_cases, main, score_predictions,
)
from src.models import CandidateAssessment


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


if __name__ == "__main__":
    unittest.main()
