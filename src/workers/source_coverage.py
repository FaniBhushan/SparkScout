"""Recover a short source landscape using remaining approved search allowance."""

from collections import Counter
from collections.abc import Mapping
from contextlib import nullcontext

from src.adapters.base import SourceAdapter
from src.models import InputRequest, ResolvedSearchConfiguration, SourceQuery
from src.models.source_record import RetrievalStatus, SourceRecord
from src.observability import RunTracer
from src.workers.source_filter import same_source_content, source_is_within_age_limit
from src.sources.merge import capture_excerpts, is_live_source, merge_source_records


async def recover_source_coverage(
    request: InputRequest,
    search: ResolvedSearchConfiguration,
    sources: list[SourceRecord],
    adapters: Mapping[str, SourceAdapter],
    *,
    planned_queries: int,
    stage: str,
    tracer: RunTracer | None = None,
    quarantined: set[str] | None = None,
) -> tuple[list[SourceRecord], list[str]]:
    """Try each approved provider at most once, without another planning call.

    Planned source-type count is not actual source coverage: a provider may have
    no records of a requested type. Recovery therefore examines usable receipts
    and missing required types, within the original query, record, and byte caps.
    """
    kept = list(sources)
    quarantined = set(quarantined or ())
    by_id = {source.source_id: source for source in kept}
    counts = Counter(source.source_type for source in kept)
    warnings = []
    used = planned_queries
    for provider in search.providers:
        if provider.provider_id not in adapters:
            continue
        usable = [source for source in kept if source.retrieval_status in
                  (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL)]
        missing = set(search.required_source_types) - {source.source_type for source in usable}
        if len(usable) >= search.minimum_source_count and not missing:
            break
        remaining = search.max_sources - len(kept)
        if used >= search.max_queries or remaining <= 0:
            break
        allowed = [kind for kind in provider.source_types
                   if counts[kind] < search.max_records_by_type.get(kind, search.max_sources)]
        if not allowed:
            continue
        # Prefer a missing mandatory type, otherwise broaden within the user's
        # approved types. Do not invent sources or lower the coverage threshold.
        kinds = [kind for kind in allowed if kind in missing] or allowed
        query = SourceQuery(
            query_id=f"{stage}-coverage-{used + 1}", provider_id=provider.provider_id,
            text=" ".join([request.domain, *request.interests, "datasets methods resources user needs"]),
            source_types=kinds, content_types=provider.content_types,
            max_results=min(search.max_results_per_query, remaining),
        )
        with (tracer.span("coverage_search", provider_id=provider.provider_id, query_id=query.query_id)
              if tracer else nullcontext()):
            results = await adapters[provider.provider_id].search(query)
        used += 1
        warnings.append(f"{stage.capitalize()} used a remaining query to recover source coverage.")
        for source in results[:query.max_results]:
            if source.provider != query.provider_id or source.query_id != query.query_id:
                raise ValueError("adapter returned a source for the wrong provider or query")
            if source.source_type not in kinds:
                raise ValueError("adapter returned an unrequested source type")
            if not source_is_within_age_limit(source, search):
                continue
            source = capture_excerpts(source)
            if source.source_id in quarantined:
                continue
            previous = by_id.get(source.source_id)
            if previous is not None:
                if is_live_source(source):
                    try:
                        merged = merge_source_records(previous, source)
                    except ValueError:
                        quarantined.add(source.source_id)
                        kept.remove(previous)
                        by_id.pop(source.source_id)
                        counts[previous.source_type] -= 1
                        warnings.append(f"{stage.capitalize()} quarantined conflicting source {source.source_id}.")
                        if tracer:
                            tracer.event(stage, "source_receipt_quarantined", count=1)
                        continue
                    kept[kept.index(previous)] = merged
                    by_id[source.source_id] = merged
                elif not same_source_content(previous, source):
                    raise ValueError("conflicting source records during coverage recovery")
                continue
            if counts[source.source_type] >= search.max_records_by_type.get(source.source_type, search.max_sources):
                continue
            kept.append(source)
            by_id[source.source_id] = source
            counts[source.source_type] += 1
        if tracer:
            tracer.budget(stage, "search_queries", used, search.max_queries)
            tracer.budget(stage, "source_records", len(kept), search.max_sources)
    return kept, warnings
