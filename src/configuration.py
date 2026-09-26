"""Load and validate operator configuration files."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from src.adapters.base import SourceAdapter
from src.models import (
    InputRequest,
    BudgetPolicy,
    ResolvedProvider,
    ResolvedSearchConfiguration,
    SearchDefaults,
    SearchLimits,
    SourceConfiguration,
)


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def load_source_configuration(path: Path = CONFIG_DIR / "sources.json") -> SourceConfiguration:
    """Load the approved source type, provider, and domain registry."""

    return SourceConfiguration.model_validate_json(path.read_text(encoding="utf-8"))


def load_search_defaults(path: Path = CONFIG_DIR / "search_defaults.json") -> SearchDefaults:
    """Load search presets and ensure none exceed operator hard limits."""

    data = json.loads(path.read_text(encoding="utf-8"))
    return SearchDefaults.model_validate(data)


def load_budget_policy(path: Path = CONFIG_DIR / "budgets.json") -> BudgetPolicy:
    """Load run defaults and operator ceilings for time, tokens, and cost."""

    return BudgetPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_search_configuration(
    request: InputRequest,
    available_adapters: Mapping[str, SourceAdapter],
    *,
    preset_name: str = "balanced",
    requested_limits: SearchLimits | None = None,
    sources: SourceConfiguration | None = None,
    defaults: SearchDefaults | None = None,
) -> ResolvedSearchConfiguration:
    """Select approved search permissions from config and ready adapters."""

    sources = sources if sources is not None else load_source_configuration()
    defaults = defaults if defaults is not None else load_search_defaults()
    domain_key = re.sub(r"[\s-]+", "_", request.domain.strip().casefold())
    if sources.domains and domain_key not in sources.domains:
        raise ValueError(f"unknown source domain: {request.domain!r}")
    try:
        preset = defaults.presets[preset_name]
    except KeyError:
        raise ValueError(f"unknown search preset: {preset_name!r}") from None

    limits = requested_limits if requested_limits is not None else SearchLimits(
        max_queries=preset.max_queries,
        max_results_per_query=preset.max_results_per_query,
        max_sources=preset.max_sources,
    )
    for field in ("max_queries", "max_results_per_query", "max_sources"):
        if getattr(limits, field) > getattr(defaults.hard_limits, field):
            raise ValueError(f"requested {field} exceeds the operator hard limit")
    if limits.max_sources < preset.minimum_source_count:
        raise ValueError("max_sources cannot be below the preset's minimum_source_count")

    policy = request.source_policy
    known_types = set(sources.source_types)
    mentioned_types = (
        set(policy.include_types)
        | set(policy.exclude_types)
        | set(policy.required_types)
        | set(policy.max_records_by_type)
    )
    unknown_types = mentioned_types - known_types
    if unknown_types:
        raise ValueError(f"unknown source types: {sorted(unknown_types)}")

    route = sources.routes.get(domain_key)
    allowed_types = (set(policy.include_types) or known_types) - set(policy.exclude_types)
    required_types = set(policy.required_types)
    if route:
        required_types.update(route.required_types)
    if not required_types.issubset(allowed_types):
        raise ValueError("domain and user source requirements conflict")

    def usable_provider(provider_id: str) -> ResolvedProvider | None:
        definition = sources.providers[provider_id]
        if (
            not definition.enabled
            or provider_id not in available_adapters
            or (domain_key not in definition.domains and "*" not in definition.domains)
        ):
            return None
        source_types = [item for item in definition.emits if item in allowed_types]
        content_types = [
            item for item in defaults.content_types if item in definition.capabilities
        ]
        if not source_types or not content_types:
            return None
        return ResolvedProvider(
            provider_id=provider_id,
            source_types=source_types,
            content_types=content_types,
        )

    primary_ids = route.providers if route else list(sources.providers)
    selected = [
        provider
        for provider_id in dict.fromkeys(primary_ids)
        if (provider := usable_provider(provider_id)) is not None
    ]
    if route:
        # Fallback providers supplement missing required or preferred source types.
        target_types = required_types | (set(route.preferred_types) & allowed_types)
        covered_types = {item for provider in selected for item in provider.source_types}
        for provider_id in route.fallback_providers:
            if selected and target_types.issubset(covered_types):
                break
            if provider_id in {provider.provider_id for provider in selected}:
                continue
            provider = usable_provider(provider_id)
            if provider is not None:
                selected.append(provider)
                covered_types.update(provider.source_types)

    if not selected:
        raise ValueError(f"no enabled, ready providers for domain {request.domain!r}")
    covered_types = {item for provider in selected for item in provider.source_types}
    missing_types = required_types - covered_types
    if missing_types:
        raise ValueError(f"no available provider for required source types: {sorted(missing_types)}")

    unselected_caps = set(policy.max_records_by_type) - covered_types
    if unselected_caps:
        raise ValueError(f"record caps reference unavailable source types: {sorted(unselected_caps)}")
    if any(cap > limits.max_sources for cap in policy.max_records_by_type.values()):
        raise ValueError("per-type record caps cannot exceed max_sources")
    # Catalog values are defaults; an explicit request can tighten or raise them
    # within the run's overall source ceiling.
    type_caps = {
        source_type: min(
            policy.max_records_by_type.get(
                source_type, sources.source_types[source_type].default_max_records
            ),
            limits.max_sources,
        )
        for source_type in sorted(covered_types)
    }
    # A type can be stricter than its preset (for example, recent repositories).
    # Preserve the reference date so both branches apply the same age decision.
    age_limits = {
        source_type: min(
            preset.recency_days,
            sources.source_types[source_type].default_max_age_days or preset.recency_days,
        )
        for source_type in sorted(covered_types)
    }

    content_types = list(
        dict.fromkeys(item for provider in selected for item in provider.content_types)
    )
    return ResolvedSearchConfiguration(
        domain=request.domain,
        providers=selected,
        content_types=content_types,
        max_queries=limits.max_queries,
        max_results_per_query=limits.max_results_per_query,
        max_sources=limits.max_sources,
        minimum_source_count=preset.minimum_source_count,
        max_records_by_type=type_caps,
        required_source_types=sorted(required_types),
        max_age_days_by_type=age_limits,
        as_of_date=date.today(),
    )
