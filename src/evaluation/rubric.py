"""Load a preset or exact user weights for candidate scoring."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from src.models.evaluation_configuration import EvaluationConfiguration


DEFAULT_RUBRIC_PATH = Path(__file__).resolve().parents[2] / "config" / "rubric.json"


def load_evaluation_configuration(
    preset: str | None = None,
    *,
    weights: Mapping[str, int] | None = None,
    path: Path = DEFAULT_RUBRIC_PATH,
) -> EvaluationConfiguration:
    """Resolve a preset or a complete set of user-supplied criterion weights."""

    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)

    definitions = catalog["criteria"]
    if weights is None:
        selected_preset = preset or catalog["default_preset"]
        try:
            selected_weights = catalog["presets"][selected_preset]
        except KeyError as error:
            raise ValueError(f"unknown rubric preset: {selected_preset}") from error
    else:
        selected_preset = "custom"
        selected_weights = dict(weights)

    if set(selected_weights) != set(definitions):
        raise ValueError("weights must provide exactly the configured criteria")

    return EvaluationConfiguration(
        preset=selected_preset,
        criteria={
            criterion_id: {**definition, "weight": selected_weights[criterion_id]}
            for criterion_id, definition in definitions.items()
        },
        hard_gates=catalog["hard_gates"],
        retrieval_top_k=catalog["retrieval"]["top_k_per_criterion"],
        max_context_chunks=catalog["retrieval"]["max_context_chunks"],
        max_context_tokens=catalog["retrieval"]["max_context_tokens"],
    )
