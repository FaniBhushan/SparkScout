"""Search approved sources and return candidate ideas for later evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from typing import Protocol

from src.adapters.base import SourceAdapter
from src.models import (
    CandidateIdea,
    InputRequest,
    ResolvedSearchConfiguration,
    ScoutQuery,
    ScoutResult,
    SourceRecord,
)
from src.models.source_record import RetrievalStatus
from src.observability import RunTracer


class ScoutQueryPlanner(Protocol):
    """Turn the request and search limits into bounded research queries."""

    async def plan(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
    ) -> list[ScoutQuery]: ...


class CandidateGenerator(Protocol):
    """Propose ideas from the request and captured evidence."""

    async def generate(
        self,
        request: InputRequest,
        sources: list[SourceRecord],
    ) -> list[CandidateIdea]: ...


class ScoutWorker:
    """Search approved sources and return candidate ideas for later evaluation."""

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter],
        query_planner: ScoutQueryPlanner,
        candidate_generator: CandidateGenerator,
        tracer: RunTracer | None = None,
    ) -> None:
        self.adapters = adapters
        self.query_planner = query_planner
        self.candidate_generator = candidate_generator
        self.tracer = tracer

    async def run(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
    ) -> ScoutResult:
        trace_span = self.tracer.span("scout") if self.tracer else nullcontext()
        with trace_span:
            return await self._run(request, search)

    async def _run(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
    ) -> ScoutResult:
        if request.domain.casefold() != search.domain.casefold():
            raise ValueError("request and resolved search domains must match")

        queries = await self.query_planner.plan(request, search)
        self._validate_queries(queries, search)
        if self.tracer:
            self.tracer.budget("scout", "search_queries", len(queries), search.max_queries)

        sources: list[SourceRecord] = []
        seen_sources: dict[str, SourceRecord] = {}
        search_calls = 0
        for query in queries:
            remaining = search.max_sources - len(sources)
            if remaining <= 0:
                break

            bounded_query = query.model_copy(
                update={"max_results": min(query.max_results, remaining)}
            )
            trace_span = (
                self.tracer.span(
                    "source_search", provider_id=query.provider_id, query_id=query.query_id
                )
                if self.tracer
                else nullcontext()
            )
            with trace_span:
                results = await self.adapters[query.provider_id].search(bounded_query)
            search_calls += 1
            if self.tracer:
                self.tracer.event(
                    "source_search",
                    "results",
                    provider_id=query.provider_id,
                    query_id=query.query_id,
                    count=len(results),
                )
                self.tracer.budget("scout", "search_calls", search_calls, search.max_queries)
            if len(results) > bounded_query.max_results:
                raise ValueError(
                    f"adapter {query.provider_id!r} exceeded the query result limit"
                )

            for source in results:
                if source.provider != query.provider_id or source.query_id != query.query_id:
                    raise ValueError("adapter returned a source for the wrong provider or query")
                if source.source_type not in query.source_types:
                    raise ValueError("adapter returned an unrequested source type")
                previous = seen_sources.get(source.source_id)
                if previous is None:
                    sources.append(source)
                    seen_sources[source.source_id] = source
                elif previous != source:
                    raise ValueError(
                        f"conflicting records have the same source ID {source.source_id!r}"
                    )
            if self.tracer:
                self.tracer.budget("scout", "source_records", len(sources), search.max_sources)

        available_sources = [
            source
            for source in sources
            if source.retrieval_status in (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL)
        ]
        if not available_sources:
            return ScoutResult(
                sources=sources,
                warnings=["No usable sources were found for candidate discovery."],
            )

        trace_span = self.tracer.span("candidate_generation") if self.tracer else nullcontext()
        with trace_span:
            candidates = await self.candidate_generator.generate(request, available_sources)
        if self.tracer:
            self.tracer.budget(
                "scout", "candidate_count", len(candidates), request.desired_candidate_count
            )
        warnings = []
        if len(candidates) < request.desired_candidate_count:
            warnings.append(
                f"Found {len(candidates)} of {request.desired_candidate_count} requested candidates."
            )
        return ScoutResult(candidates=candidates, sources=sources, warnings=warnings)

    def _validate_queries(
        self,
        queries: list[ScoutQuery],
        search: ResolvedSearchConfiguration,
    ) -> None:
        if len(queries) > search.max_queries:
            raise ValueError("query planner exceeded max_queries")
        if len({query.query_id for query in queries}) != len(queries):
            raise ValueError("query IDs must be unique")

        allowed = {
            provider.provider_id: set(provider.source_types)
            for provider in search.providers
        }
        available_content = set(search.content_types)
        for query in queries:
            if query.provider_id not in allowed or query.provider_id not in self.adapters:
                raise ValueError(f"no approved adapter for provider {query.provider_id!r}")
            if not set(query.source_types).issubset(allowed[query.provider_id]):
                raise ValueError(f"query {query.query_id!r} requests an unavailable source type")
            if not set(query.content_types).issubset(available_content):
                raise ValueError(f"query {query.query_id!r} requests an unavailable content type")
            if query.max_results > search.max_results_per_query:
                raise ValueError(f"query {query.query_id!r} exceeds max_results_per_query")
