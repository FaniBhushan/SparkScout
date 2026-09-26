"""Versioned prompt templates for model-backed worker implementations."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from src.models import (
    CandidateAssessment,
    CandidateIdea,
    PromptSuggestions,
    ProposalDraft,
    ScoutQuery,
    SourceQuery,
)


PromptName = Literal[
    "scout_query_planner",
    "scout_candidate_generator",
    "library_query_planner",
    "critic_candidate_judge",
    "final_proposal",
    "request_interpreter",
]
PROMPT_DIR = Path(__file__).resolve().parent
_PROMPTS: dict[PromptName, tuple[str, TypeAdapter]] = {
    "scout_query_planner": ("scout_query_planner.md", TypeAdapter(list[ScoutQuery])),
    "scout_candidate_generator": ("scout_candidate_generator.md", TypeAdapter(list[CandidateIdea])),
    "library_query_planner": ("library_query_planner.md", TypeAdapter(list[SourceQuery])),
    "critic_candidate_judge": ("critic_candidate_judge.md", TypeAdapter(CandidateAssessment)),
    "final_proposal": ("final_proposal.md", TypeAdapter(ProposalDraft)),
    "request_interpreter": ("request_interpreter.md", TypeAdapter(PromptSuggestions)),
}
_PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def render_prompt(name: PromptName, **context: object) -> str:
    """Load a prompt and insert JSON inputs plus the contract-derived output schema."""

    try:
        filename, output_type = _PROMPTS[name]
    except KeyError:
        raise ValueError(f"unknown prompt template: {name!r}") from None

    values = dict(context)
    values["OUTPUT_SCHEMA"] = output_type.json_schema()
    template = (PROMPT_DIR / filename).read_text(encoding="utf-8")
    placeholders = set(_PLACEHOLDER.findall(template))
    missing = placeholders - values.keys()
    extra = values.keys() - placeholders
    if missing or extra:
        raise ValueError(
            f"prompt {name!r} context mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    serialized = {
        key: json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
        for key, value in values.items()
    }
    return _PLACEHOLDER.sub(lambda match: serialized[match.group(1)], template)


def parse_model_output(name: PromptName, output: str | bytes | object) -> object:
    """Validate a model response against the Pydantic contract for its prompt."""

    try:
        _, output_type = _PROMPTS[name]
    except KeyError:
        raise ValueError(f"unknown prompt template: {name!r}") from None
    if isinstance(output, (str, bytes)):
        return output_type.validate_json(output, strict=True)
    return output_type.validate_python(output, strict=True)


def _json_default(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize prompt input of type {type(value).__name__}")


__all__ = ["PromptName", "parse_model_output", "render_prompt"]
