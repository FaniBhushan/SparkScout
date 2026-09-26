"""Deterministic local TF-IDF vector and lexical retrieval over run chunks."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from hashlib import sha256

from src.models import RetrievedChunk
from src.models.source_record import SourceChunk

from .configuration import RetrievalIndexConfiguration


def _terms(text: str) -> list[str]:
    return re.findall(r"[\w]+", text.casefold())


def _bounded_chunks(
    chunks: list[SourceChunk], settings: RetrievalIndexConfiguration
) -> list[SourceChunk]:
    """Apply the configured window and overlap while preserving source IDs."""

    if sum(len(chunk.text) for chunk in chunks) > settings.max_corpus_chars:
        raise ValueError("Library corpus exceeds max_corpus_chars")
    normalized: list[SourceChunk] = []
    for chunk in chunks:
        text = chunk.text
        if len(text) <= settings.chunk_size_chars:
            normalized.append(chunk.model_copy(deep=True))
            continue
        start = 0
        part = 0
        while start < len(text):
            end = min(start + settings.chunk_size_chars, len(text))
            window = text[start:end]
            offset = chunk.start_offset or 0
            normalized.append(SourceChunk(
                chunk_id=f"{chunk.chunk_id}-p{part}",
                source_id=chunk.source_id,
                ordinal=chunk.ordinal * settings.max_chunks + part,
                text=window,
                content_hash=sha256(window.encode("utf-8")).hexdigest(),
                token_count=max(1, len(window) // 4),
                start_offset=offset + start,
                end_offset=offset + end,
            ))
            if len(normalized) > settings.max_chunks:
                raise ValueError("retrieval index exceeds max_chunks")
            if end == len(text):
                break
            start = end - settings.chunk_overlap_chars
            part += 1
    if len(normalized) > settings.max_chunks:
        raise ValueError("retrieval index exceeds max_chunks")
    if len({chunk.chunk_id for chunk in normalized}) != len(normalized):
        raise ValueError("retrieval index contains duplicate chunk IDs")
    return normalized


class HybridInMemoryRetriever:
    """Rank by local TF-IDF cosine plus exact query-term overlap.

    This local vector representation is deterministic and incurs no embedding
    service cost. It is not a semantic sentence-embedding model.
    """

    def __init__(
        self, chunks: list[SourceChunk], settings: RetrievalIndexConfiguration
    ) -> None:
        self.settings = settings
        self.chunks = _bounded_chunks(chunks, settings)
        term_counts = [Counter(_terms(chunk.text)) for chunk in self.chunks]
        # Smoothed IDF keeps rare terms useful without dividing by zero in a
        # one-document corpus; the same vocabulary is used for every query.
        document_frequency = Counter(
            term for counts in term_counts for term in counts
        )
        count = len(self.chunks)
        self.idf = {
            term: math.log((count + 1) / (frequency + 1)) + 1
            for term, frequency in document_frequency.items()
        }
        self.vectors = [
            {term: frequency * self.idf[term] for term, frequency in counts.items()}
            for counts in term_counts
        ]
        self.norms = [math.sqrt(sum(value * value for value in vector.values()))
                      for vector in self.vectors]
        # Bound a deterministic serialized footprint. Python object overhead is
        # larger, so the result records this as an estimate rather than heap use.
        self.index_bytes = len(json.dumps(
            {
                "chunks": [
                    (chunk.chunk_id, chunk.source_id, chunk.text)
                    for chunk in self.chunks
                ],
                "vectors": self.vectors,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"))
        if self.index_bytes > settings.max_index_bytes:
            raise ValueError("retrieval index exceeds max_index_bytes")

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        counts = Counter(_terms(query))
        if not counts:
            return []
        query_vector = {
            term: frequency * self.idf[term]
            for term, frequency in counts.items() if term in self.idf
        }
        query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
        if not query_norm:
            return []
        query_terms = set(counts)
        hits = []
        for chunk, vector, norm in zip(self.chunks, self.vectors, self.norms):
            overlap = len(query_terms & vector.keys())
            if not overlap:
                continue
            cosine = sum(query_vector.get(term, 0) * value
                         for term, value in vector.items()) / (query_norm * norm)
            lexical = overlap / len(query_terms)
            # Both components are in [0, 1]; the IDF term gives rare matches
            # more weight while exact overlap prevents zero-evidence hits.
            hits.append(RetrievedChunk(chunk=chunk, score=0.6 * cosine + 0.4 * lexical))
        return sorted(hits, key=lambda hit: (-hit.score, hit.chunk.chunk_id))[:top_k]
