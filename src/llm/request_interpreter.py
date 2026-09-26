"""One bounded model call to draft, but never execute, a run configuration."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from src.adapters.base import SourceAdapter
from src.configuration import load_search_defaults, load_source_configuration
from src.evaluation.rubric import DEFAULT_RUBRIC_PATH
from src.guardrails import check_privacy, emit_advisories, input_advisories
from src.llm.client import LLMClient
from src.llm.prompt_call import call_prompt
from src.models import (
    InterpretationIssue,
    PromptInterpretationDraft,
    PromptSuggestions,
    SearchDefaults,
    SourceConfiguration,
)
from src.observability import RunTracer


class LLMRequestInterpreter:
    """Produce reviewable suggestions only after an explicit draft action."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def draft(
        self,
        prompt: str,
        available_adapters: Mapping[str, SourceAdapter],
        *,
        sources: SourceConfiguration | None = None,
        defaults: SearchDefaults | None = None,
        tracer: RunTracer | None = None,
    ) -> PromptInterpretationDraft:
        """Warn on large input, bound output, and flag unavailable capabilities."""

        if not prompt.strip():
            raise ValueError("request text must not be empty")
        advisories = input_advisories(prompt)
        emit_advisories(advisories)
        sources = sources if sources is not None else load_source_configuration()
        defaults = defaults if defaults is not None else load_search_defaults()
        rubric = json.loads(DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8"))
        ready = {
            provider_id: definition
            for provider_id, definition in sources.providers.items()
            if definition.enabled and provider_id in available_adapters
        }
        catalog = {
            "domains": sources.domains,
            "source_types": sorted(sources.source_types),
            "ready_providers": {
                provider_id: {
                    "source_types": definition.emits,
                    "content_types": definition.capabilities,
                }
                for provider_id, definition in ready.items()
            },
            "search_presets": sorted(defaults.presets),
            "rubric_presets": sorted(rubric["presets"]),
            "rubric_criteria": sorted(rubric["criteria"]),
        }
        suggestions = await call_prompt(
            self.llm_client,
            "request_interpreter",
            {"CATALOG": catalog, "USER_PROMPT": prompt},
            max_output_tokens=1800,
            tracer=tracer,
        )
        assert isinstance(suggestions, PromptSuggestions)
        issues = list(suggestions.issues)

        def unsupported(path: str, value: str) -> None:
            issues.append(InterpretationIssue(
                kind="unsupported", path=path,
                message=f"{value!r} is not available in this run",
            ))

        domain = suggestions.request.domain
        if domain and re.sub(r"[\s-]+", "_", domain.strip().casefold()) not in sources.domains:
            issues.append(InterpretationIssue(
                kind="ambiguous", path="request.domain",
                message="This domain needs an explicit Other-domain opt-in",
            ))
        if suggestions.search.preset and suggestions.search.preset not in defaults.presets:
            unsupported("search.preset", suggestions.search.preset)
        if suggestions.evaluation.rubric_preset and suggestions.evaluation.rubric_preset not in rubric["presets"]:
            unsupported("evaluation.rubric_preset", suggestions.evaluation.rubric_preset)
        if suggestions.evaluation.weights is not None and set(suggestions.evaluation.weights) != set(rubric["criteria"]):
            issues.append(InterpretationIssue(
                kind="unsupported", path="evaluation.weights",
                message="Weights must cover every configured criterion",
            ))
        for provider_id in suggestions.search.provider_ids or []:
            if provider_id not in ready:
                unsupported("search.provider_ids", provider_id)
        ready_content = {item for definition in ready.values() for item in definition.capabilities}
        for content_type in suggestions.search.content_types or []:
            if content_type not in ready_content or content_type not in defaults.content_types:
                unsupported("search.content_types", content_type)
        policy = suggestions.search.source_policy
        ready_types = {item for definition in ready.values() for item in definition.emits}
        ready_tiers = {
            sources.source_types[item].evidence_tier for item in ready_types
        }
        for tier in suggestions.search.evidence_tiers or []:
            if tier not in ready_tiers:
                unsupported("search.evidence_tiers", tier.value)
        if policy is not None:
            requested = (
                set(policy.include_types) | set(policy.required_types)
                | set(policy.max_records_by_type)
            )
            for source_type in sorted(requested - ready_types):
                unsupported("search.source_policy", source_type)
        for path in suggestions.uncertain_paths:
            if path not in _suggested_paths(suggestions):
                issues.append(InterpretationIssue(
                    kind="ambiguous", path=path,
                    message="The model marked an absent or unknown suggestion as uncertain",
                ))
        return PromptInterpretationDraft(
            original_prompt=prompt, suggestions=suggestions, issues=issues,
            warnings=list(dict.fromkeys([*advisories, *check_privacy(suggestions)])),
        )


def _suggested_paths(suggestions: PromptSuggestions) -> set[str]:
    """Use only populated top-level contract fields as reviewable selections."""

    return {
        f"{section}.{field}"
        for section in ("request", "search", "evaluation")
        for field, value in getattr(suggestions, section).model_dump(exclude_unset=True).items()
        if value is not None
    }
