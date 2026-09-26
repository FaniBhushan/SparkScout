"""Library worker: collect an independent, compact source landscape."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from contextlib import nullcontext
from hashlib import sha256
from typing import Protocol

from src.adapters.base import SourceAdapter
from src.models import InputRequest, LibraryResult, ResolvedSearchConfiguration, SourceQuery
from src.models.source_record import RetrievalStatus, SourceChunk, SourceRecord
from src.observability import RunTracer
from src.workers.source_filter import source_is_within_age_limit
from src.workers.upload_query import include_upload_query


class LibraryQueryPlanner(Protocol):
    """Plan broad source queries independently of Scout's candidates."""

    async def plan(
        self, request: InputRequest, search: ResolvedSearchConfiguration
    ) -> list[SourceQuery]: ...


class LibraryWorker:
    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter],
        query_planner: LibraryQueryPlanner,
        tracer: RunTracer | None = None,
    ) -> None:
        self.adapters = adapters
        self.query_planner = query_planner
        self.tracer = tracer

    async def run(
        self, request: InputRequest, search: ResolvedSearchConfiguration
    ) -> LibraryResult:
        with self.tracer.span("library") if self.tracer else nullcontext():
            return await self._run(request, search)

    async def _run(
        self, request: InputRequest, search: ResolvedSearchConfiguration
    ) -> LibraryResult:
        if request.domain.casefold() != search.domain.casefold():
            raise ValueError("request and resolved search domains must match")

        queries = include_upload_query(await self.query_planner.plan(request, search), search, SourceQuery)
        self._validate_queries(queries, search)
        if self.tracer:
            self.tracer.budget("library", "search_queries", len(queries), search.max_queries)

        sources: list[SourceRecord] = []
        seen: dict[str, SourceRecord] = {}
        type_counts: Counter[str] = Counter()
        for query in queries:
            remaining = search.max_sources - len(sources)
            if remaining <= 0:
                break
            source_types = [
                source_type for source_type in query.source_types
                if type_counts[source_type]
                < search.max_records_by_type.get(source_type, search.max_sources)
            ]
            if not source_types:
                continue
            bounded = query.model_copy(update={
                "max_results": min(query.max_results, remaining),
                "source_types": source_types,
            })
            with (
                self.tracer.span(
                    "library_source_search",
                    provider_id=query.provider_id,
                    query_id=query.query_id,
                )
                if self.tracer
                else nullcontext()
            ):
                results = await self.adapters[query.provider_id].search(bounded)
            if len(results) > bounded.max_results:
                raise ValueError(f"adapter {query.provider_id!r} exceeded the query result limit")
            for source in results:
                if source.provider != query.provider_id or source.query_id != query.query_id:
                    raise ValueError("adapter returned a source for the wrong provider or query")
                if source.source_type not in bounded.source_types:
                    raise ValueError("adapter returned an unrequested source type")
                if not source_is_within_age_limit(source, search):
                    continue
                previous = seen.get(source.source_id)
                if previous is None:
                    if type_counts[source.source_type] >= search.max_records_by_type.get(
                        source.source_type, search.max_sources
                    ):
                        continue
                    sources.append(source)
                    seen[source.source_id] = source
                    type_counts[source.source_type] += 1
                elif previous != source:
                    raise ValueError(f"conflicting records have source ID {source.source_id!r}")
            if self.tracer:
                self.tracer.budget("library", "source_records", len(sources), search.max_sources)

        chunks = [
            SourceChunk(
                chunk_id=f"{source.source_id}-c0",
                source_id=source.source_id,
                ordinal=0,
                text=source.full_text or source.abstract_or_snippet,
                content_hash=sha256((source.full_text or source.abstract_or_snippet).encode("utf-8")).hexdigest(),
                token_count=max(1, len(source.full_text or source.abstract_or_snippet) // 4),
                start_offset=0,
                end_offset=len(source.full_text or source.abstract_or_snippet),
            )
            for source in sources
            if source.retrieval_status in (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL)
            and (source.full_text or source.abstract_or_snippet)
        ]
        warnings = []
        if not chunks:
            warnings.append("No usable source snippets were found for candidate evaluation.")
        if self.tracer:
            self.tracer.event("library", "chunks_ready", count=len(chunks))
        return LibraryResult(sources=sources, chunks=chunks, warnings=warnings)

    def _validate_queries(
        self, queries: list[SourceQuery], search: ResolvedSearchConfiguration
    ) -> None:
        if len(queries) > search.max_queries:
            raise ValueError("query planner exceeded max_queries")
        if len({query.query_id for query in queries}) != len(queries):
            raise ValueError("query IDs must be unique")
        allowed = {provider.provider_id: provider for provider in search.providers}
        for query in queries:
            if query.provider_id not in allowed or query.provider_id not in self.adapters:
                raise ValueError(f"no approved adapter for provider {query.provider_id!r}")
            provider = allowed[query.provider_id]
            if not set(query.source_types).issubset(provider.source_types):
                raise ValueError(f"query {query.query_id!r} requests an unavailable source type")
            if not set(query.content_types).issubset(provider.content_types):
                raise ValueError(
                    f"query {query.query_id!r} requests an unavailable content type "
                    f"from provider {query.provider_id!r}"
                )
            if query.max_results > search.max_results_per_query:
                raise ValueError(f"query {query.query_id!r} exceeds max_results_per_query")
