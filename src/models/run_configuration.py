"""Submitted choices and the immutable effective configuration for a run."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from .common import ContractModel, Identifier, NonEmptyText
from .evaluation_configuration import EvaluationConfiguration, Percentage
from .input_request import InputRequest
from .prompt_interpretation import PromptInterpretationDraft
from .resolved_search_configuration import ResolvedSearchConfiguration
from .run_budget import BudgetSelection, RunBudgetLimits
from .search_defaults import SearchLimits
from .source_configuration import EvidenceTier, SourcePolicy


ConfigurationMode = Literal["simple", "advanced"]
ValueOrigin = Literal["explicit", "deduced", "preset", "default"]


class UploadedSource(ContractModel):
    """Auditable receipt for user-supplied content; file bytes stay outside JSON."""

    filename: NonEmptyText
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: PositiveInt
    pdf_pages: NonNegativeInt = 0
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
    rights_confirmed: Literal[True]

    @model_validator(mode="after")
    def validate_filename(self) -> "UploadedSource":
        if self.filename in (".", "..") or "/" in self.filename or "\\" in self.filename:
            raise ValueError("upload filename must not contain a path")
        return self


class SearchConfiguration(ContractModel):
    """User-facing search choices; empty selections inherit approved defaults."""

    schema_version: Literal["1.0"] = "1.0"
    mode: ConfigurationMode = "simple"
    preset: NonEmptyText = "balanced"
    allow_other_domain: bool = False
    source_policy: SourcePolicy = Field(default_factory=SourcePolicy)
    provider_ids: list[Identifier] = Field(default_factory=list)
    content_types: list[Identifier] = Field(default_factory=list)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
    uploads: list[UploadedSource] = Field(default_factory=list)
    limits: SearchLimits | None = None
    recency_days: PositiveInt | None = None
    published_from: date | None = None
    published_to: date | None = None
    evidence_tiers: list[EvidenceTier] = Field(default_factory=list)
    fallback_policy: Literal["skip_unavailable", "fail_if_unavailable"] = "skip_unavailable"
    custom_instructions: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_selections(self) -> "SearchConfiguration":
        if len(self.provider_ids) != len(set(self.provider_ids)):
            raise ValueError("provider_ids must be unique")
        if len(self.content_types) != len(set(self.content_types)):
            raise ValueError("content_types must be unique")
        if len(self.evidence_tiers) != len(set(self.evidence_tiers)):
            raise ValueError("evidence_tiers must be unique")
        if len({item.filename for item in self.uploads}) != len(self.uploads):
            raise ValueError("upload filenames must be unique")
        if self.published_from and self.published_to and self.published_from > self.published_to:
            raise ValueError("published_from cannot be after published_to")
        return self


class EvaluationSelection(ContractModel):
    """Choose a rubric preset or provide one complete percentage allocation."""

    schema_version: Literal["1.0"] = "1.0"
    rubric_preset: NonEmptyText | None = None
    weights: dict[Identifier, Percentage] | None = None
    retrieval_top_k: PositiveInt | None = None
    custom_instructions: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_weight_total(self) -> "EvaluationSelection":
        if self.weights is not None and sum(self.weights.values()) != 100:
            raise ValueError("evaluation weights must total 100")
        return self


class SubmittedRunConfiguration(ContractModel):
    """Keep the user's request and choices distinct from resolved permissions."""

    schema_version: Literal["1.0"] = "1.0"
    request: InputRequest
    search: SearchConfiguration = Field(default_factory=SearchConfiguration)
    evaluation: EvaluationSelection = Field(default_factory=EvaluationSelection)
    budgets: BudgetSelection = Field(default_factory=BudgetSelection)
    original_prompt: NonEmptyText | None = None
    interpretation_draft: PromptInterpretationDraft | None = None
    field_origins: dict[str, ValueOrigin] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_field_origins(self) -> "SubmittedRunConfiguration":
        if self.interpretation_draft is not None:
            if self.original_prompt != self.interpretation_draft.original_prompt:
                raise ValueError("interpretation draft must match the original prompt")
        sections = {
            "request": type(self.request).model_fields,
            "search": type(self.search).model_fields,
            "evaluation": type(self.evaluation).model_fields,
            "budgets": type(self.budgets).model_fields,
        }
        for path, origin in self.field_origins.items():
            section, separator, remainder = path.partition(".")
            field = remainder.split(".", 1)[0] if separator else ""
            if section not in sections or field not in sections[section]:
                raise ValueError(f"field origin references an unknown field: {path!r}")
            if origin == "deduced" and self.original_prompt is None:
                raise ValueError("deduced field origins require the original prompt")
        return self


def effective_configuration_checksum(
    request: InputRequest,
    search: ResolvedSearchConfiguration,
    evaluation: EvaluationConfiguration,
    budgets: RunBudgetLimits,
) -> str:
    """Hash only effective behavior, so equivalent UI modes get the same ID."""

    payload = {
        "request": request.model_dump(mode="json"),
        "search": search.model_dump(mode="json"),
        "evaluation": evaluation.model_dump(mode="json"),
        "budgets": budgets.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PreparedRun(ContractModel):
    """Preflight output checked again immediately before any research calls."""

    schema_version: Literal["1.0"] = "1.0"
    submitted: SubmittedRunConfiguration
    request: InputRequest
    search: ResolvedSearchConfiguration
    evaluation: EvaluationConfiguration
    budgets: RunBudgetLimits
    field_origins: dict[str, ValueOrigin]
    configuration_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    warnings: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_checksum(self) -> "PreparedRun":
        expected = effective_configuration_checksum(
            self.request, self.search, self.evaluation, self.budgets
        )
        if self.configuration_checksum != expected:
            raise ValueError("prepared configuration checksum does not match effective values")
        return self
