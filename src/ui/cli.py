"""Command-line interface; run with ``python -m src.ui.cli``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from src.adapters import build_available_adapters
from src.adapters.user_upload import MAX_FILE_BYTES
from src.application.service import run_prepared_research
from src.testing.demo import OfflineDemoClient
from src.runtime.environment import load_local_environment
from src.guardrails import emit_advisories, safe_error_message
from src.application.interpretation import confirm_interpretation
from src.llm.client import ModelPricing, OpenAITextClient
from src.llm.request_interpreter import LLMRequestInterpreter
from src.models import (
    EvaluationSelection,
    InputRequest,
    InterpretationReview,
    PromptInterpretationDraft,
    SearchConfiguration,
    SubmittedRunConfiguration,
)
from src.observability import RunTracer
from src.application.preflight import prepare_run


def _submitted_input(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> SubmittedRunConfiguration:
    """Keep legacy case/request inputs while accepting the shared full contract."""

    if args.config is not None:
        return SubmittedRunConfiguration.model_validate_json(
            args.config.read_text(encoding="utf-8")
        )
    if args.case is not None:
        if args.fixture_set is not None or args.live:
            parser.error("--case supplies its own frozen fixture and cannot use --live")
        case = json.loads(args.case.read_text(encoding="utf-8"))
        request = InputRequest.model_validate(case["expected_request"])
    else:
        request = InputRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    return SubmittedRunConfiguration(
        request=request,
        search=SearchConfiguration(
            preset=args.search_preset, source_policy=request.source_policy,
        ),
        evaluation=EvaluationSelection(rubric_preset=args.rubric_preset),
    )


def main(argv: list[str] | None = None) -> int:
    load_local_environment()
    parser = argparse.ArgumentParser(description="Run ScoutSpark or draft a reviewed request")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--case", type=Path, help="evaluation case JSON with a fixture set")
    inputs.add_argument("--request", type=Path, help="structured InputRequest JSON")
    inputs.add_argument("--config", type=Path, help="full SubmittedRunConfiguration JSON")
    inputs.add_argument("--prompt-file", type=Path, help="draft configuration from plain text")
    inputs.add_argument("--draft-file", type=Path, help="saved PromptInterpretationDraft JSON")
    parser.add_argument("--review-file", type=Path, help="InterpretationReview JSON for --draft-file")
    parser.add_argument("--fixture-set", help="synthetic source fixture for request/config/prompt")
    parser.add_argument("--live", action="store_true", help="use credential-ready live adapters")
    parser.add_argument("--upload", type=Path, action="append", default=[],
                        help="run-scoped .txt, .md, or .pdf document; repeat for multiple files")
    parser.add_argument("--confirm-upload-rights", action="store_true",
                        help="confirm rights to use uploads; text may reach the model and inform results")
    parser.add_argument("--upload-language", choices=("en", "de", "fr", "es"), default="en",
                        help="declared language for all uploaded documents")
    parser.add_argument("--model", help="OpenAI model ID; not needed for --offline-demo")
    parser.add_argument("--offline-demo", action="store_true",
                        help="use a deterministic local model with frozen sources")
    parser.add_argument("--mode", choices=("sequential", "parallel"), default="sequential")
    parser.add_argument("--trace-dir", type=Path, default=Path("runs"),
                        help="directory for structured, text-free run traces")
    parser.add_argument("--checkpoint-dir", type=Path, help="opt-in local run checkpoint directory")
    parser.add_argument("--resume", action="store_true", help="reuse valid stages and preserve spent budget")
    parser.add_argument("--frozen-replay", action="store_true", help="resume using saved stages only")
    parser.add_argument("--retry-once", action="store_true", help="retry transient failures once within budgets")
    parser.add_argument("--search-preset", default="balanced", help="legacy --case/--request only")
    parser.add_argument("--rubric-preset", default="balanced", help="legacy --case/--request only")
    parser.add_argument("--input-rate", type=float, help="trusted USD per million input tokens")
    parser.add_argument("--output-rate", type=float, help="trusted USD per million output tokens")
    args = parser.parse_args(argv)
    if (args.resume or args.frozen_replay) and args.checkpoint_dir is None:
        parser.error("resume/replay requires --checkpoint-dir")
    if args.prompt_file and args.checkpoint_dir:
        parser.error("checkpointing applies to research, after prompt review")

    if (args.review_file is None) != (args.draft_file is None):
        parser.error("--draft-file and --review-file must be supplied together")
    if args.live and args.fixture_set is not None:
        parser.error("choose --live or --fixture-set, not both")
    if args.offline_demo and args.live:
        parser.error("--offline-demo requires a frozen fixture, not --live")
    if args.offline_demo and args.upload:
        parser.error("--offline-demo uses synthetic fixtures, not uploaded documents")
    if args.offline_demo and args.prompt_file is not None:
        parser.error("prompt interpretation requires an OpenAI model, not --offline-demo")
    if not args.offline_demo and not args.model:
        parser.error("--model is required unless --offline-demo is selected")
    if (args.input_rate is None) != (args.output_rate is None):
        parser.error("--input-rate and --output-rate must be supplied together")
    pricing = (
        ModelPricing(args.input_rate, args.output_rate)
        if args.input_rate is not None else None
    )

    fixture_set = args.fixture_set
    if args.case is not None:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        fixture_set = case["fixture_set"]
    if fixture_set is None and not args.live and not args.upload:
        parser.error("choose --fixture-set, --live, or --upload")
    if args.upload and not args.confirm_upload_rights:
        parser.error("--upload requires --confirm-upload-rights")
    upload_files = []
    for path in args.upload:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            parser.error(f"upload must be an existing file of at most {MAX_FILE_BYTES} bytes: {path}")
        upload_files.append((path.name, path.read_bytes(), args.upload_language))
    adapters = build_available_adapters(
        fixture_set=fixture_set, include_live=args.live,
        upload_files=upload_files, upload_rights_confirmed=args.confirm_upload_rights,
    )
    if not adapters:
        parser.error("no source adapters are ready")

    if args.prompt_file is not None:
        if not os.getenv("OPENAI_API_KEY"):
            parser.error("OPENAI_API_KEY is required to interpret a prompt")
        client = OpenAITextClient(args.model, pricing=pricing)
        prompt = args.prompt_file.read_text(encoding="utf-8")
        draft = asyncio.run(LLMRequestInterpreter(client).draft(prompt, adapters))
        print(draft.model_dump_json(indent=2))
        return 0
    elif args.draft_file is not None:
        draft = PromptInterpretationDraft.model_validate_json(
            args.draft_file.read_text(encoding="utf-8")
        )
        review = InterpretationReview.model_validate_json(
            args.review_file.read_text(encoding="utf-8")
        )
        submitted = confirm_interpretation(draft, review)
        client = None
    else:
        submitted = _submitted_input(args, parser)
        client = None

    upload_adapter = adapters.get("user_upload")
    if upload_adapter is not None and not submitted.search.uploads:
        submitted = SubmittedRunConfiguration.model_validate({
            **submitted.model_dump(mode="python"),
            "search": {
                **submitted.search.model_dump(mode="python"),
                "uploads": [item.model_dump(mode="python") for item in upload_adapter.manifest],
            },
            "field_origins": {**submitted.field_origins, "search.uploads": "explicit"},
        })

    prepared = prepare_run(submitted, adapters)
    emit_advisories(prepared.warnings)
    if args.offline_demo:
        client = OfflineDemoClient()
    else:
        if not os.getenv("OPENAI_API_KEY"):
            parser.error("OPENAI_API_KEY is required for model calls")
        if client is None:
            client = OpenAITextClient(args.model, pricing=pricing)
    tracer = RunTracer(uuid4().hex, log_dir=args.trace_dir)
    try:
        result = asyncio.run(run_prepared_research(
            prepared, client, adapters, mode=args.mode, tracer=tracer,
            checkpoint_dir=args.checkpoint_dir, resume=args.resume or args.frozen_replay,
            frozen=args.frozen_replay, retry_limit=int(args.retry_once),
        ))
    finally:
        tracer.close()
    print(f"Trace: {tracer.trace_path}", file=sys.stderr)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(safe_error_message(error), file=sys.stderr)
        raise SystemExit(2) from None
