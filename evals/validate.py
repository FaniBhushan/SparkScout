"""Validate evaluation dataset structure without running the AI system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EVALS_DIR = Path(__file__).resolve().parent


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate() -> list[str]:
    errors: list[str] = []
    manifest = load_json(EVALS_DIR / "manifest.json")
    seen_case_ids: set[str] = set()

    split_entries = (
        ("development", manifest["development_cases"]),
        ("held_out", manifest["held_out_cases"]),
    )
    for expected_split, entries in split_entries:
        for relative_case_path in entries:
            case_path = EVALS_DIR / relative_case_path
            if not case_path.is_file():
                errors.append(f"missing case file: {relative_case_path}")
                continue

            case = load_json(case_path)
            case_id = case.get("case_id")
            if case_id in seen_case_ids:
                errors.append(f"duplicate case_id: {case_id}")
            seen_case_ids.add(case_id)
            if case.get("split") != expected_split:
                errors.append(f"{case_id}: expected split {expected_split!r}")

            fixture_set = case.get("fixture_set")
            if fixture_set is None:
                continue

            fixture_dir = EVALS_DIR / "frozen_sources" / fixture_set
            sources_path = fixture_dir / "sources.json"
            chunks_path = fixture_dir / "chunks.json"
            if not sources_path.is_file() or not chunks_path.is_file():
                errors.append(f"{case_id}: incomplete fixture set {fixture_set!r}")
                continue

            sources = load_json(sources_path)
            chunks = load_json(chunks_path)
            source_ids = {record["source_id"] for record in sources}
            chunk_source_ids = {chunk["source_id"] for chunk in chunks}
            if unknown := chunk_source_ids - source_ids:
                errors.append(f"{case_id}: chunks reference unknown sources {sorted(unknown)}")

            relevant_ids = set(case.get("expected", {}).get("relevant_source_ids", []))
            if unknown := relevant_ids - source_ids:
                errors.append(f"{case_id}: gold labels reference unknown sources {sorted(unknown)}")

            for record in sources:
                note = record.get("license_access_note", "").lower()
                if "synthetic fixture" not in note:
                    errors.append(f"{case_id}: {record['source_id']} is not labeled synthetic")

    return errors


if __name__ == "__main__":
    validation_errors = validate()
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Evaluation dataset is structurally valid.")
