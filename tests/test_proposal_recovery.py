"""Recovery retains paid work and never promotes a failed gate or duplicate idea."""

import json
import tempfile
import unittest
from dataclasses import replace

from src.adapters import FrozenFixtureAdapter
from src.application.service import run_research, run_prepared_research
from src.models import InputRequest, SubmittedRunConfiguration
from src.application.preflight import prepare_run
from test_application import FakeLLMClient, prompt_json
from test_proposal_verification import AuditClient


class ReplacementClient(FakeLLMClient):
    model = "test-replacement"

    async def complete(self, prompt, *, max_output_tokens):
        reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
        data = json.loads(reply.text)
        if "idea-discovery worker" in prompt:
            feedback = prompt_json(prompt, "Batch instructions:\n").get("recovery_feedback")
            if feedback:
                assert feedback["previous_ideas"]
                data[0].update(title="Source permission inspection",
                               problem_statement="Students need to inspect documented data permissions.",
                               proposed_outcome="A permission report for existing datasets")
        if "evidence-based candidate assessor" in prompt:
            candidate = prompt_json(prompt, "Candidate:\n")
            if not candidate["candidate_id"].startswith("recovery-"):
                data["hard_gates"]["data_access"].update(passed=False, rationale="Data access is not established.")
        return replace(reply, text=json.dumps(data))


class ProposalRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_task_inputs_skip_writing_and_preserve_evidence(self):
        class MissingInputsClient(FakeLLMClient):
            async def complete(self, prompt, *, max_output_tokens):
                reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
                if "idea-discovery worker" in prompt:
                    candidates = json.loads(reply.text)
                    for candidate in candidates:
                        candidate["required_data"] = ["labeled training data"]
                    return replace(reply, text=json.dumps(candidates))
                if "independently verify factual support" in prompt:
                    data = json.loads(reply.text)
                    for item in data["checks"]:
                        if item["check_id"] == "narrative:data_task_fit":
                            item.update(label="unsupported", rationale="Essential labels are absent.", evidence_quotes=[])
                    return replace(reply, text=json.dumps(data))
                return reply

        client = MissingInputsClient()
        result = await run_research(self.request, client, self.adapters)
        self.assertFalse(result.final_proposals)
        self.assertTrue(result.library.chunks)
        self.assertNotIn(4000, client.calls)
        self.assertIn("essential input precheck failed", result.proposal_failures["candidate-01"])

    async def test_critic_stage_stop_keeps_first_assessment_for_finalization(self):
        from src.runtime.budgets import StageAllowanceExceeded

        class LimitedClient(AuditClient):
            async def complete(self, prompt, *, max_output_tokens):
                if "evidence-based candidate assessor" in prompt:
                    candidate = prompt_json(prompt, "Candidate:\n")
                    if candidate["candidate_id"] == "candidate-02":
                        raise StageAllowanceExceeded("retaining finalization allowance")
                return await super().complete(prompt, max_output_tokens=max_output_tokens)

        request = self.request.model_copy(update={"desired_candidate_count": 2})
        client = LimitedClient(always_fail_id="unused")
        result = await run_research(request, client, self.adapters)
        self.assertEqual(result.finalist_candidate_ids, ["candidate-01"])
        self.assertEqual(len(result.critic.evaluations), 1)
        self.assertTrue(any("stage allowance" in warning for warning in result.critic.warnings))

    def setUp(self):
        self.adapters = {"frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")}
        self.request = InputRequest(domain="AI engineering", time_limit_days=30,
                                    desired_candidate_count=1, finalist_count=1)

    async def test_failed_top_proposal_backfills_from_remaining_passing_candidates(self):
        request = self.request.model_copy(update={"desired_candidate_count": 2})
        client = AuditClient(always_fail_id="candidate-01")
        result = await run_research(request, client, self.adapters)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.finalist_candidate_ids, ["candidate-02"])
        self.assertEqual(result.final_proposals[0].rank, 2)
        self.assertFalse(result.recovery_history)
        self.assertEqual(client.audits, {"candidate-01": 2, "candidate-02": 1})

    async def test_replacements_pass_critic_and_resume_reuses_paid_work(self):
        for mode in ("sequential", "parallel"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                prepared = prepare_run(SubmittedRunConfiguration(request=self.request), self.adapters)
                client = ReplacementClient()
                result = await run_prepared_research(prepared, client, self.adapters,
                                                    mode=mode, checkpoint_dir=directory)
                self.assertEqual(result.finalist_candidate_ids, ["recovery-01-1"])
                self.assertEqual(result.recovery_history[0].outcome, "completed")
                self.assertFalse(result.recovery_history[0].previous_evaluations[0].gate_passed)
                self.assertLessEqual(result.budget_usage.provider_calls["frozen_fixture"], 3)
                resumed_client = ReplacementClient()
                resumed = await run_prepared_research(prepared, resumed_client, self.adapters,
                    mode=mode, checkpoint_dir=directory, resume=True)
                self.assertFalse(resumed_client.calls)
                self.assertEqual(resumed.final_proposals, result.final_proposals)
                self.assertEqual(resumed.budget_usage.model_tokens, result.budget_usage.model_tokens)

    async def test_recovery_does_not_repeat_an_unchanged_failed_idea(self):
        class FailedClient(FakeLLMClient):
            async def complete(self, prompt, *, max_output_tokens):
                reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
                if "evidence-based candidate assessor" in prompt:
                    data = json.loads(reply.text)
                    data["hard_gates"]["data_access"].update(passed=False, rationale="Missing access.")
                    return replace(reply, text=json.dumps(data))
                return reply

        client = FailedClient()
        result = await run_research(self.request, client, self.adapters)
        self.assertFalse(result.final_proposals)
        self.assertEqual(result.recovery_history[0].outcome, "exhausted")
        self.assertEqual(result.scout.candidates[0].candidate_id, "candidate-01")
        self.assertEqual(len(result.critic.evaluations), 1)
        self.assertFalse(result.recovery_history[0].replacement_candidate_ids)
