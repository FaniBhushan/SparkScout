"""Validated search presets and operator hard limits."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel, Identifier


class SearchPreset(ContractModel):
    max_queries: PositiveInt
    max_results_per_query: PositiveInt
    max_sources: PositiveInt
    minimum_source_count: PositiveInt = 3
    recency_days: PositiveInt


class SearchLimits(ContractModel):
    max_queries: PositiveInt
    max_results_per_query: PositiveInt
    max_sources: PositiveInt


class SearchDefaults(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    content_types: list[Identifier] = Field(min_length=1)
    presets: dict[Identifier, SearchPreset] = Field(min_length=1)
    hard_limits: SearchLimits

    @model_validator(mode="after")
    def ensure_presets_fit_hard_limits(self) -> "SearchDefaults":
        for name, preset in self.presets.items():
            if preset.minimum_source_count > preset.max_sources:
                raise ValueError(f"preset {name!r} minimum_source_count exceeds max_sources")
            for field in ("max_queries", "max_results_per_query", "max_sources"):
                if getattr(preset, field) > getattr(self.hard_limits, field):
                    raise ValueError(f"preset {name!r} exceeds hard limit {field}")
        return self
