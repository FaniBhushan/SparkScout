"""Build Library evidence from source text and adapter-supplied passages."""

from hashlib import sha256

from src.models.source_record import RetrievalStatus, SourceChunk, SourceRecord


def build_source_chunks(sources: list[SourceRecord]) -> list[SourceChunk]:
    """Keep captured passage IDs and retain summaries that add different context.

    Adapters may provide excerpts without full documents. These excerpts stay
    separate from the source summary so retrieval can select either passage.
    The run index applies size limits and splits long passages afterwards.
    """

    chunks: list[SourceChunk] = []
    seen_ids: set[str] = set()
    for source in sources:
        if source.retrieval_status not in (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL):
            continue
        for captured in source.evidence_chunks:
            if captured.source_id != source.source_id:
                raise ValueError("evidence chunk must belong to its source record")
            if captured.chunk_id in seen_ids:
                raise ValueError("evidence chunk IDs must be unique")
            if captured.text_redacted:
                raise ValueError("cannot index redacted evidence")
            seen_ids.add(captured.chunk_id)
            chunks.append(captured.model_copy(deep=True, update={
                "content_hash": sha256(captured.text.encode("utf-8")).hexdigest(),
                "token_count": max(1, len(captured.text) // 4),
            }))

        text = source.full_text or source.abstract_or_snippet
        for ordinal, excerpt in enumerate(source.excerpts):
            if any(excerpt.text == chunk.text for chunk in source.evidence_chunks):
                continue
            digest = sha256(excerpt.text.encode("utf-8")).hexdigest()
            chunk_id = f"{source.source_id}-excerpt-{digest}"
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            chunks.append(SourceChunk(
                chunk_id=chunk_id, source_id=source.source_id,
                ordinal=max((chunk.ordinal for chunk in source.evidence_chunks), default=-1) + ordinal + 1,
                text=excerpt.text, content_hash=digest,
                token_count=max(1, len(excerpt.text) // 4),
            ))
        if source.excerpts and any(text == excerpt.text for excerpt in source.excerpts):
            continue
        if not text or any(text == chunk.text for chunk in source.evidence_chunks):
            continue
        # A captured passage may already use c0; never replace its citation ID.
        chunk_id = f"{source.source_id}-c0"
        while chunk_id in seen_ids:
            chunk_id += "-text"
        seen_ids.add(chunk_id)
        chunks.append(SourceChunk(
            chunk_id=chunk_id,
            source_id=source.source_id,
            ordinal=max((chunk.ordinal for chunk in source.evidence_chunks), default=-1) + 1,
            text=text,
            content_hash=sha256(text.encode("utf-8")).hexdigest(),
            token_count=max(1, len(text) // 4),
            start_offset=0,
            end_offset=len(text),
        ))
    return chunks
