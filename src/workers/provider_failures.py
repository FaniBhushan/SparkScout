"""Decide when a provider failure may degrade a research branch safely."""

from src.models import ResolvedSearchConfiguration


def may_skip_provider_failure(
    provider_id: str,
    query_source_types: list[str],
    search: ResolvedSearchConfiguration,
) -> bool:
    """Skip optional remote failures, but preserve local and mandatory inputs."""

    if provider_id in {"user_upload", "frozen_fixture"}:
        return False
    required_here = set(query_source_types) & set(search.required_source_types)
    for source_type in required_here:
        other_suppliers = [
            provider for provider in search.providers
            if provider.provider_id != provider_id and source_type in provider.source_types
        ]
        if not other_suppliers:
            return False
    return True
