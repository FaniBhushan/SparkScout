"""Output contract for the Scout worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .candidate_idea import CandidateIdea
from .common import ContractModel, NonEmptyText
from .source_record import SourceRecord


class ScoutResult(ContractModel):
    """Candidate ideas and source records discovered by the Scout."""

    schema_version: Literal["1.0"] = "1.0"
    candidates: list[CandidateIdea] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def exclude_internal_ideas(self) -> "ScoutResult":
        if any(candidate.origin == "synthetic" for candidate in self.candidates):
            raise ValueError("synthetic exploration must not appear in Scout results")
        return self
