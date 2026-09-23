"""Small retriever contract and deterministic lexical implementation."""

from __future__ import annotations

import re
from typing import Protocol

from src.models import RetrievedChunk
from src.models.source_record import SourceChunk


class Retriever(Protocol):
    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]: ...


class InMemoryRetriever:
    """Simple run-scoped retrieval; replaceable with a hybrid index later."""

    def __init__(self, chunks: list[SourceChunk]) -> None:
        self.chunks = list(chunks)

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        terms = set(re.findall(r"[\w]+", query.casefold()))
        ranked = []
        for chunk in self.chunks:
            overlap = len(terms & set(re.findall(r"[\w]+", chunk.text.casefold())))
            if overlap:
                ranked.append(RetrievedChunk(chunk=chunk, score=float(overlap)))
        return sorted(ranked, key=lambda hit: (-hit.score, hit.chunk.chunk_id))[:top_k]
