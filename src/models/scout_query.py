"""Bounded research queries used by Scout and Library."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveInt

from .common import ContractModel, Identifier, NonEmptyText


class SourceQuery(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    query_id: Identifier
    provider_id: Identifier
    text: NonEmptyText
    source_types: list[Identifier] = Field(min_length=1)
    content_types: list[Identifier] = Field(min_length=1)
    max_results: PositiveInt


class ScoutQuery(SourceQuery):
    """Source query planned for the Scout worker."""
