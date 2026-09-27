"""Assemble one research run independently of its CLI or future UI."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from src.adapters.base import SourceAdapter
from src.runtime.budgets import BudgetExceeded, BudgetedLLMClient, BudgetedSourceAdapter, RunBudget
from src.application.finalization import ProposalCoverageError, finalize_proposals
from src.guardrails import check_privacy, emit_advisories, input_advisories
from src.llm import (
    LLMCandidateGenerator,
    LLMCandidateJudge,
    LLMLibraryQueryPlanner,
    LLMProposalWriter,
    LLMScoutQueryPlanner,
)
from src.llm.client import LLMClient, ModelPricing
from src.llm.proposal_verifier import LLMProposalVerifier
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
from src.application.preflight import prepare_run
from src.retrieval import InMemoryRetriever
from src.workers.critic_worker import CriticWorker
from src.workers.library_worker import LibraryWorker
from src.workers.scout_worker import ScoutWorker
from src.persistence import RunStore
from src.persistence.identity import run_identity
from src.persistence.workers import CheckpointWorker, CheckpointWriter, CheckpointVerifier
from src.application.recovery import recover_empty_result


@dataclass(frozen=True)
class LLMOutputLimits:
    """Per-call output caps applied within the separate run-wide token budget."""

    scout_queries: int = 1000
    candidate_generation: int = 3000
    library_queries: int = 1000
    critic_assessment: int = 3000
    final_proposal: int = 4000
    proposal_verification: int = 2000

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
    for proposal in data["final_proposals"]:
        audit = proposal.get("evidence_audit")
        if audit:
            # Quotes may contain uploaded text even when Library chunks have
            # already been redacted. Keep verdicts but omit all audit excerpts.
            for verdict in [*audit["claims"], *audit["dependencies"],
                            *audit["narrative_checks"].values()]:
                verdict["evidence_quotes"] = []
            audit["quotes_redacted"] = True


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
    checkpoint_dir=None,
    resume: bool = False,
    frozen: bool = False,
    retry_limit: int = 0,
) -> OrchestrationResult:
    """Optionally checkpoint one run; resume requires the identical reviewed inputs."""
    if retry_limit not in (0, 1):
        raise ValueError("retry_limit must be zero or one")
    if (resume or frozen) and checkpoint_dir is None:
        raise ValueError("resume/frozen replay requires a checkpoint directory")
    prepared = PreparedRun.model_validate(prepared.model_dump(mode="python"))
    pricing = model_pricing if model_pricing is not None else getattr(llm_client, "pricing", None)
    store = None
    if checkpoint_dir is not None:
        store = RunStore(checkpoint_dir,
                         run_identity(prepared, llm_client, available_adapters, output_limits,
                                      mode, pricing, retry_limit),
                         resume=resume, frozen=frozen, uploads=bool(prepared.submitted.search.uploads),
                         tracer=tracer)
    try:
        return await _execute_prepared_research(
            prepared, llm_client, available_adapters, output_limits=output_limits,
            mode=mode, tracer=tracer, model_pricing=pricing, store=store, retry_limit=retry_limit,
        )
    finally:
        if store:
            store.close()


async def _execute_prepared_research(
    prepared: PreparedRun,
    llm_client: LLMClient,
    available_adapters: Mapping[str, SourceAdapter],
    *,
    output_limits: LLMOutputLimits = LLMOutputLimits(),
    mode: RunMode = "sequential",
    tracer: RunTracer | None = None,
    model_pricing: ModelPricing | None = None,
    store: RunStore | None = None,
    retry_limit: int = 0,
) -> OrchestrationResult:
    """Run only the reviewed effective configuration, without resolving it again."""

    # Revalidate a potentially mutable nested model before any external work.
    prepared = PreparedRun.model_validate(prepared.model_dump(mode="python"))
    advisories = input_advisories(prepared.submitted)
    check_privacy(prepared)
    emit_advisories(advisories)
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
    budget.retry_limit = retry_limit
    if store:
        if store.state["budget"]:
            budget.restore(store.state["budget"])
        budget.checkpoint = store
        if store.read("normalized", prepared.configuration_checksum, PreparedRun) is None:
            store.write("normalized", prepared.configuration_checksum, prepared)
    run_client = BudgetedLLMClient(llm_client, budget)
    # Discovery/scoring should not consume the allowance needed to write and
    # verify a result. This is inside (not additional to) the user's token cap.
    research_client = BudgetedLLMClient(
        llm_client, budget, headroom_tokens=min(30000, prepared.budgets.max_model_tokens // 3))
    run_adapters = {
        provider_id: BudgetedSourceAdapter(available_adapters[provider_id], provider_id, budget)
        for provider_id in selected
    }
    request = prepared.request
    search = prepared.search
    rubric = prepared.evaluation

    generator = LLMCandidateGenerator(
        research_client, max_output_tokens=output_limits.candidate_generation, tracer=tracer
    )
    scout = ScoutWorker(
        run_adapters,
        LLMScoutQueryPlanner(
            run_client, max_output_tokens=output_limits.scout_queries, tracer=tracer
        ),
        generator,
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
            research_client, max_output_tokens=output_limits.critic_assessment, tracer=tracer
        ),
        tracer=tracer,
    )
    writer = LLMProposalWriter(
        run_client, max_output_tokens=output_limits.final_proposal, tracer=tracer
    )
    verifier = LLMProposalVerifier(
        run_client, max_output_tokens=output_limits.proposal_verification, tracer=tracer,
    )
    # Recovery may use the allowance initially protected from exploration, but
    # still leaves a smaller drafting reserve inside the same run-wide cap.
    recovery_client = BudgetedLLMClient(
        llm_client, budget, headroom_tokens=min(12000, prepared.budgets.max_model_tokens // 6))
    recovery_generator = LLMCandidateGenerator(
        recovery_client, max_output_tokens=output_limits.candidate_generation, tracer=tracer)
    recovery_critic = CriticWorker(InMemoryRetriever([]), LLMCandidateJudge(
        recovery_client, max_output_tokens=output_limits.critic_assessment, tracer=tracer), tracer=tracer)
    if store:
        from src.models import ScoutResult, LibraryResult, CriticResult
        scout = CheckpointWorker(scout, store, "scout", ScoutResult)
        library = CheckpointWorker(library, store, "library", LibraryResult)
        critic = CheckpointWorker(critic, store, "critic", CriticResult)
        writer = CheckpointWriter(writer, store)
        verifier = CheckpointVerifier(verifier, store)

    async def execute() -> OrchestrationResult:
        coordinator = Orchestrator(scout, library, critic, tracer=tracer)
        coordinator.checkpoint = store
        async def orchestrate():
            return await coordinator.run(request, search, rubric, mode=mode)
        result = await store.run_stage("evaluated", prepared.configuration_checksum,
                                       OrchestrationResult, orchestrate) if store else await orchestrate()
        try:
            if store:
                finalized = await store.run_stage("finalized", result.model_dump(mode="json"),
                    OrchestrationResult, lambda: finalize_proposals(request, result, writer, verifier,
                        allow_provisional_narrative=rubric.allow_provisional_narrative, tracer=tracer))
            else:
                finalized = await finalize_proposals(request, result, writer, verifier,
                    allow_provisional_narrative=rubric.allow_provisional_narrative, tracer=tracer)
            return await recover_empty_result(
                request, search, rubric, finalized, adapters=run_adapters, budget=budget,
                generator=recovery_generator, critic=recovery_critic, writer=writer, verifier=verifier,
                tracer=tracer, store=store,
            )
        except ProposalCoverageError as error:
            # Evidence insufficiency is a reportable outcome, not a fabricated draft.
            data = result.model_dump(mode="python")
            data["status"] = "insufficient_coverage"
            data["warnings"] = [*result.warnings, str(error)]
            data["completed_at"] = datetime.now(timezone.utc)
            return OrchestrationResult.model_validate(data)

    try:
        finalized = await asyncio.wait_for(execute(), timeout=max(0.001, budget.remaining_seconds()))
    except asyncio.TimeoutError as error:
        raise BudgetExceeded("run time budget exhausted") from error
    finally:
        budget.persist()
    if tracer:
        tracer.event(
            "application", "run_finalized", task_id=finalized.run_id,
            count=len(finalized.final_proposals),
        )
    data = finalized.model_dump(mode="python")
    _redact_uploaded_text(data, prepared)
    data["prepared_run"] = prepared.model_dump(mode="python")
    data["budget_usage"] = budget.snapshot()
    # Export redaction does not cover generated summaries; inspect those too.
    output_warnings = check_privacy(data)
    data["warnings"] = list(dict.fromkeys([
        *data["warnings"], *advisories, *prepared.warnings, *output_warnings,
    ]))
    return OrchestrationResult.model_validate(data)
