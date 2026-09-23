"""Shared types used by ScoutSpark data contracts."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


Identifier = Annotated[
    str,
    Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"),
]
NonEmptyText = Annotated[str, Field(min_length=1)]


class ContractModel(BaseModel):
    """Base class for versioned, strict contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class EvidenceStance(str, Enum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    MISSING = "missing"


class EvidenceReference(ContractModel):
    """Pointer from a claim to a captured source or source chunk."""

    source_id: Identifier
    chunk_id: Identifier | None = None
    stance: EvidenceStance = EvidenceStance.SUPPORTING
    note: NonEmptyText | None = None


class ClaimEvidence(ContractModel):
    """A material claim and the evidence receipts that support it."""

    claim: NonEmptyText
    references: list[EvidenceReference] = Field(min_length=1)
