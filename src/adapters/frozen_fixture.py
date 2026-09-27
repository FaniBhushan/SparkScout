"""Offline adapter for a checked-in frozen source fixture set."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.models.scout_query import SourceQuery
from src.models.source_record import SourceChunk, SourceRecord


DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "evals" / "frozen_sources"


class FrozenFixtureAdapter:
    """Return deterministic fixture records without making network requests.

    The fixture set is selected by the caller for the current evaluation case.
    Results are filtered by requested source type and retain stable fixture IDs.
    """

    def __init__(
        self,
        fixture_set: str,
        *,
        provider_id: str = "frozen_fixture",
        fixture_root: Path | str = DEFAULT_FIXTURE_ROOT,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", fixture_set):
            raise ValueError("fixture_set must be a simple fixture directory name")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", provider_id):
            raise ValueError("provider_id must be a valid source provider identifier")

        self.fixture_set = fixture_set
        self.provider_id = provider_id
        self.fixture_dir = Path(fixture_root).resolve() / fixture_set
        if self.fixture_dir.parent != Path(fixture_root).resolve():
            raise ValueError("fixture_set must be a direct child of fixture_root")

        source_path = self.fixture_dir / "sources.json"
        if not source_path.is_file():
            raise FileNotFoundError(f"fixture source file not found: {source_path}")
        raw_sources = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(raw_sources, list):
            raise ValueError("fixture sources.json must contain a JSON list")
        self._sources = [SourceRecord.model_validate(item) for item in raw_sources]
        by_id = {source.source_id: source for source in self._sources}
        if len(by_id) != len(self._sources):
            raise ValueError("fixture source IDs must be unique")
        chunks_path = self.fixture_dir / "chunks.json"
        if chunks_path.is_file():
            raw_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
            if not isinstance(raw_chunks, list):
                raise ValueError("fixture chunks.json must contain a JSON list")
            seen = set()
            for item in raw_chunks:
                chunk = SourceChunk.model_validate(item)
                if chunk.source_id not in by_id:
                    raise ValueError("fixture chunk references an unknown source")
                if chunk.chunk_id in seen:
                    raise ValueError("fixture chunk IDs must be unique")
                if chunk.text_redacted:
                    raise ValueError("fixture evidence must contain readable text")
                seen.add(chunk.chunk_id)
                by_id[chunk.source_id].evidence_chunks.append(chunk)

    async def search(self, query: SourceQuery) -> list[SourceRecord]:
        """Select requested fixture types and bind records to this search query."""

        if query.provider_id != self.provider_id:
            raise ValueError(
                f"query provider {query.provider_id!r} does not match adapter "
                f"{self.provider_id!r}"
            )

        selected = [
            source
            for source in self._sources
            if source.source_type in query.source_types
        ][: query.max_results]
        records = []
        for source in selected:
            # Prepared synthetic passages are snippets, not permission to fetch full text.
            include_text = bool({"abstract", "snippet"} & set(query.content_types))
            records.append(source.model_copy(deep=True, update={
                "provider": self.provider_id,
                "query_id": query.query_id,
                "abstract_or_snippet": source.abstract_or_snippet if include_text else None,
                "evidence_chunks": [chunk.model_copy(deep=True) for chunk in source.evidence_chunks]
                if include_text else [],
                "full_text": None,
            }))
        return records
