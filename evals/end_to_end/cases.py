"""Load explicitly selected development cases and fingerprint their inputs."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.models import InputRequest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ("robotics-agriculture-01", "software-accessibility-01", "medicine-public-data-01")


class ResearchCase(BaseModel):
    """Research starts at the structured request; interpretation is a separate eval."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str
    case_id: str
    split: str
    description: str
    prompt: str
    expected_request: InputRequest | None
    fixture_set: str | None
    expected: dict


def load_cases(case_ids: list[str]) -> list[tuple[ResearchCase, str]]:
    """Restrict selection to manifest-listed development research cases."""
    manifest = json.loads((ROOT / "manifest.json").read_text())
    available = {}
    for relative in manifest["development_cases"]:
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("case path escapes evaluation directory")
        raw = path.read_bytes()
        case = ResearchCase.model_validate_json(raw)
        available[case.case_id] = (case, raw)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")
    loaded = []
    for case_id in case_ids:
        if case_id not in available:
            raise ValueError(f"unknown development case: {case_id}")
        case, raw = available[case_id]
        if case.expected_request is None or case.fixture_set is None:
            raise ValueError(f"{case_id} requires a prompt-interpretation evaluation")
        folder = (ROOT / "frozen_sources" / case.fixture_set).resolve()
        if folder.parent != ROOT / "frozen_sources":
            raise ValueError("invalid fixture directory")
        # Passage edits change evidence just as source edits do.
        digest = hashlib.sha256(
            raw + (folder / "sources.json").read_bytes() + (folder / "chunks.json").read_bytes()
        ).hexdigest()
        loaded.append((case, digest))
    return loaded
