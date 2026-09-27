"""Normalized source receipts and retrievable chunks."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import Field, HttpUrl, NonNegativeInt, PositiveInt, model_validator

from .common import ContractModel, Identifier, NonEmptyText


class RetrievalStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class SourceChunk(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    chunk_id: Identifier
    source_id: Identifier
    ordinal: NonNegativeInt
    text: NonEmptyText
    text_redacted: bool = False
    content_hash: NonEmptyText
    token_count: PositiveInt | None = None
    start_offset: NonNegativeInt | None = None
    end_offset: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> "SourceChunk":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together")
        if self.start_offset is not None and self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class ExcerptReceipt(ContractModel):
    """The search receipt that supplied an excerpt, retained for audit."""

    query_id: Identifier
    captured_at: datetime
    url: HttpUrl | None = None


class SourceExcerpt(ContractModel):
    """Distinct public search text; additional receipts do not duplicate its text."""

    text: NonEmptyText
    content_hash: NonEmptyText
    receipts: list[ExcerptReceipt] = Field(default_factory=list)


class SourceRecord(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: Identifier
    provider: Identifier
    source_type: Identifier
    title: NonEmptyText
    authors_or_owners: list[NonEmptyText] = Field(default_factory=list)
    published_at: date | datetime | None = None
    captured_at: datetime
    canonical_url: HttpUrl | None = None
    query_id: Identifier
    domain_tags: list[NonEmptyText] = Field(default_factory=list)
    abstract_or_snippet: NonEmptyText | None = None
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
    # Retained only in memory until Library builds chunks; never serialized into manifests.
    full_text: str | None = Field(default=None, exclude=True, repr=False)
    # Adapter passages travel to Library without inflating Scout's source prompt.
    evidence_chunks: list[SourceChunk] = Field(default_factory=list, exclude=True, repr=False)
    # Public live-search excerpts survive checkpoint serialization. Upload text
    # continues to use the separate, memory-only full_text/evidence_chunks fields.
    excerpts: list[SourceExcerpt] = Field(default_factory=list, repr=False)
    license_access_note: NonEmptyText | None = None
    content_hash: NonEmptyText
    retrieval_status: RetrievalStatus
    provider_record_id: NonEmptyText | None = None
    metadata_conflicts: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_sources(self) -> "SourceRecord":
        if any(chunk.source_id != self.source_id for chunk in self.evidence_chunks):
            raise ValueError("evidence chunk must belong to its source record")
        return self
