"""Deterministic recovery for model-planned searches that exceed hard limits."""

from typing import TypeVar

from src.models import ResolvedSearchConfiguration, SourceQuery


QueryT = TypeVar("QueryT", bound=SourceQuery)


def bound_query_plan(
    queries: list[QueryT], search: ResolvedSearchConfiguration
) -> tuple[list[QueryT], list[str]]:
    """Clamp result counts and trim excess queries before any provider is called."""

    warnings: list[str] = []
    providers = {provider.provider_id: provider for provider in search.providers}
    bounded: list[QueryT] = []
    for query in queries:
        provider = providers.get(query.provider_id)
        if provider is None:
            # Leave this for the worker's fail-closed provider authorization check.
            bounded.append(query)
            continue
        source_types = [item for item in query.source_types if item in provider.source_types]
        content_types = [item for item in query.content_types if item in provider.content_types]
        if not source_types or not content_types:
            warnings.append(
                f"Query {query.query_id} was skipped because it has no allowed source/content types."
            )
            continue
        if source_types != query.source_types or content_types != query.content_types:
            warnings.append(f"Query {query.query_id} was limited to provider-approved types.")
            bounded.append(query.model_copy(update={
                "source_types": source_types,
                "content_types": content_types,
            }))
        else:
            bounded.append(query)

    selected_types = {item for query in bounded for item in query.source_types}
    if len(selected_types) < search.minimum_source_count:
        for index, query in enumerate(bounded):
            provider = providers.get(query.provider_id)
            if provider is None:
                continue
            additions = [item for item in provider.source_types if item not in selected_types]
            if not additions:
                continue
            bounded[index] = query.model_copy(update={
                "source_types": [*query.source_types, *additions],
            })
            selected_types.update(additions)
            warnings.append(
                f"Query {query.query_id} was broadened to approved source types "
                "to support the minimum source coverage."
            )
            if len(selected_types) >= search.minimum_source_count:
                break

    if len(bounded) > search.max_queries:
        removed = len(bounded) - search.max_queries
        bounded = bounded[: search.max_queries]
        warnings.append(
            f"Search plan exceeded the {search.max_queries}-query limit; "
            f"{removed} extra quer{'y' if removed == 1 else 'ies'} were skipped."
        )

    result: list[QueryT] = []
    for query in bounded:
        if query.max_results > search.max_results_per_query:
            result.append(
                query.model_copy(update={"max_results": search.max_results_per_query})
            )
            warnings.append(
                f"Query {query.query_id} requested {query.max_results} results; "
                f"limited it to {search.max_results_per_query}."
            )
        else:
            result.append(query)
    return result, warnings
