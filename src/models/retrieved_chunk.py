"""A source chunk returned by the run's retrieval index."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .common import ContractModel
from .source_record import SourceChunk


RelevanceScore = Annotated[float, Field(ge=0)]


class RetrievedChunk(ContractModel):
    chunk: SourceChunk
    score: RelevanceScore
