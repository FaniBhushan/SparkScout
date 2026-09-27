"""Quality review hides prior judgments and rejects incomplete dimensions."""

import json
import unittest
from pathlib import Path

from evals.analysis.quality import RUBRIC_PATH, review_payload, review_reports
from src.llm.client import ModelReply


class QualityEvalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.proposal = {"proposal_id": "p1", "candidate_id": "c1", "rank": 1,
            "total_score": 99, "criterion_scores": ["prior score"], "evidence_audit": {"passed": True},
            "title": "A prototype", "problem_statement": "A scoped problem"}
        self.record = {"case_id": "case1", "result": {
            "prepared_run": {"request": {"domain": "AI engineering"}},
            "library": {"chunks": [{"source_id": "s", "chunk_id": "c", "text": "Evidence."}]},
            "final_proposals": [self.proposal],
        }}

    def test_blind_payload_excludes_scores_mode_and_audit(self):
        payload = review_payload(self.record, self.proposal)
        self.assertEqual(set(payload), {"request", "proposal", "evidence"})
        self.assertEqual(set(payload["proposal"]), {"title", "problem_statement"})

    async def test_incomplete_review_is_recorded_as_an_error(self):
        class Client:
            async def complete(self, prompt, *, max_output_tokens):
                return ModelReply(text='{"dimensions":{},"issues":[]}', model="fake")
        rows = await review_reports([(Path("report.json"), {"mode": "parallel", "cases": [self.record]})],
                                    Client(), json.loads(RUBRIC_PATH.read_text()))
        self.assertIsNone(rows[0]["review"])
        self.assertIn("every rubric dimension", rows[0]["error"])

    async def test_resume_reuses_completed_review_without_another_model_call(self):
        class NoCallClient:
            async def complete(self, prompt, *, max_output_tokens):
                raise AssertionError("completed review should be reused")

        dimensions = {name: {"score": 4, "reason": "Clear and useful."}
                      for name in json.loads(RUBRIC_PATH.read_text())["dimensions"]}
        prior = {"review": {"dimensions": dimensions, "issues": []}, "prompt_sha256": "prompt-hash"}
        completed = {("report.json", "case1", "p1"): prior}
        rows = await review_reports(
            [(Path("report.json"), {"mode": "sequential", "cases": [self.record]})],
            NoCallClient(), json.loads(RUBRIC_PATH.read_text()), completed,
        )
        self.assertEqual(rows[0]["review"], prior["review"])
        self.assertTrue(rows[0]["reused"])
        self.assertEqual(rows[0]["prompt_sha256"], "prompt-hash")
