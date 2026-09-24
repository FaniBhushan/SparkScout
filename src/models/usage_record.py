"""Token, provider-call, cache, and cost accounting for a task."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt

from .common import ContractModel, Identifier, NonEmptyText


NonNegativeCost = Annotated[float, Field(ge=0)]


class UsageRecord(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    models: list[NonEmptyText] = Field(default_factory=list)
    provider_calls: dict[Identifier, NonNegativeInt] = Field(default_factory=dict)
    model_calls: NonNegativeInt = 0
    search_calls: NonNegativeInt = 0
    prompt_tokens: NonNegativeInt = 0
    completion_tokens: NonNegativeInt = 0
    token_usage_available: bool = True
    embedding_tokens: NonNegativeInt = 0
    estimated_cost_usd: NonNegativeCost | None = None
    cache_hits: NonNegativeInt = 0
    sources_captured: NonNegativeInt = 0
