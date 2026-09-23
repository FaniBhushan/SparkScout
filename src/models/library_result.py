"""Evidence landscape collected independently by the Library worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel, NonEmptyText
from .source_record import SourceChunk, SourceRecord


class LibraryResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    sources: list[SourceRecord] = Field(default_factory=list)
    chunks: list[SourceChunk] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
