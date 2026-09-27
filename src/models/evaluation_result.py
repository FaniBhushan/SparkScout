"""Evidence-backed scoring and hard-gate results for one candidate."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .candidate_idea import CandidateIdea
from .common import ContractModel, EvidenceReference, Identifier, NonEmptyText


Score = Annotated[float, Field(ge=0, le=5)]
Weight = Annotated[float, Field(ge=0, le=100)]
TotalScore = Annotated[float, Field(ge=0, le=100)]


class CriterionScore(ContractModel):
    criterion_id: Identifier
    score: Score
    weight: Weight
    weighted_score: TotalScore
    rationale: NonEmptyText
    evidence: list[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_weighted_score(self) -> "CriterionScore":
        expected = self.score / 5 * self.weight
        if abs(self.weighted_score - expected) > 0.01:
            raise ValueError(f"weighted_score must equal score / 5 * weight ({expected:.2f})")
        return self


class HardGateResult(ContractModel):
    gate_id: Identifier
    passed: bool
    rationale: NonEmptyText
    evidence: list[EvidenceReference] = Field(default_factory=list)


class EvaluationResult(ContractModel):
    """One candidate's criterion scores, hard-gate decisions, and evidence links."""

    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: Identifier
    candidate_id: Identifier
    criteria: list[CriterionScore] = Field(min_length=1)
    hard_gates: list[HardGateResult] = Field(default_factory=list)
    gate_passed: bool
    total_score: TotalScore
    rejection_reasons: list[NonEmptyText] = Field(default_factory=list)
    uncertainty: list[NonEmptyText] = Field(default_factory=list)
    revised_candidate: CandidateIdea | None = None
    evaluated_at: datetime

    @property
    def can_accept_evidence_risk(self) -> bool:
        """Only an isolated evidence gap is eligible for a user's risk decision."""

        gates = {gate.gate_id: gate for gate in self.hard_gates}
        required = {"user_constraints", "evaluation_method", "data_access",
                    "evidence_sufficiency", "time_scope"}
        return (
            not self.gate_passed
            and len(gates) == len(self.hard_gates)
            and required <= gates.keys()
            and {key for key, gate in gates.items() if not gate.passed} == {"evidence_sufficiency"}
        )

    @model_validator(mode="after")
    def validate_totals_and_gates(self) -> "EvaluationResult":
        if self.revised_candidate is not None and self.revised_candidate.origin == "synthetic":
            raise ValueError("synthetic exploration must not appear in evaluated results")
        total_weight = sum(item.weight for item in self.criteria)
        if abs(total_weight - 100) > 0.01:
            raise ValueError(f"criterion weights must total 100, got {total_weight:.2f}")

        expected_total = sum(item.weighted_score for item in self.criteria)
        if abs(self.total_score - expected_total) > 0.01:
            raise ValueError(f"total_score must equal weighted criterion scores ({expected_total:.2f})")

        expected_gate_status = all(gate.passed for gate in self.hard_gates)
        if self.gate_passed != expected_gate_status:
            raise ValueError("gate_passed must agree with all hard-gate results")
        if not self.gate_passed and not self.rejection_reasons:
            raise ValueError("a gate failure requires at least one rejection reason")
        return self
