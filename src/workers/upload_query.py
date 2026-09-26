"""Ensure user-provided documents enter both independent research branches."""

from __future__ import annotations

from src.models import ResolvedSearchConfiguration, SourceQuery


def include_upload_query(
    queries: list[SourceQuery], search: ResolvedSearchConfiguration, query_type: type[SourceQuery]
) -> list[SourceQuery]:
    provider = next((item for item in search.providers if item.provider_id == "user_upload"), None)
    if provider is None:
        return queries
    content = ["metadata", "licensed_full_text"]
    if not set(content).issubset(provider.content_types):
        raise ValueError("selected upload provider must allow licensed full text")
    for index, query in enumerate(queries):
        if query.provider_id == "user_upload":
            queries[index] = query_type.model_validate({
                **query.model_dump(mode="python"),
                "source_types": ["user_document"],
                "content_types": content,
            })
            return queries
    upload = query_type(
        query_id="uploaded-documents", provider_id="user_upload",
        text="User-provided documents", source_types=["user_document"],
        content_types=content, max_results=min(5, search.max_results_per_query),
    )
    # A required local source takes one of the bounded query slots.
    if len(queries) >= search.max_queries:
        return [*queries[:search.max_queries - 1], upload]
    return [*queries, upload]
