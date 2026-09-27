"""Run with python -m evals.end_to_end; paid mode always requires a suite cap."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from uuid import uuid4

from src.runtime.budgets import BudgetedLLMClient, RunBudget
from src.testing.demo import OfflineDemoClient
from src.runtime.environment import load_local_environment
from src.guardrails import safe_error_message
from src.llm.client import ModelPricing, OpenAITextClient
from src.models import RunBudgetLimits

from .cases import DEFAULT_CASES, ROOT, load_cases
from .reports import write_report
from .runner import run_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    execution = parser.add_mutually_exclusive_group(required=True)
    execution.add_argument("--offline-demo", action="store_true")
    execution.add_argument("--model")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--mode", choices=["sequential", "parallel"], default="sequential")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint-root", type=Path, help="retain paid work for explicit resume")
    parser.add_argument("--resume", action="store_true", help="reuse matching case checkpoints")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--max-elapsed-seconds", type=float, default=900)
    parser.add_argument("--max-model-tokens", type=int, default=600000)
    parser.add_argument("--input-rate", type=float)
    parser.add_argument("--output-rate", type=float)
    args = parser.parse_args()
    if not isfinite(args.max_elapsed_seconds) or args.max_elapsed_seconds <= 0 or args.max_model_tokens <= 0:
        parser.error("suite time and token limits must be positive")
    if args.model and any(value is None or not isfinite(value) or value <= 0 for value in (
        args.max_cost_usd, args.input_rate, args.output_rate
    )):
        parser.error("paid mode requires positive finite --max-cost-usd, --input-rate and --output-rate")
    cases = load_cases(args.case_ids or list(DEFAULT_CASES))
    destination = args.output or ROOT / "reports" / uuid4().hex
    if destination.exists():
        parser.error("output directory already exists; choose a new directory")
    checkpoint_root = args.checkpoint_root
    if args.resume and checkpoint_root is None:
        parser.error("--resume requires --checkpoint-root")
    if args.model and checkpoint_root is None:
        checkpoint_root = destination.with_name(destination.name + "-checkpoints")
    pricing = ModelPricing(args.input_rate, args.output_rate) if args.model else None
    budget = None
    if args.model:
        load_local_environment()
        client = OpenAITextClient(args.model, pricing=pricing, max_retries=0)
        budget = RunBudget(RunBudgetLimits(max_elapsed_seconds=args.max_elapsed_seconds,
                                          max_model_tokens=args.max_model_tokens,
                                          max_estimated_cost_usd=args.max_cost_usd), pricing=pricing)
        run_client = BudgetedLLMClient(client, budget)
    else:
        client = run_client = OfflineDemoClient()

    async def execute():
        try:
            return await run_cases(cases, run_client, mode=args.mode, pricing=pricing,
                                   checkpoint_root=checkpoint_root, resume=args.resume)
        finally:
            if args.model:
                await client.sdk_client.close()

    records = asyncio.run(execute())
    report = {
        "schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "execution": "paid_model" if args.model else "offline_demo", "model": args.model,
        "resolved_models": sorted(client.resolved_models) if args.model else [],
        "checkpoint_root": str(checkpoint_root) if checkpoint_root else None,
        "mode": args.mode, "fixture_kind": "synthetic", "scope": "structured_request_to_proposals",
        "dataset_version": json.loads((ROOT / "manifest.json").read_text())["dataset_version"],
        "prompt_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted((ROOT.parent / "src/prompts").glob("*.md"))},
        "suite_budget_usage": budget.snapshot() if budget else None,
        "max_cost_usd": args.max_cost_usd,
        "max_elapsed_seconds": args.max_elapsed_seconds,
        "max_model_tokens": args.max_model_tokens,
        "pricing_per_million": {"input": args.input_rate, "output": args.output_rate},
        "cases": records,
    }
    write_report(destination, report)
    print(f"Report: {destination / 'summary.md'}")
    print(f"Passed: {sum(record['outcome'] == 'passed' for record in records)}/{len(records)}")
    return 0 if all(record["outcome"] == "passed" for record in records) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(safe_error_message(error)) from None
