"""Common interface for research source adapters."""

from __future__ import annotations

from typing import Protocol

from src.models.scout_query import SourceQuery
from src.models.source_record import SourceRecord


class SourceAdapter(Protocol):
    """Search one approved provider and return normalized source receipts."""

    async def search(self, query: SourceQuery) -> list[SourceRecord]: ...
