"""Reviewable, partial configuration extracted from a natural-language request."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, PositiveInt

from .common import ContractModel, Identifier, NonEmptyText
from .input_request import SkillLevel
from .search_defaults import SearchLimits
from .source_configuration import EvidenceTier, SourcePolicy


class RequestSuggestions(ContractModel):
    """Only values actually stated or strongly implied by the user belong here."""

    domain: NonEmptyText | None = None
    time_limit_days: PositiveInt | None = None
    interests: list[NonEmptyText] | None = None
    skill_level: SkillLevel | None = None
    team_size: PositiveInt | None = None
    available_resources: list[NonEmptyText] | None = None
    excluded_topics: list[NonEmptyText] | None = None
    data_constraints: list[NonEmptyText] | None = None
    desired_candidate_count: PositiveInt | None = None
    finalist_count: PositiveInt | None = None


class SearchSuggestions(ContractModel):
    preset: NonEmptyText | None = None
    allow_other_domain: bool | None = None
    source_policy: SourcePolicy | None = None
    provider_ids: list[Identifier] | None = None
    content_types: list[Identifier] | None = None
    limits: SearchLimits | None = None
    recency_days: PositiveInt | None = None
    published_from: date | None = None
    published_to: date | None = None
    evidence_tiers: list[EvidenceTier] | None = None
    fallback_policy: Literal["skip_unavailable", "fail_if_unavailable"] | None = None


class EvaluationSuggestions(ContractModel):
    rubric_preset: NonEmptyText | None = None
    weights: dict[Identifier, int] | None = None
    retrieval_top_k: PositiveInt | None = None


class InterpretationIssue(ContractModel):
    kind: Literal["ambiguous", "unsupported", "conflict"]
    message: NonEmptyText
    path: str | None = None


class PromptSuggestions(ContractModel):
    """Model output: suggestions are not permissions or runnable configuration."""

    request: RequestSuggestions = Field(default_factory=RequestSuggestions)
    search: SearchSuggestions = Field(default_factory=SearchSuggestions)
    evaluation: EvaluationSuggestions = Field(default_factory=EvaluationSuggestions)
    uncertain_paths: list[str] = Field(default_factory=list)
    issues: list[InterpretationIssue] = Field(default_factory=list)


class PromptInterpretationDraft(ContractModel):
    """Persist the original words and the draft until a person reviews them."""

    original_prompt: NonEmptyText
    suggestions: PromptSuggestions
    issues: list[InterpretationIssue] = Field(default_factory=list)


class InterpretationReview(ContractModel):
    """Explicit acceptance or correction; an empty review accepts no suggestions."""

    accepted_paths: set[str] = Field(default_factory=set)
    overrides: dict[str, object] = Field(default_factory=dict)
    acknowledged_issues: set[int] = Field(default_factory=set)
