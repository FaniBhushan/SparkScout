"""Normalized capstone request extracted from a user prompt."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel, NonEmptyText
from .source_configuration import SourcePolicy


class SkillLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class InputRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    domain: NonEmptyText
    time_limit_days: PositiveInt
    interests: list[NonEmptyText] = Field(default_factory=list)
    skill_level: SkillLevel = SkillLevel.INTERMEDIATE
    team_size: PositiveInt = 1
    available_resources: list[NonEmptyText] = Field(default_factory=list)
    excluded_topics: list[NonEmptyText] = Field(default_factory=list)
    data_constraints: list[NonEmptyText] = Field(default_factory=list)
    desired_candidate_count: PositiveInt = 12
    finalist_count: PositiveInt = 3
    source_policy: SourcePolicy = Field(default_factory=SourcePolicy)

    @model_validator(mode="after")
    def validate_candidate_counts(self) -> "InputRequest":
        if self.finalist_count > self.desired_candidate_count:
            raise ValueError("finalist_count cannot exceed desired_candidate_count")
        return self
