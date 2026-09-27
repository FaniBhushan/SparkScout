"""Bounded passage selection for data dependencies, without inventing support."""

import re

from src.models.source_record import SourceChunk


def dependency_passages(dependencies: list[str], chunks: list[SourceChunk],
                        *, excluded: set[str] | None = None) -> list[SourceChunk]:
    """Select whole, matching passages; retrieval relevance is not verification.

    One best passage per dependency is considered before filling another slot.
    Limits bound additional drafting context to four passages / 6,000 characters.
    Never clip a passage: doing so could remove a permission restriction.
    """
    excluded = set(excluded or ())
    selected = []
    remaining = 6000
    stop = {"the", "and", "for", "with", "from", "data", "dataset", "datasets", "public"}
    for dependency in dependencies:
        terms = set(re.findall(r"\w+", dependency.lower())) - stop
        ranked = sorted(chunks, key=lambda chunk: (
            -len(terms & set(re.findall(r"\w+", chunk.text.lower()))), chunk.chunk_id))
        for chunk in ranked:
            if (chunk.chunk_id in excluded or len(chunk.text) > min(2000, remaining)
                    or not terms.intersection(re.findall(r"\w+", chunk.text.lower()))):
                continue
            selected.append(chunk)
            excluded.add(chunk.chunk_id)
            remaining -= len(chunk.text)
            break
        if len(selected) >= 4:
            break
    return selected
