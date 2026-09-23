"""Candidate idea produced by the Scout worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel, EvidenceReference, Identifier, NonEmptyText


class CandidateIdea(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: Identifier
    title: NonEmptyText
    problem_statement: NonEmptyText
    target_users: list[NonEmptyText] = Field(min_length=1)
    proposed_outcome: NonEmptyText
    why_it_matters: NonEmptyText
    domain_tags: list[NonEmptyText] = Field(default_factory=list)
    required_data: list[NonEmptyText] = Field(default_factory=list)
    required_tools: list[NonEmptyText] = Field(default_factory=list)
    access_assumptions: list[NonEmptyText] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
