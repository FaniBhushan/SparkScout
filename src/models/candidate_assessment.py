"""Raw Critic judgments before deterministic scoring."""

from __future__ import annotations

from pydantic import Field

from .candidate_idea import CandidateIdea
from .common import ContractModel, EvidenceReference, Identifier, NonEmptyText
from .evaluation_result import Score


class CriterionJudgment(ContractModel):
    score: Score
    rationale: NonEmptyText
    evidence: list[EvidenceReference] = Field(default_factory=list)


class GateJudgment(ContractModel):
    passed: bool
    rationale: NonEmptyText
    evidence: list[EvidenceReference] = Field(default_factory=list)


class CandidateAssessment(ContractModel):
    criteria: dict[Identifier, CriterionJudgment]
    hard_gates: dict[Identifier, GateJudgment]
    uncertainty: list[NonEmptyText] = Field(default_factory=list)
    revised_candidate: CandidateIdea | None = None
