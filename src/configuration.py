"""Load and validate operator configuration files."""

from __future__ import annotations

import json
from pathlib import Path

from src.models import SearchDefaults, SourceConfiguration


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def load_source_configuration(path: Path = CONFIG_DIR / "sources.json") -> SourceConfiguration:
    """Load the approved source type, provider, and domain registry."""

    return SourceConfiguration.model_validate_json(path.read_text(encoding="utf-8"))


def load_search_defaults(path: Path = CONFIG_DIR / "search_defaults.json") -> SearchDefaults:
    """Load search presets and ensure none exceed operator hard limits."""

    data = json.loads(path.read_text(encoding="utf-8"))
    return SearchDefaults.model_validate(data)
