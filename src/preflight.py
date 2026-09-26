"""Resolve submitted choices once, before model or source-provider calls."""

from __future__ import annotations

import re
from collections.abc import Mapping

from src.adapters.base import SourceAdapter
from src.configuration import (
    load_search_defaults,
    load_budget_policy,
    load_source_configuration,
    resolve_search_configuration,
)
from src.evaluation import load_evaluation_configuration
from src.guardrails import input_advisories
from src.models import (
    InputRequest,
    BudgetPolicy,
    PreparedRun,
    ResolvedSearchConfiguration,
    RunBudgetLimits,
    SearchDefaults,
    SourceConfiguration,
    SourcePolicy,
    SubmittedRunConfiguration,
    ValueOrigin,
    effective_configuration_checksum,
    resolve_budget_limits,
)


def _effective_request(submitted: SubmittedRunConfiguration) -> InputRequest:
    """Keep the legacy request policy usable without accepting conflicting copies."""

    request_policy = submitted.request.source_policy
    search_policy = submitted.search.source_policy
    empty = SourcePolicy()
    if request_policy != empty and search_policy != empty and request_policy != search_policy:
        raise ValueError("request and search source policies conflict")
    selected_policy = search_policy if search_policy != empty else request_policy
    return InputRequest.model_validate({
        **submitted.request.model_dump(mode="python"),
        "source_policy": selected_policy.model_dump(mode="python"),
    })


def _resolve_search(
    request: InputRequest,
    submitted: SubmittedRunConfiguration,
    adapters: Mapping[str, SourceAdapter],
    sources: SourceConfiguration,
    defaults: SearchDefaults,
) -> ResolvedSearchConfiguration:
    search = submitted.search
    domain_key = re.sub(r"[\s-]+", "_", request.domain.strip().casefold())
    if sources.domains and domain_key not in sources.domains:
        if not search.allow_other_domain:
            raise ValueError(f"unknown source domain: {request.domain!r}")
        # An Other domain uses only providers explicitly marked for all domains.
        sources = sources.model_copy(update={"domains": [*sources.domains, domain_key]})
    base = resolve_search_configuration(
        request,
        adapters,
        preset_name=search.preset,
        requested_limits=search.limits,
        sources=sources,
        defaults=defaults,
    )
    ready = {provider.provider_id: provider for provider in base.providers}
    if search.provider_ids:
        unavailable = set(search.provider_ids) - set(ready)
        if unavailable:
            raise ValueError(f"requested providers are unavailable: {sorted(unavailable)}")
        selected = [ready[provider_id] for provider_id in search.provider_ids]
    else:
        selected = base.providers
        if search.fallback_policy == "fail_if_unavailable":
            allowed_types = (
                set(request.source_policy.include_types) or set(sources.source_types)
            ) - set(request.source_policy.exclude_types)
            route = sources.routes.get(domain_key)
            route_providers = (
                set(route.providers) | set(route.fallback_providers)
                if route else set(sources.providers)
            )
            expected = {
                provider_id for provider_id, definition in sources.providers.items()
                if definition.enabled
                and provider_id in route_providers
                and (definition.adapter != "frozen_fixture" or provider_id in adapters)
                and (domain_key in definition.domains or "*" in definition.domains)
                and set(definition.emits) & allowed_types
            }
            unavailable = expected - {provider.provider_id for provider in selected}
            if unavailable:
                raise ValueError(
                    f"enabled providers are unavailable: {sorted(unavailable)}"
                )

    if search.language:
        unsupported = [
            provider.provider_id for provider in selected
            if not sources.providers[provider.provider_id].supports_language
        ]
        if unsupported and search.provider_ids:
            raise ValueError(f"selected providers cannot enforce language: {unsupported}")
        selected = [provider for provider in selected if provider.provider_id not in unsupported]
        if not selected:
            raise ValueError("no ready provider can enforce the selected language")

    if search.content_types:
        allowed_content = set(search.content_types)
        available_content = {
            item for provider in selected for item in provider.content_types
        }
        unavailable_content = allowed_content - available_content
        if unavailable_content:
            raise ValueError(f"requested content types are unavailable: {sorted(unavailable_content)}")
        filtered = [
            provider.model_copy(update={
                "content_types": [
                    item for item in provider.content_types if item in allowed_content
                ]
            })
            for provider in selected
        ]
        if search.provider_ids and any(not provider.content_types for provider in filtered):
            raise ValueError("a requested provider cannot supply the selected content types")
        selected = [provider for provider in filtered if provider.content_types]

    covered_types = {item for provider in selected for item in provider.source_types}
    if not set(base.required_source_types).issubset(covered_types):
        raise ValueError("selected providers cannot supply required source types")
    if request.source_policy.include_types and not set(
        request.source_policy.include_types
    ).issubset(covered_types):
        raise ValueError("selected providers cannot supply included source types")
    unavailable_caps = set(request.source_policy.max_records_by_type) - covered_types
    if unavailable_caps:
        raise ValueError(f"record caps reference unavailable source types: {sorted(unavailable_caps)}")
    return ResolvedSearchConfiguration(
        domain=base.domain,
        providers=selected,
        content_types=list(dict.fromkeys(
            item for provider in selected for item in provider.content_types
        )),
        language=search.language,
        upload_sha256={item.filename: item.sha256 for item in search.uploads},
        max_queries=base.max_queries,
        max_results_per_query=base.max_results_per_query,
        max_sources=base.max_sources,
        minimum_source_count=base.minimum_source_count,
        max_records_by_type={
            key: value for key, value in base.max_records_by_type.items()
            if key in covered_types
        },
        required_source_types=base.required_source_types,
        max_age_days_by_type={
            key: search.recency_days or value for key, value in base.max_age_days_by_type.items()
            if key in covered_types
        },
        as_of_date=base.as_of_date,
        published_from=search.published_from,
        published_to=search.published_to,
        require_published_date=bool(
            search.recency_days or search.published_from or search.published_to
        ),
    )


def _field_origins(submitted: SubmittedRunConfiguration) -> dict[str, ValueOrigin]:
    """Record default versus explicit fields; later deductions can override origins."""

    origins = {
        f"{section}.{field}": (
            "explicit" if field in model.model_fields_set else "default"
        )
        for section, model in (
            ("request", submitted.request),
            ("search", submitted.search),
            ("evaluation", submitted.evaluation),
            ("budgets", submitted.budgets),
        )
        for field in type(model).model_fields
        if field != "schema_version"
    }
    if "preset" not in submitted.search.model_fields_set:
        origins["search.preset"] = "preset"
    if submitted.evaluation.weights is None:
        origins["evaluation.weights"] = "preset"
    origins.update(submitted.field_origins)
    return origins


def prepare_run(
    submitted: SubmittedRunConfiguration,
    available_adapters: Mapping[str, SourceAdapter],
    *,
    sources: SourceConfiguration | None = None,
    defaults: SearchDefaults | None = None,
    budget_policy: BudgetPolicy | None = None,
) -> PreparedRun:
    """Validate choices and freeze the exact request, search, and rubric for execution."""

    advisories = input_advisories(submitted)
    if submitted.search.custom_instructions or submitted.evaluation.custom_instructions:
        raise ValueError("free-text configuration instructions require interpretation before a run")
    registry = sources if sources is not None else load_source_configuration()
    presets = defaults if defaults is not None else load_search_defaults()
    request = _effective_request(submitted)
    if submitted.search.evidence_tiers:
        permitted = {
            source_type for source_type, definition in registry.source_types.items()
            if definition.evidence_tier in submitted.search.evidence_tiers
            and any(
                provider.enabled and provider_id in available_adapters
                and source_type in provider.emits
                for provider_id, provider in registry.providers.items()
            )
        }
        if not permitted:
            raise ValueError("no ready source types match selected evidence tiers")
        policy = request.source_policy
        if set(policy.include_types) - permitted or set(policy.required_types) - permitted:
            raise ValueError("source type requirements conflict with selected evidence tiers")
        request = InputRequest.model_validate({
            **request.model_dump(mode="python"),
            "source_policy": {
                **policy.model_dump(mode="python"),
                "include_types": policy.include_types or sorted(permitted),
            },
        })
    search = _resolve_search(request, submitted, available_adapters, registry, presets)
    evaluation = load_evaluation_configuration(
        submitted.evaluation.rubric_preset,
        weights=submitted.evaluation.weights,
    )
    if submitted.evaluation.retrieval_top_k is not None:
        if submitted.evaluation.retrieval_top_k > evaluation.max_context_chunks:
            raise ValueError("retrieval_top_k exceeds the configured context chunk limit")
        evaluation = type(evaluation).model_validate({
            **evaluation.model_dump(mode="python"),
            "retrieval_top_k": submitted.evaluation.retrieval_top_k,
        })
    budgets = resolve_budget_limits(
        submitted.budgets,
        budget_policy if budget_policy is not None else load_budget_policy(),
    )
    budgets = RunBudgetLimits.model_validate({
        **budgets.model_dump(mode="python"),
        "provider_call_limits": {
            provider.provider_id: registry.providers[provider.provider_id].max_requests_per_run
            for provider in search.providers
        },
    })
    upload_adapter = available_adapters.get("user_upload")
    actual_uploads = getattr(upload_adapter, "manifest", []) if upload_adapter else []
    if submitted.search.uploads != actual_uploads:
        raise ValueError("reviewed upload receipts do not match the supplied files")
    if actual_uploads:
        if "user_upload" not in {provider.provider_id for provider in search.providers}:
            raise ValueError("uploaded files must be included in the selected providers")
        upload_provider = next(
            provider for provider in search.providers if provider.provider_id == "user_upload"
        )
        if "licensed_full_text" not in upload_provider.content_types:
            raise ValueError("uploaded documents require the full-text content type")
        if sum(item.byte_count for item in actual_uploads) > budgets.max_source_bytes:
            raise ValueError("uploaded file bytes exceed the run source-byte budget")
        if sum(item.pdf_pages for item in actual_uploads) > budgets.max_pdf_pages:
            raise ValueError("uploaded PDF pages exceed the run page budget")
        if search.language and any(item.language != search.language for item in actual_uploads):
            raise ValueError("uploaded document languages do not match the search language")
    return PreparedRun(
        submitted=submitted.model_copy(deep=True),
        request=request.model_copy(deep=True),
        search=search,
        evaluation=evaluation,
        budgets=budgets,
        field_origins=_field_origins(submitted),
        warnings=list(dict.fromkeys([
            *advisories, *getattr(upload_adapter, "warnings", []),
        ])),
        configuration_checksum=effective_configuration_checksum(
            request, search, evaluation, budgets
        ),
    )
