"""Run one explicitly configured live demo and save its result plus trace link."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

from src.adapters import build_available_adapters
from src.application.service import run_prepared_research
from src.runtime.environment import load_local_environment
from src.llm.client import ModelPricing, OpenAITextClient
from src.models import SubmittedRunConfiguration
from src.observability import RunTracer
from src.application.preflight import prepare_run
from src.guardrails import safe_error_message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new report directory")
    parser.add_argument("--model", required=True)
    parser.add_argument("--input-rate", type=float, required=True)
    parser.add_argument("--output-rate", type=float, required=True)
    parser.add_argument("--trace-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output directory already exists; choose a new path")
    load_local_environment()
    adapters = build_available_adapters(include_live=True)
    submitted = SubmittedRunConfiguration.model_validate_json(
        args.config.read_text(encoding="utf-8")
    )
    prepared = prepare_run(submitted, adapters)
    provider_ids = {provider.provider_id for provider in prepared.search.providers}
    available_types = {kind for provider in prepared.search.providers for kind in provider.source_types}
    if "tavily" not in provider_ids or "web_article" not in available_types:
        parser.error("live demo config must resolve Tavily and web_article")

    pricing = ModelPricing(args.input_rate, args.output_rate)
    client = OpenAITextClient(args.model, pricing=pricing, max_retries=0)
    tracer = RunTracer(uuid4().hex, log_dir=args.trace_dir)
    started = monotonic()
    args.output.mkdir(parents=True)

    async def execute():
        try:
            return await run_prepared_research(
                prepared, client, adapters, mode="sequential", tracer=tracer,
                model_pricing=pricing,
                checkpoint_dir=args.output / "checkpoint",
            )
        finally:
            await client.sdk_client.close()

    result = None
    error = None
    try:
        result = asyncio.run(execute())
    except Exception as failure:
        error = {"type": type(failure).__name__, "message": safe_error_message(failure)}
    finally:
        tracer.close()
    elapsed = round(monotonic() - started, 3)
    report = {
        "schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "execution": "live_model", "model": args.model, "mode": "sequential",
        "config_path": str(args.config),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "trace_path": str(tracer.trace_path), "duration_seconds": elapsed,
        "pricing_per_million": {"input": args.input_rate, "output": args.output_rate},
        "prepared_run": prepared.model_dump(mode="json"),
        "result": result.model_dump(mode="json") if result else None,
        "error": error,
    }
    (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {args.output / 'results.json'}")
    print(f"Trace: {tracer.trace_path}")
    if error:
        print(f"Run stopped: {error['type']}: {error['message']}")
        return 1
    print(f"Status: {result.status}; proposals: {len(result.final_proposals)}")
    print(f"Sources: {len(result.source_manifest)}; duration: {elapsed}s")
    cost = result.budget_usage.estimated_cost_usd if result.budget_usage else None
    print(f"Estimated cost: {cost}")
    return 0 if result.final_proposals else 1


if __name__ == "__main__":
    raise SystemExit(main())
