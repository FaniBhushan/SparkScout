"""Score finalists remain visible independently of gate and drafting outcomes."""

import asyncio
import json
import unittest
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from src.adapters import FrozenFixtureAdapter
from src.application.service import run_research
from src.models import InputRequest, OrchestrationResult
from test_run_equivalence import FrozenModel


class ScoreSelectionTests(unittest.TestCase):
    def test_failed_gate_leader_is_visible_with_reason_and_others_are_compact(self):
        result = asyncio.run(run_research(
            InputRequest(domain="AI engineering", time_limit_days=30,
                         desired_candidate_count=3, finalist_count=2),
            FrozenModel(), {"frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")},
        ))
        result = OrchestrationResult.model_validate_json(result.model_dump_json())
        self.assertEqual(result.score_finalist_candidate_ids, ["candidate-02", "candidate-01"])

        def show():
            import streamlit as st
            from src.ui.scorecards import render_scorecards
            render_scorecards(st.session_state.result)

        app = AppTest.from_function(show)
        app.session_state["result"] = result
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("Access audit", app.expander[0].label)
        self.assertTrue(app.warning)
        self.assertTrue(any("Proposal sketch" in item.value for item in app.markdown))
        self.assertTrue(any("Target users:" in item.value for item in app.text))
        self.assertEqual(sum("Not a finalist:" in item.value for item in app.caption), 1)
        result.prepared_run = None
        result.requested_finalist_count = 1
        self.assertEqual(result.score_finalist_candidate_ids, ["candidate-02"])

    def test_all_failed_gates_still_have_score_selections(self):
        class FailedGates(FrozenModel):
            async def complete(self, prompt, *, max_output_tokens):
                reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
                if "evidence-based candidate assessor" in prompt:
                    payload = json.loads(reply.text)
                    payload["hard_gates"]["data_access"].update(
                        passed=False, rationale="Required access remains unresolved.")
                    return replace(reply, text=json.dumps(payload))
                return reply

        result = asyncio.run(run_research(
            InputRequest(domain="AI engineering", time_limit_days=30,
                         desired_candidate_count=3, finalist_count=2),
            FailedGates(), {"frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")},
        ))
        self.assertFalse(result.final_proposals)
        self.assertEqual(result.score_finalist_candidate_ids, ["candidate-02", "candidate-01"])
        self.assertTrue(all(not row.gate_passed for row in result.score_ranking))
