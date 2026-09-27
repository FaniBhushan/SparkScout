"""Shared source identity and deterministic merging of public search receipts."""

from hashlib import sha256
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from src.models.source_record import ExcerptReceipt, SourceExcerpt, SourceRecord


def canonical_source_url(url: str) -> str:
    """Remove known tracking and fragments, preserving meaningful query order.

    Do not collapse paths, sort query parameters, or remove arbitrary parameters:
    those transformations can change which document a URL identifies.
    """
    parsed = urlsplit(url)
    query = "&".join(part for part in parsed.query.split("&") if part and not (
        unquote_plus(part.split("=", 1)[0]).lower().startswith("utm_")
        or unquote_plus(part.split("=", 1)[0]).lower() in {"fbclid", "gclid"}
    ))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path or "/", query, ""))


def is_live_source(source: SourceRecord) -> bool:
    return source.provider in {"tavily", "github"}


def _identity(source: SourceRecord) -> tuple:
    if source.provider == "github" and source.provider_record_id:
        key = ("repository", source.provider_record_id)
    else:
        key = ("url", canonical_source_url(str(source.canonical_url))) if source.canonical_url else None
    return source.provider, source.source_type, key


def capture_excerpts(source: SourceRecord) -> SourceRecord:
    """Capture public snippets before a later receipt can replace their metadata."""
    if not is_live_source(source):
        return source
    excerpts = list(source.excerpts)
    for text in (source.abstract_or_snippet, source.full_text):
        if text:
            excerpts.append(SourceExcerpt(
                text=text, content_hash=sha256(text.encode()).hexdigest(),
                receipts=[ExcerptReceipt(query_id=source.query_id,
                                         captured_at=source.captured_at, url=source.canonical_url)],
            ))
    by_text = {}
    for excerpt in excerpts:
        by_text.setdefault(excerpt.text, []).extend(excerpt.receipts)
    normalized = []
    for text in sorted(by_text, key=lambda value: (sha256(value.encode()).hexdigest(), value)):
        receipts = {receipt.model_dump_json(): receipt for receipt in by_text[text]}
        normalized.append(SourceExcerpt(
            text=text, content_hash=sha256(text.encode()).hexdigest(),
            receipts=[receipts[key] for key in sorted(receipts)],
        ))
    return source.model_copy(update={"excerpts": normalized})


def merge_source_records(left: SourceRecord, right: SourceRecord) -> SourceRecord:
    """Merge compatible receipts without guessing when identities conflict.

    Live results may contribute multiple snippets for one canonical source;
    non-live fixture records must agree on their source identity and content hash.
    """
    if left.source_id != right.source_id:
        raise ValueError("conflicting records have different source IDs")
    if is_live_source(left) or is_live_source(right):
        if _identity(left) != _identity(right) or _identity(left)[2] is None:
            raise ValueError(f"conflicting records have source ID {left.source_id!r}")
    elif (left.provider, left.source_type, left.canonical_url, left.content_hash) != (
        right.provider, right.source_type, right.canonical_url, right.content_hash
    ):
        raise ValueError(f"conflicting records have source ID {left.source_id!r}")

    # A stable representative retains receipt metadata without depending on
    # branch completion order. Evidence is unioned independently below.
    key = lambda record: (record.query_id, record.model_dump_json(exclude={"excerpts"}))
    baseline = min((left, right), key=key)
    if not is_live_source(baseline):
        return baseline
    left, right = capture_excerpts(left), capture_excerpts(right)
    chunks = {}
    for chunk in [*left.evidence_chunks, *right.evidence_chunks]:
        if chunk.chunk_id in chunks and chunks[chunk.chunk_id] != chunk:
            raise ValueError(f"conflicting evidence chunk {chunk.chunk_id!r}")
        chunks[chunk.chunk_id] = chunk
    merged = baseline.model_copy(update={
        "excerpts": [*left.excerpts, *right.excerpts],
        "evidence_chunks": [chunks[key] for key in sorted(chunks)],
    })
    return capture_excerpts(merged)
