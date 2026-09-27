"""Review must preserve failed gates, caveats, budgets, and run identity."""

import asyncio
import json
import unittest
from dataclasses import replace

from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src.adapters import FrozenFixtureAdapter
from src.application import run_research
from src.evaluation.review import record_candidate_review
from src.models import InputRequest, OrchestrationResult
from test_application import FakeLLMClient


class GateClient(FakeLLMClient):
    """Supply controlled gate judgments through the real application pipeline."""

    def __init__(self, failed_gates):
        super().__init__()
        self.failed_gates = failed_gates

    async def complete(self, prompt, *, max_output_tokens):
        reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
        if "evidence-based candidate assessor" in prompt:
            payload = json.loads(reply.text)
            for gate_id in self.failed_gates:
                payload["hard_gates"][gate_id]["passed"] = False
                payload["hard_gates"][gate_id]["rationale"] = f"Unresolved {gate_id} requirement."
            payload["uncertainty"] = ["Development may take four to six weeks; reduce the MVP scope."]
            reply = replace(reply, text=json.dumps(payload))
        return reply


def run_with_gates(failed_gates):
    return asyncio.run(run_research(
        InputRequest(domain="AI engineering", time_limit_days=30,
                     desired_candidate_count=1, finalist_count=1),
        GateClient(failed_gates),
        {"frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")},
    ))


class GateReviewTests(unittest.TestCase):
    def test_evidence_risk_decision_preserves_assessment_and_partial_status(self):
        original = run_with_gates(["evidence_sufficiency"])
        reviewed = record_candidate_review(original, "candidate-01", "accepted_risk", acknowledged=True)
        self.assertEqual(reviewed.critic, original.critic)
        self.assertEqual(reviewed.ranking, original.ranking)
        self.assertEqual(reviewed.budget_usage, original.budget_usage)
        self.assertFalse(reviewed.critic.evaluations[0].gate_passed)
        self.assertEqual(reviewed.status, "insufficient_coverage")
        self.assertEqual(reviewed.finalist_candidate_ids, [])
        self.assertEqual(reviewed.final_proposals, [])
        self.assertEqual(original.review_decisions, [])
        exported = OrchestrationResult.model_validate_json(reviewed.model_dump_json())
        self.assertEqual(exported.review_decisions[0].decision, "accepted_risk")
        self.assertIn(original.critic.evaluations[0].rejection_reasons[0],
                      exported.review_decisions[0].caveats)

    def test_other_failed_gates_and_unacknowledged_acceptance_are_blocked(self):
        result = run_with_gates(["evidence_sufficiency"])
        with self.assertRaisesRegex(ValueError, "acknowledge"):
            record_candidate_review(result, "candidate-01", "accepted_risk")
        for gate in ("time_scope", "data_access", "user_constraints", "evaluation_method"):
            with self.subTest(gate=gate):
                blocked = run_with_gates(["evidence_sufficiency", gate])
                self.assertFalse(blocked.critic.evaluations[0].can_accept_evidence_risk)
                with self.assertRaisesRegex(ValueError, "not eligible"):
                    record_candidate_review(blocked, "candidate-01", "accepted_risk", acknowledged=True)

    def test_decline_replaces_current_choice_but_keeps_history(self):
        result = run_with_gates(["evidence_sufficiency"])
        result = record_candidate_review(result, "candidate-01", "accepted_risk", acknowledged=True)
        result = record_candidate_review(result, "candidate-01", "declined")
        self.assertEqual([item.decision for item in result.review_decisions], ["accepted_risk", "declined"])

    def test_review_cannot_be_reused_with_changed_run_or_assessment(self):
        reviewed = record_candidate_review(run_with_gates(["evidence_sufficiency"]),
                                           "candidate-01", "accepted_risk", acknowledged=True)
        for field, value in (("run_id", "other-run"), ("caveats", ["Everything is proven"]),
                             ("assessment_sha256", "0" * 64)):
            with self.subTest(field=field):
                data = reviewed.model_dump(mode="python")
                data["review_decisions"][0][field] = value
                with self.assertRaises(ValidationError):
                    OrchestrationResult.model_validate(data)
        data = reviewed.model_dump(mode="python")
        data["scout"]["candidates"][0]["proposed_outcome"] = "A different project"
        with self.assertRaisesRegex(ValidationError, "current candidate assessment"):
            OrchestrationResult.model_validate(data)

    def test_uncertain_timing_is_preserved_in_final_proposal(self):
        result = run_with_gates([])
        self.assertEqual(result.status, "completed")
        caveats = result.critic.evaluations[0].uncertainty
        self.assertTrue(any("not a delivery guarantee" in item for item in caveats))
        self.assertTrue(any("four to six weeks" in item for item in caveats))
        self.assertTrue(set(caveats) <= set(result.final_proposals[0].unknowns))


class GateReviewUITests(unittest.TestCase):
    @staticmethod
    def app(result):
        def show_result():
            import streamlit as st
            from src.ui.views import _result_view
            _result_view(st.session_state.result)
        app = AppTest.from_function(show_result)
        app.session_state.result = result
        return app.run(timeout=30)

    def test_explicit_selection_survives_reruns_and_keeps_gate_failed(self):
        result = run_with_gates(["evidence_sufficiency"])
        app = self.app(result)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.button[0].disabled)
        self.assertTrue(any("evidence_sufficiency" in item.value for item in app.warning))
        app.checkbox[0].check().run(timeout=30)
        app.button[0].click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("User accepted the risk" in item.value for item in app.info))
        saved = app.session_state.result
        self.assertEqual(saved.review_decisions[-1].decision, "accepted_risk")
        self.assertFalse(saved.critic.evaluations[0].gate_passed)
        self.assertEqual(saved.budget_usage, result.budget_usage)
        app.run(timeout=30)
        self.assertEqual(len(app.session_state.result.review_decisions), 1)
        app.button[1].click().run(timeout=30)
        self.assertEqual(app.session_state.result.review_decisions[-1].decision, "declined")
        self.assertEqual(len(app.get("download_button")), 1)

    def test_known_time_conflict_has_no_acceptance_control(self):
        app = self.app(run_with_gates(["time_scope"]))
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.button), 0)
        self.assertTrue(any("Resolve the failed requirements" in item.value for item in app.info))

    def test_new_run_requires_fresh_acknowledgement(self):
        app = self.app(run_with_gates(["evidence_sufficiency"]))
        app.checkbox[0].check().run(timeout=30)
        app.button[0].click().run(timeout=30)
        app.session_state.result = run_with_gates(["evidence_sufficiency"])
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(app.checkbox[0].value)
        self.assertTrue(app.button[0].disabled)
        self.assertEqual(app.session_state.result.review_decisions, [])


if __name__ == "__main__":
    unittest.main()
