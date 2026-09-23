"""Output contract for the Scout worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .candidate_idea import CandidateIdea
from .common import ContractModel, NonEmptyText
from .source_record import SourceRecord


class ScoutResult(ContractModel):
    """Candidate ideas and source records discovered by the Scout."""

    schema_version: Literal["1.0"] = "1.0"
    candidates: list[CandidateIdea] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
