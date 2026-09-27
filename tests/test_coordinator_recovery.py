"""Coordinator handles explicit candidate-level Critic skips safely."""

import unittest
from datetime import datetime, timezone

from src.models import CandidateIdea, CriticResult, EvaluationResult
from src.orchestration.coordinator import OrchestrationError, Orchestrator


def candidate(candidate_id: str) -> CandidateIdea:
    return CandidateIdea(
        candidate_id=candidate_id,
        title=f"Project {candidate_id}",
        problem_statement="Students need a clearer way to compare public datasets.",
        target_users=["Students"],
        proposed_outcome="A small comparison tool.",
        why_it_matters="It reduces setup time.",
    )


def evaluation(candidate_id: str) -> EvaluationResult:
    return EvaluationResult.model_validate({
        "evaluation_id": f"eval:{candidate_id}",
        "candidate_id": candidate_id,
        "criteria": [{
            "criterion_id": "quality", "score": 4, "weight": 100,
            "weighted_score": 80, "rationale": "Supported by supplied evidence.",
        }],
        "hard_gates": [], "gate_passed": True, "total_score": 80,
        "evaluated_at": datetime.now(timezone.utc),
    })


class CoordinatorRecoveryTests(unittest.TestCase):
    def test_explicitly_skipped_candidate_is_omitted_from_ranking(self):
        result = Orchestrator._rank(
            [candidate("candidate-01"), candidate("candidate-02")],
            CriticResult(
                evaluations=[evaluation("candidate-02")],
                warnings=["Candidate candidate-01 was not scored because its Critic citation check failed."],
            ),
        )

        self.assertEqual([item.candidate_id for item in result], ["candidate-02"])

    def test_missing_candidate_without_skip_warning_still_fails(self):
        with self.assertRaisesRegex(OrchestrationError, "without explicit skip warnings"):
            Orchestrator._rank(
                [candidate("candidate-01"), candidate("candidate-02")],
                CriticResult(evaluations=[evaluation("candidate-02")]),
            )


if __name__ == "__main__":
    unittest.main()
