"""Normalized capstone request extracted from a user prompt."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel
from .source_configuration import SourcePolicy


# Structured fields should be concise. Long free-form prompts use warnings instead.
InterestText = Annotated[str, Field(min_length=1, max_length=200)]
DomainText = Annotated[str, Field(min_length=1, max_length=200)]
RequestDetail = Annotated[str, Field(min_length=1, max_length=1000)]
InterestList = Annotated[list[InterestText], Field(max_length=20)]
DetailList = Annotated[list[RequestDetail], Field(max_length=20)]


class SkillLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class InputRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    domain: DomainText
    time_limit_days: PositiveInt
    interests: InterestList = Field(default_factory=list)
    skill_level: SkillLevel = SkillLevel.INTERMEDIATE
    team_size: PositiveInt = 1
    available_resources: DetailList = Field(default_factory=list)
    excluded_topics: DetailList = Field(default_factory=list)
    data_constraints: DetailList = Field(default_factory=list)
    desired_candidate_count: PositiveInt = 5
    finalist_count: PositiveInt = 2
    source_policy: SourcePolicy = Field(default_factory=SourcePolicy)

    @model_validator(mode="after")
    def validate_candidate_counts(self) -> "InputRequest":
        if self.finalist_count > self.desired_candidate_count:
            raise ValueError("finalist_count cannot exceed desired_candidate_count")
        return self
