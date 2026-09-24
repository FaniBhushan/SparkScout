"""Minimal frozen-fixture entry point for a structured research request."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from src.adapters import FrozenFixtureAdapter
from src.application import run_research
from src.llm.client import OpenAITextClient
from src.models import InputRequest


def _load_input(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[InputRequest, str]:
    """Read either a frozen evaluation case or a standalone request JSON file."""

    if args.case is not None:
        if args.fixture_set is not None:
            parser.error("--fixture-set is only used with --request")
        case = json.loads(args.case.read_text(encoding="utf-8"))
        return InputRequest.model_validate(case["expected_request"]), case["fixture_set"]

    if args.fixture_set is None:
        parser.error("--fixture-set is required with --request")
    request = InputRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    return request, args.fixture_set


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ScoutSpark against synthetic frozen sources")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--case", type=Path, help="evaluation case JSON containing expected_request")
    inputs.add_argument("--request", type=Path, help="structured InputRequest JSON")
    parser.add_argument("--fixture-set", help="frozen source directory name for --request")
    parser.add_argument("--model", required=True, help="OpenAI model ID to use for worker calls")
    parser.add_argument("--mode", choices=("sequential", "parallel"), default="sequential")
    parser.add_argument("--search-preset", default="balanced")
    parser.add_argument("--rubric-preset", default="balanced")
    args = parser.parse_args(argv)

    request, fixture_set = _load_input(args, parser)
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required for model calls")

    # Frozen mode deliberately registers no live search adapters.
    adapters = {"frozen_fixture": FrozenFixtureAdapter(fixture_set)}
    result = asyncio.run(
        run_research(
            request,
            OpenAITextClient(args.model),
            adapters,
            search_preset=args.search_preset,
            rubric_preset=args.rubric_preset,
            mode=args.mode,
        )
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
