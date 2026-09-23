"""Auditable output of one sequential or parallel coordinator run."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ContractModel, Identifier, NonEmptyText
from .critic_result import CriticResult
from .library_result import LibraryResult
from .scout_result import ScoutResult
from .source_record import SourceRecord


class RankedCandidate(ContractModel):
    candidate_id: Identifier
    evaluation_id: Identifier
    rank: int = Field(ge=1)
    total_score: float = Field(ge=0, le=100)
    gate_passed: bool


class OrchestrationResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    mode: Literal["sequential", "parallel"]
    status: Literal["completed", "insufficient_coverage"]
    scout: ScoutResult
    library: LibraryResult
    critic: CriticResult
    source_manifest: list[SourceRecord] = Field(default_factory=list)
    ranking: list[RankedCandidate] = Field(default_factory=list)
    finalist_candidate_ids: list[Identifier] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
    completed_at: datetime
