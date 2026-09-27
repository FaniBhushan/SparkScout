"""Record an explicit risk decision without repeating research or model calls."""

from datetime import datetime, timezone
from typing import Literal

from src.guardrails import check_privacy
from src.models import OrchestrationResult
from src.models.candidate_review import CandidateReviewDecision, assessment_fingerprint


def record_candidate_review(
    result: OrchestrationResult,
    candidate_id: str,
    decision: Literal["accepted_risk", "declined"],
    *,
    acknowledged: bool = False,
) -> OrchestrationResult:
    """Keep an auditable decision history; acceptance selects an idea for the user.

    It does not promote the idea to the system's finalists, change gate results,
    or generate a proposal. The result's original completion status stays intact.
    """

    result = OrchestrationResult.model_validate(result.model_dump(mode="python"))
    check_privacy(result)
    if decision == "accepted_risk" and acknowledged is not True:
        raise ValueError("acknowledge the evidence caveats before accepting this idea")
    candidate = next((item for item in result.scout.candidates
                      if item.candidate_id == candidate_id), None)
    evaluation = next((item for item in result.critic.evaluations
                       if item.candidate_id == candidate_id), None)
    if candidate is None or evaluation is None or not evaluation.can_accept_evidence_risk:
        raise ValueError("this candidate is not eligible for evidence-risk acceptance")
    review = CandidateReviewDecision(
        run_id=result.run_id, candidate_id=candidate_id, evaluation_id=evaluation.evaluation_id,
        assessment_sha256=assessment_fingerprint(candidate, evaluation), decision=decision,
        caveats=list(dict.fromkeys([*evaluation.rejection_reasons, *evaluation.uncertainty])),
        decided_at=datetime.now(timezone.utc),
    )
    data = result.model_dump(mode="python")
    data["review_decisions"] = [*result.review_decisions, review]
    return OrchestrationResult.model_validate(data)
