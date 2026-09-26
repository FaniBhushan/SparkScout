"""The approved search choices and limits for one run."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel, Identifier, NonEmptyText


class ResolvedProvider(ContractModel):
    """A provider selected from the operator's source registry."""

    provider_id: Identifier
    source_types: list[Identifier] = Field(min_length=1)
    content_types: list[Identifier] = Field(min_length=1)


class ResolvedSearchConfiguration(ContractModel):
    """Search permissions; global content types are the providers' union."""

    schema_version: Literal["1.0"] = "1.0"
    domain: NonEmptyText
    providers: list[ResolvedProvider] = Field(min_length=1)
    content_types: list[Identifier] = Field(min_length=1)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
    upload_sha256: dict[str, str] = Field(default_factory=dict)
    max_queries: PositiveInt
    max_results_per_query: PositiveInt
    max_sources: PositiveInt
    minimum_source_count: PositiveInt = 1
    max_records_by_type: dict[Identifier, PositiveInt] = Field(default_factory=dict)
    required_source_types: list[Identifier] = Field(default_factory=list)
    max_age_days_by_type: dict[Identifier, PositiveInt] = Field(default_factory=dict)
    as_of_date: date | None = None
    published_from: date | None = None
    published_to: date | None = None
    require_published_date: bool = False

    @model_validator(mode="after")
    def validate_resolved_choices(self) -> "ResolvedSearchConfiguration":
        if self.minimum_source_count > self.max_sources:
            raise ValueError("minimum_source_count cannot exceed max_sources")
        provider_ids = [provider.provider_id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider IDs must be unique")
        available_content_types = {
            content_type
            for provider in self.providers
            for content_type in provider.content_types
        }
        if set(self.content_types) != available_content_types:
            raise ValueError("content_types must match the selected providers' content types")
        available_source_types = {
            source_type for provider in self.providers for source_type in provider.source_types
        }
        unknown_caps = set(self.max_records_by_type) - available_source_types
        if unknown_caps:
            raise ValueError(f"record caps reference unavailable source types: {sorted(unknown_caps)}")
        unknown_ages = set(self.max_age_days_by_type) - available_source_types
        if unknown_ages:
            raise ValueError(f"recency limits reference unavailable source types: {sorted(unknown_ages)}")
        if not set(self.required_source_types).issubset(available_source_types):
            raise ValueError("required source types must be available from selected providers")
        if self.max_age_days_by_type and self.as_of_date is None:
            raise ValueError("as_of_date is required with source recency limits")
        if any(cap > self.max_sources for cap in self.max_records_by_type.values()):
            raise ValueError("per-type record caps cannot exceed max_sources")
        if self.published_from and self.published_to and self.published_from > self.published_to:
            raise ValueError("published_from cannot be after published_to")
        return self
