"""Model-authored proposal content, excluding deterministic ranking fields."""

from __future__ import annotations

from pydantic import Field

from .common import ClaimEvidence, ContractModel, NonEmptyText
from .final_proposal import AlternativeApproach, ProposalEvaluationPlan


class ProposalDraft(ContractModel):
    """LLM-authored fields later combined with code-owned identity and scores."""

    gap_or_differentiation: NonEmptyText
    scoped_mvp: list[NonEmptyText] = Field(min_length=1)
    non_goals: list[NonEmptyText] = Field(min_length=1)
    required_data: list[NonEmptyText] = Field(default_factory=list)
    required_tools: list[NonEmptyText] = Field(default_factory=list)
    access_assumptions: list[NonEmptyText] = Field(default_factory=list)
    technical_approach: NonEmptyText
    alternatives: list[AlternativeApproach] = Field(min_length=1)
    risks: list[NonEmptyText] = Field(min_length=1)
    unknowns: list[NonEmptyText] = Field(default_factory=list)
    first_kill_test: NonEmptyText
    evaluation_plan: ProposalEvaluationPlan
    citations: list[ClaimEvidence] = Field(min_length=1)
