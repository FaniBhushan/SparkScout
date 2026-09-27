"""User decisions kept separate from the original automated assessment."""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field

from .candidate_idea import CandidateIdea
from .common import ContractModel, Identifier, NonEmptyText
from .evaluation_result import EvaluationResult


def assessment_fingerprint(candidate: CandidateIdea, evaluation: EvaluationResult) -> str:
    """Bind a decision to the exact idea and assessment the user reviewed."""

    payload = {"candidate": candidate.model_dump(mode="json"),
               "evaluation": evaluation.model_dump(mode="json")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class CandidateReviewDecision(ContractModel):
    run_id: Identifier
    candidate_id: Identifier
    evaluation_id: Identifier
    assessment_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["accepted_risk", "declined"]
    caveats: list[NonEmptyText] = Field(min_length=1)
    decided_at: datetime
