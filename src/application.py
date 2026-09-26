"""Assemble one research run independently of its CLI or future UI."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from src.adapters.base import SourceAdapter
from src.budgets import BudgetExceeded, BudgetedLLMClient, BudgetedSourceAdapter, RunBudget
from src.finalization import ProposalCoverageError, finalize_proposals
from src.llm import (
    LLMCandidateGenerator,
    LLMCandidateJudge,
    LLMLibraryQueryPlanner,
    LLMProposalWriter,
    LLMScoutQueryPlanner,
)
from src.llm.client import LLMClient, ModelPricing
from src.models import (
    EvaluationSelection,
    InputRequest,
    OrchestrationResult,
    PreparedRun,
    SearchConfiguration,
    SearchLimits,
    SubmittedRunConfiguration,
)
from src.observability import RunTracer
from src.orchestration.coordinator import Orchestrator, RunMode
from src.preflight import prepare_run
from src.retrieval import InMemoryRetriever
from src.workers.critic_worker import CriticWorker
from src.workers.library_worker import LibraryWorker
from src.workers.scout_worker import ScoutWorker


@dataclass(frozen=True)
class LLMOutputLimits:
    """Per-call output caps applied within the separate run-wide token budget."""

    scout_queries: int = 1000
    candidate_generation: int = 3000
    library_queries: int = 1000
    critic_assessment: int = 3000
    final_proposal: int = 4000

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("all LLM output limits must be positive")


def _redact_uploaded_text(data: dict[str, object], prepared: PreparedRun) -> None:
    """Keep receipt IDs and hashes but omit uploaded passages from exportable results."""

    upload_ids = {
        f"upload-{digest[:20]}" for digest in prepared.search.upload_sha256.values()
    }
    if not upload_ids:
        return
    for section in ("scout", "library"):
        for source in data[section]["sources"]:
            if source["source_id"] in upload_ids:
                source["abstract_or_snippet"] = None
    for source in data["source_manifest"]:
        if source["source_id"] in upload_ids:
            source["abstract_or_snippet"] = None
    for chunk in data["library"]["chunks"]:
        if chunk["source_id"] in upload_ids:
            chunk["text"] = "[Uploaded text omitted from exported result]"
            chunk["text_redacted"] = True


async def run_research(
    request: InputRequest,
    llm_client: LLMClient,
    available_adapters: Mapping[str, SourceAdapter],
    *,
    search_preset: str = "balanced",
    rubric_preset: str | None = None,
    requested_limits: SearchLimits | None = None,
    weights: Mapping[str, int] | None = None,
    output_limits: LLMOutputLimits = LLMOutputLimits(),
    mode: RunMode = "sequential",
    tracer: RunTracer | None = None,
    model_pricing: ModelPricing | None = None,
) -> OrchestrationResult:
    """Preserve the existing entry point through the shared preflight path."""

    submitted = SubmittedRunConfiguration(
        request=request,
        search=SearchConfiguration(
            preset=search_preset,
            source_policy=request.source_policy,
            limits=requested_limits,
        ),
        evaluation=EvaluationSelection(rubric_preset=rubric_preset, weights=weights),
    )
    prepared = prepare_run(submitted, available_adapters)
    return await run_prepared_research(
        prepared,
        llm_client,
        available_adapters,
        output_limits=output_limits,
        mode=mode,
        tracer=tracer,
        model_pricing=model_pricing,
    )


async def run_prepared_research(
    prepared: PreparedRun,
    llm_client: LLMClient,
    available_adapters: Mapping[str, SourceAdapter],
    *,
    output_limits: LLMOutputLimits = LLMOutputLimits(),
    mode: RunMode = "sequential",
    tracer: RunTracer | None = None,
    model_pricing: ModelPricing | None = None,
) -> OrchestrationResult:
    """Run only the reviewed effective configuration, without resolving it again."""

    # Revalidate a potentially mutable nested model before any external work.
    prepared = PreparedRun.model_validate(prepared.model_dump(mode="python"))
    selected = {provider.provider_id for provider in prepared.search.providers}
    missing = selected - set(available_adapters)
    if missing:
        raise ValueError(f"prepared providers are no longer available: {sorted(missing)}")
    upload_adapter = available_adapters.get("user_upload")
    actual_uploads = getattr(upload_adapter, "manifest", []) if upload_adapter else []
    if prepared.submitted.search.uploads != actual_uploads:
        raise ValueError("uploaded files changed after configuration review")
    if prepared.search.upload_sha256 != {
        item.filename: item.sha256 for item in actual_uploads
    }:
        raise ValueError("resolved upload hashes do not match reviewed files")
    pricing = model_pricing if model_pricing is not None else getattr(llm_client, "pricing", None)
    budget = RunBudget(prepared.budgets, pricing=pricing, tracer=tracer)
    run_client = BudgetedLLMClient(llm_client, budget)
    run_adapters = {
        provider_id: BudgetedSourceAdapter(available_adapters[provider_id], provider_id, budget)
        for provider_id in selected
    }
    request = prepared.request
    search = prepared.search
    rubric = prepared.evaluation

    scout = ScoutWorker(
        run_adapters,
        LLMScoutQueryPlanner(
            run_client, max_output_tokens=output_limits.scout_queries, tracer=tracer
        ),
        LLMCandidateGenerator(
            run_client, max_output_tokens=output_limits.candidate_generation, tracer=tracer
        ),
        tracer=tracer,
    )
    library = LibraryWorker(
        run_adapters,
        LLMLibraryQueryPlanner(
            run_client, max_output_tokens=output_limits.library_queries, tracer=tracer
        ),
        tracer=tracer,
    )
    # The coordinator replaces this empty template index with Library chunks for each run.
    critic = CriticWorker(
        InMemoryRetriever([]),
        LLMCandidateJudge(
            run_client, max_output_tokens=output_limits.critic_assessment, tracer=tracer
        ),
        tracer=tracer,
    )
    writer = LLMProposalWriter(
        run_client, max_output_tokens=output_limits.final_proposal, tracer=tracer
    )
    async def execute() -> OrchestrationResult:
        result = await Orchestrator(scout, library, critic, tracer=tracer).run(
            request, search, rubric, mode=mode
        )
        try:
            return await finalize_proposals(request, result, writer)
        except ProposalCoverageError as error:
            # Evidence insufficiency is a reportable outcome, not a fabricated draft.
            data = result.model_dump(mode="python")
            data["status"] = "insufficient_coverage"
            data["warnings"] = [*result.warnings, str(error)]
            data["completed_at"] = datetime.now(timezone.utc)
            return OrchestrationResult.model_validate(data)

    try:
        finalized = await asyncio.wait_for(execute(), timeout=prepared.budgets.max_elapsed_seconds)
    except asyncio.TimeoutError as error:
        raise BudgetExceeded("run time budget exhausted") from error
    if tracer:
        tracer.event(
            "application", "run_finalized", task_id=finalized.run_id,
            count=len(finalized.final_proposals),
        )
    data = finalized.model_dump(mode="python")
    _redact_uploaded_text(data, prepared)
    data["prepared_run"] = prepared.model_dump(mode="python")
    data["budget_usage"] = budget.snapshot()
    return OrchestrationResult.model_validate(data)
