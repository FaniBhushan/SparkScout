"""Scout worker: search approved sources and return candidate ideas."""

from __future__ import annotations

from collections import Counter
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
from src.adapters.http_json import SourceAdapterError
from src.runtime.budgets import ProviderCallBudgetExceeded
from src.workers.provider_failures import may_skip_provider_failure
from src.workers.source_filter import same_source_content, source_is_within_age_limit
from src.sources.merge import capture_excerpts, is_live_source, merge_source_records
from src.workers.query_limits import bound_query_plan
from src.workers.upload_query import include_upload_query
from src.workers.source_coverage import recover_source_coverage


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

        queries = include_upload_query(await self.query_planner.plan(request, search), search, ScoutQuery)
        queries, warnings = bound_query_plan(queries, search)
        self._validate_queries(queries, search)
        if self.tracer:
            if warnings:
                self.tracer.event("scout", "query_plan_adjusted", count=len(warnings))
            self.tracer.budget("scout", "search_queries", len(queries), search.max_queries)

        sources: list[SourceRecord] = []
        seen_sources: dict[str, SourceRecord] = {}
        quarantined: set[str] = set()
        type_counts: Counter[str] = Counter()
        search_calls = 0
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

            bounded_query = query.model_copy(
                update={
                    "max_results": min(query.max_results, remaining),
                    "source_types": source_types,
                }
            )
            trace_span = (
                self.tracer.span(
                    "source_search", provider_id=query.provider_id, query_id=query.query_id
                )
                if self.tracer
                else nullcontext()
            )
            with trace_span:
                try:
                    results = await self.adapters[query.provider_id].search(bounded_query)
                except (ProviderCallBudgetExceeded, SourceAdapterError) as error:
                    if not may_skip_provider_failure(query.provider_id, source_types, search):
                        raise
                    warnings.append(
                        f"Scout skipped {query.provider_id} search ({type(error).__name__}); "
                        "continuing with other available sources."
                    )
                    if self.tracer:
                        self.tracer.event(
                            "scout", "optional_provider_skipped",
                            provider_id=query.provider_id,
                            failure_type=type(error).__name__,
                        )
                    search_calls += 1
                    if self.tracer:
                        self.tracer.budget("scout", "search_calls", search_calls, search.max_queries)
                    continue
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
                if source.source_type not in bounded_query.source_types:
                    raise ValueError("adapter returned an unrequested source type")
                if not source_is_within_age_limit(source, search):
                    continue
                source = capture_excerpts(source)
                if source.source_id in quarantined:
                    continue
                previous = seen_sources.get(source.source_id)
                if previous is None:
                    if type_counts[source.source_type] >= search.max_records_by_type.get(
                        source.source_type, search.max_sources
                    ):
                        continue
                    sources.append(source)
                    seen_sources[source.source_id] = source
                    type_counts[source.source_type] += 1
                elif is_live_source(source):
                    try:
                        merged = merge_source_records(previous, source)
                    except ValueError:
                        quarantined.add(source.source_id)
                        sources.remove(previous)
                        seen_sources.pop(source.source_id)
                        type_counts[previous.source_type] -= 1
                        warnings.append(f"Scout quarantined conflicting source {source.source_id}.")
                        if self.tracer:
                            self.tracer.event("scout", "source_receipt_quarantined", count=1)
                        continue
                    sources[sources.index(previous)] = merged
                    seen_sources[source.source_id] = merged
                elif not same_source_content(previous, source):
                    raise ValueError(
                        f"conflicting records have the same source ID {source.source_id!r}"
                    )
            if self.tracer:
                self.tracer.budget("scout", "source_records", len(sources), search.max_sources)

        sources, recovery_warnings = await recover_source_coverage(
            request, search, sources, self.adapters, planned_queries=len(queries),
            stage="scout", tracer=self.tracer,
            quarantined=quarantined,
        )
        warnings.extend(recovery_warnings)
        available_sources = [
            source
            for source in sources
            if source.retrieval_status in (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL)
        ]
        if not available_sources:
            return ScoutResult(
                sources=sources,
                warnings=[*warnings, "No usable sources were found for candidate discovery."],
            )

        trace_span = self.tracer.span("candidate_generation") if self.tracer else nullcontext()
        with trace_span:
            candidates = await self.candidate_generator.generate(request, available_sources)
        # Apply the boundary for injected generators as well as the LLM implementation.
        candidates = [item for item in candidates if item.origin != "synthetic"]
        if self.tracer:
            self.tracer.budget(
                "scout", "candidate_count", len(candidates), request.desired_candidate_count
            )
        warnings = list(warnings)
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
