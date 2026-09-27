"""Final proposal selected from a gate-passing candidate."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveInt

from .common import ClaimEvidence, ContractModel, Identifier, NonEmptyText
from .evaluation_result import CriterionScore, TotalScore
from .proposal_audit import ProposalAudit


class AlternativeApproach(ContractModel):
    name: NonEmptyText
    description: NonEmptyText
    tradeoff: NonEmptyText


class ProposalEvaluationPlan(ContractModel):
    method: NonEmptyText
    objective_metrics: list[NonEmptyText] = Field(min_length=1)
    qualitative_metrics: list[NonEmptyText] = Field(default_factory=list)
    success_criteria: list[NonEmptyText] = Field(min_length=1)


class FinalProposal(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    proposal_id: Identifier
    candidate_id: Identifier
    rank: PositiveInt
    title: NonEmptyText
    problem_statement: NonEmptyText
    target_users: list[NonEmptyText] = Field(min_length=1)
    proposed_artifact: NonEmptyText
    why_it_matters: NonEmptyText
    gap_or_differentiation: NonEmptyText
    scoped_mvp: list[NonEmptyText] = Field(min_length=1)
    non_goals: list[NonEmptyText] = Field(min_length=1)
    required_data: list[NonEmptyText] = Field(default_factory=list)
    required_tools: list[NonEmptyText] = Field(default_factory=list)
    access_assumptions: list[NonEmptyText] = Field(default_factory=list)
    technical_approach: NonEmptyText
    alternatives: list[AlternativeApproach] = Field(min_length=1)
    criterion_scores: list[CriterionScore] = Field(min_length=1)
    total_score: TotalScore
    risks: list[NonEmptyText] = Field(min_length=1)
    unknowns: list[NonEmptyText] = Field(default_factory=list)
    first_kill_test: NonEmptyText
    evaluation_plan: ProposalEvaluationPlan
    citations: list[ClaimEvidence] = Field(min_length=1)
    evidence_audit: ProposalAudit | None = None
