"""UI-independent catalog and review merge shared by Streamlit tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from src.adapters.base import SourceAdapter
from src.configuration import load_budget_policy, load_search_defaults, load_source_configuration
from src.evaluation.rubric import DEFAULT_RUBRIC_PATH
from src.interpretation import confirm_interpretation
from src.models import (
    InterpretationReview,
    PromptInterpretationDraft,
    SubmittedRunConfiguration,
)


@dataclass(frozen=True)
class InterfaceCatalog:
    domains: list[str]
    providers: list[str]
    source_types: list[str]
    content_types: list[str]
    languages: list[str]
    evidence_tiers: list[str]
    search_presets: list[str]
    preset_limits: dict[str, dict[str, int]]
    rubric_presets: list[str]
    criteria_labels: dict[str, str]
    rubric_weights: dict[str, dict[str, int]]
    default_rubric: str
    max_queries: int
    max_results_per_query: int
    max_sources: int
    max_elapsed_seconds: float
    default_elapsed_seconds: float
    max_model_tokens: int
    default_model_tokens: int
    max_source_bytes: int
    default_source_bytes: int
    max_pdf_pages: int
    default_pdf_pages: int
    max_estimated_cost_usd: float | None
    max_context_chunks: int
    default_retrieval_top_k: int


def interface_catalog(adapters: Mapping[str, SourceAdapter]) -> InterfaceCatalog:
    """Show only capabilities backed by an enabled, instantiated adapter."""

    sources = load_source_configuration()
    search = load_search_defaults()
    budgets = load_budget_policy()
    rubric = json.loads(DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8"))
    ready = {
        provider_id: definition
        for provider_id, definition in sources.providers.items()
        if definition.enabled and provider_id in adapters
    }
    source_types = {source_type for definition in ready.values() for source_type in definition.emits}
    content_types = {
        content_type for definition in ready.values() for content_type in definition.capabilities
    } & set(search.content_types)
    tiers = {
        sources.source_types[source_type].evidence_tier.value for source_type in source_types
    }
    return InterfaceCatalog(
        domains=list(sources.domains),
        providers=list(ready),
        source_types=sorted(source_types),
        content_types=sorted(content_types),
        languages=["en", "de", "fr", "es"] if any(
            provider.supports_language for provider in ready.values()
        ) else [],
        evidence_tiers=sorted(tiers),
        search_presets=list(search.presets),
        preset_limits={
            name: {
                "max_queries": preset.max_queries,
                "max_results_per_query": preset.max_results_per_query,
                "max_sources": preset.max_sources,
            }
            for name, preset in search.presets.items()
        },
        rubric_presets=list(rubric["presets"]),
        criteria_labels={key: value["label"] for key, value in rubric["criteria"].items()},
        rubric_weights=rubric["presets"],
        default_rubric=rubric["default_preset"],
        max_queries=search.hard_limits.max_queries,
        max_results_per_query=search.hard_limits.max_results_per_query,
        max_sources=search.hard_limits.max_sources,
        max_elapsed_seconds=budgets.ceilings.max_elapsed_seconds,
        default_elapsed_seconds=budgets.defaults.max_elapsed_seconds,
        max_model_tokens=budgets.ceilings.max_model_tokens,
        default_model_tokens=budgets.defaults.max_model_tokens,
        max_source_bytes=budgets.ceilings.max_source_bytes,
        default_source_bytes=budgets.defaults.max_source_bytes,
        max_pdf_pages=budgets.ceilings.max_pdf_pages,
        default_pdf_pages=budgets.defaults.max_pdf_pages,
        max_estimated_cost_usd=budgets.ceilings.max_estimated_cost_usd,
        max_context_chunks=rubric["retrieval"]["max_context_chunks"],
        default_retrieval_top_k=rubric["retrieval"]["top_k_per_criterion"],
    )


def submitted_from_controls(
    values: Mapping[str, object],
    explicit_paths: set[str],
    *,
    prompt: str = "",
    draft: PromptInterpretationDraft | None = None,
    accepted_paths: set[str] | None = None,
    acknowledged_issues: set[int] | None = None,
) -> SubmittedRunConfiguration:
    """Combine edited controls with confirmed deductions; never apply a draft alone."""

    if prompt.strip() and draft is None:
        raise ValueError("prompt and instructions must be interpreted and reviewed first")
    if draft is not None and prompt.strip() != draft.original_prompt.strip():
        raise ValueError("prompt changed since interpretation; draft it again")
    unknown = explicit_paths - values.keys()
    if unknown:
        raise ValueError(f"explicit fields have no values: {sorted(unknown)}")
    chosen = {path: values[path] for path in explicit_paths if values[path] is not None}
    if draft is not None:
        reviewed = confirm_interpretation(draft, InterpretationReview(
            accepted_paths=accepted_paths or set(),
            overrides={path: value for path, value in chosen.items() if not path.startswith("budgets.")},
            acknowledged_issues=acknowledged_issues or set(),
        ))
        data = reviewed.model_dump(mode="python")
        data["budgets"] = {path.partition(".")[2]: value for path, value in chosen.items()
                           if path.startswith("budgets.")}
        data["field_origins"].update({path: "explicit" for path in chosen if path.startswith("budgets.")})
        return SubmittedRunConfiguration.model_validate(data)

    sections: dict[str, dict[str, object]] = {
        "request": {}, "search": {}, "evaluation": {}, "budgets": {},
    }
    # Preview is a deliberate manual confirmation of visible required fields,
    # even if the user left their displayed defaults unchanged.
    for path in ("request.domain", "request.time_limit_days"):
        if path in values and values[path] is not None:
            chosen.setdefault(path, values[path])
    for path, value in chosen.items():
        section, separator, field = path.partition(".")
        if not separator or section not in sections or not field:
            raise ValueError(f"unknown control path: {path!r}")
        sections[section][field] = value
    return SubmittedRunConfiguration.model_validate({
        **sections,
        "field_origins": {path: "explicit" for path in chosen},
    })
