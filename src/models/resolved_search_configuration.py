"""The approved search choices and limits for one run."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel, Identifier, NonEmptyText


class ResolvedProvider(ContractModel):
    """A provider selected from the operator's source registry."""

    provider_id: Identifier
    source_types: list[Identifier] = Field(min_length=1)


class ResolvedSearchConfiguration(ContractModel):
    """The validated search plan supplied to research workers."""

    schema_version: Literal["1.0"] = "1.0"
    domain: NonEmptyText
    providers: list[ResolvedProvider] = Field(min_length=1)
    content_types: list[Identifier] = Field(min_length=1)
    max_queries: PositiveInt
    max_results_per_query: PositiveInt
    max_sources: PositiveInt
    minimum_source_count: PositiveInt = 1

    @model_validator(mode="after")
    def validate_minimum_coverage(self) -> "ResolvedSearchConfiguration":
        if self.minimum_source_count > self.max_sources:
            raise ValueError("minimum_source_count cannot exceed max_sources")
        return self
