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


class SourceRecord(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: Identifier
    provider: Identifier
    source_type: Identifier
    title: NonEmptyText
    authors_or_owners: list[NonEmptyText] = Field(default_factory=list)
    published_at: date | datetime | None = None
    captured_at: datetime
    canonical_url: HttpUrl
    query_id: Identifier
    domain_tags: list[NonEmptyText] = Field(default_factory=list)
    abstract_or_snippet: NonEmptyText | None = None
    license_access_note: NonEmptyText | None = None
    content_hash: NonEmptyText
    retrieval_status: RetrievalStatus
    provider_record_id: NonEmptyText | None = None
    metadata_conflicts: dict[str, list[str]] = Field(default_factory=dict)


class SourceChunk(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    chunk_id: Identifier
    source_id: Identifier
    ordinal: NonNegativeInt
    text: NonEmptyText
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
