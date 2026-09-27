"""Shared source-age policy for both independent research branches."""

from __future__ import annotations

from datetime import datetime

from src.models import ResolvedSearchConfiguration, SourceRecord


def same_source_content(left: SourceRecord, right: SourceRecord) -> bool:
    """Repeated queries change receipt metadata, not the source's identity.

    Live providers use the shared merge policy at call sites. This strict check
    protects fixtures and memory-only uploads. Compare full text and passages
    explicitly because serialization omits them.
    """
    excluded = {"query_id", "captured_at"}
    return (left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)
            and left.full_text == right.full_text
            and left.evidence_chunks == right.evidence_chunks)


def source_is_within_age_limit(
    source: SourceRecord, search: ResolvedSearchConfiguration
) -> bool:
    """Keep undated records, but reject dated records older than the policy."""

    if search.language and source.language != search.language:
        return False

    max_age = search.max_age_days_by_type.get(source.source_type)
    if source.published_at is None:
        return not search.require_published_date
    if max_age is None and search.published_from is None and search.published_to is None:
        return True
    published = (
        source.published_at.date()
        if isinstance(source.published_at, datetime)
        else source.published_at
    )
    if search.published_from and published < search.published_from:
        return False
    if search.published_to and published > search.published_to:
        return False
    if max_age is None or search.as_of_date is None:
        return True
    return (search.as_of_date - published).days <= max_age
