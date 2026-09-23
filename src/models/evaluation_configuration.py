"""Resolved criterion weights and retrieval limits for the Critic."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel, Identifier, NonEmptyText


Percentage = Annotated[int, Field(ge=0, le=100)]


class CriterionDefinition(ContractModel):
    label: NonEmptyText
    weight: Percentage
    retrieval_focus: NonEmptyText


class EvaluationConfiguration(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    preset: Identifier
    criteria: dict[Identifier, CriterionDefinition] = Field(min_length=1)
    hard_gates: dict[Identifier, NonEmptyText] = Field(min_length=1)
    retrieval_top_k: PositiveInt = 2
    max_context_chunks: PositiveInt = 12
    max_context_tokens: PositiveInt = 4000

    @model_validator(mode="after")
    def validate_weights(self) -> "EvaluationConfiguration":
        if sum(criterion.weight for criterion in self.criteria.values()) != 100:
            raise ValueError("criterion weights must total 100")
        return self
