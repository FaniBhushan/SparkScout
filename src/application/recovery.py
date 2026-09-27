"""One bounded recovery round after all eligible proposals have been exhausted.

Reuse gathered evidence, search for specific gaps only with remaining allowance,
and assess a small replacement pool. The original request and rubric stay fixed.
"""

from collections import Counter

from pydantic import ValidationError

from src.adapters.http_json import SourceAdapterError
from src.runtime.budgets import BudgetExceeded
from src.application.finalization import finalize_proposals
from src.guardrails import safe_error_message
from src.llm.candidate_batches import merge_candidates
from src.llm.client import ModelResponseError
from src.models import LibraryResult, ScoutResult, SourceQuery, OrchestrationResult, CriticResult
from src.models.orchestration_result import RecoveryRecord
from src.orchestration.coordinator import Orchestrator, OrchestrationError
from src.persistence.workers import CheckpointWorker
from src.sources.merge import capture_excerpts, is_live_source, merge_source_records
from src.workers.evidence import build_source_chunks
from src.workers.source_filter import source_is_within_age_limit, same_source_content


class CompletedWorker:
    """Supply retained stage output to the coordinator without repeating calls."""

    def __init__(self, result):
        self.result = result

    async def run(self, request, search):
        return self.result.model_copy(deep=True)


def recovery_feedback(result):
    """Bound feedback size and keep model rejection text inside untrusted data."""
    return {
        "previous_ideas": [{"title": candidate.title,
                            "problem_statement": candidate.problem_statement[:300]}
                           for candidate in result.scout.candidates],
        "rejection_reasons": list(dict.fromkeys([
            *(reason[:300] for evaluation in result.critic.evaluations
              for reason in evaluation.rejection_reasons),
            *(reason[:300] for reason in result.proposal_failures.values()),
        ]))[:8],
    }


async def recover_library(request, search, previous, adapters, budget, feedback, tracer):
    """Target remaining source gaps with no more than two allowed provider calls.

    Existing receipts and chunks are retained. New records must still satisfy the
    same source, date, and provider policies as the initial search.
    """
    sources = {source.source_id: source for source in previous.sources}
    warnings = list(previous.warnings)
    used = budget.snapshot()["provider_calls"]
    # Recovery shares Scout/Library's combined query allowance and provider caps;
    # it must not turn this pass into an unbudgeted extra search stage.
    remaining_calls = min(2, max(0, 2 * search.max_queries - sum(used.values())))
    attempted = 0
    for provider in search.providers:
        if attempted >= remaining_calls or len(sources) >= search.max_sources:
            break
        provider_id = provider.provider_id
        if provider_id not in adapters or used.get(provider_id, 0) >= budget.limits.provider_call_limits.get(provider_id, 0):
            continue
        counts = Counter(source.source_type for source in sources.values())
        kinds = [kind for kind in provider.source_types
                 if counts[kind] < search.max_records_by_type.get(kind, search.max_sources)]
        if not kinds:
            continue
        query = SourceQuery(
            query_id=f"recovery-query-{attempted + 1}", provider_id=provider_id,
            text=" ".join([request.domain, *request.interests,
                           *feedback["rejection_reasons"][:2], "documented data access prototype"])[:1000],
            source_types=kinds, content_types=provider.content_types,
            max_results=min(search.max_results_per_query, search.max_sources - len(sources)),
        )
        attempted += 1
        try:
            records = await adapters[provider_id].search(query)
        except SourceAdapterError as error:
            warnings.append("Recovery search unavailable: " + safe_error_message(error))
            continue
        if tracer:
            tracer.event("recovery", "targeted_search_completed", provider_id=provider_id, count=len(records))
        for source in records[:query.max_results]:
            if (source.provider != provider_id or source.query_id != query.query_id
                    or source.source_type not in kinds or not source_is_within_age_limit(source, search)):
                warnings.append("Recovery ignored a source outside the approved query policy.")
                continue
            previous_source = sources.get(source.source_id)
            if previous_source is not None:
                try:
                    if is_live_source(source):
                        sources[source.source_id] = merge_source_records(previous_source, source)
                    elif not same_source_content(previous_source, source):
                        warnings.append(f"Recovery ignored a conflicting receipt for {source.source_id}.")
                except ValueError:
                    warnings.append(f"Recovery ignored a conflicting receipt for {source.source_id}.")
            elif counts[source.source_type] < search.max_records_by_type.get(source.source_type, search.max_sources):
                sources[source.source_id] = capture_excerpts(source)
                counts[source.source_type] += 1
    # Preserve existing citation IDs, including passages restored from checkpoints.
    chunks = {chunk.chunk_id: chunk for chunk in previous.chunks}
    texts = {(chunk.source_id, chunk.text) for chunk in chunks.values()}
    for chunk in build_source_chunks(list(sources.values())):
        if (chunk.source_id, chunk.text) not in texts:
            if chunk.chunk_id in chunks:
                warnings.append("Recovery ignored a conflicting evidence chunk.")
                continue
            chunks[chunk.chunk_id] = chunk
            texts.add((chunk.source_id, chunk.text))
    return LibraryResult(sources=list(sources.values()), chunks=list(chunks.values()), warnings=warnings)


async def recover_empty_result(request, search, rubric, result, *, adapters, budget,
                               generator, critic, writer, verifier, tracer=None, store=None):
    """Attempt one bounded recovery round only when no verified proposal exists.

    A prior successful proposal, earlier recovery attempt, or exhausted budget
    makes the run terminal; other failures preserve the best available result and
    its diagnostics.
    """
    if result.final_proposals or result.recovery_history or result.budget_exhausted:
        return result
    history = RecoveryRecord(
        previous_candidates=result.scout.candidates,
        previous_candidate_ids=[candidate.candidate_id for candidate in result.scout.candidates],
        previous_evaluations=result.critic.evaluations,
        proposal_failures=result.proposal_failures,
    )
    latest = result
    feedback = recovery_feedback(result)
    inputs = {"result": result.model_dump(mode="json"), "feedback": feedback}

    async def stage(name, model, operation):
        return await store.run_stage(f"recovery:{name}", inputs, model, operation) if store else await operation()

    try:
        budget.check_time()
        if tracer:
            tracer.event("recovery", "round_started", count=1)
        library = await stage("library", LibraryResult, lambda: recover_library(
            request, search, result.library, adapters, budget, feedback, tracer))
        if Orchestrator._minimum_coverage_warnings(request, search, library):
            history.outcome = "exhausted"
            history.reason = "Recovery could not establish the required source coverage."
        else:
            async def replacements():
                count = min(3, request.desired_candidate_count)
                smaller = request.model_copy(update={"desired_candidate_count": count,
                                                     "finalist_count": min(count, request.finalist_count)})
                # Restored sources omit memory-only evidence_chunks. Reattach
                # the actual Library passages so recovery does not regress to summaries.
                grounded_sources = [source.model_copy(update={"evidence_chunks": [
                    chunk for chunk in library.chunks if chunk.source_id == source.source_id
                ]}) for source in library.sources]
                generated = await generator.generate(smaller, grounded_sources, recovery_feedback=feedback)
                combined = merge_candidates(result.scout.candidates, generated,
                                             [{"source_id": source.source_id} for source in library.sources])
                fresh = combined[len(result.scout.candidates):]
                fresh = [candidate.model_copy(update={"candidate_id": f"recovery-01-{index + 1}"})
                         for index, candidate in enumerate(fresh) if candidate.origin != "synthetic"]
                return ScoutResult(candidates=fresh, sources=library.sources)

            scout = await stage("scout", ScoutResult, replacements)
            history.replacement_candidate_ids = [candidate.candidate_id for candidate in scout.candidates]
            if not scout.candidates:
                history.outcome = "exhausted"
                history.reason = "Recovery generated no distinct evidence-backed alternatives."
            else:
                recovery_critic = CheckpointWorker(critic, store, "recovery:critic", CriticResult) if store else critic
                coordinator = Orchestrator(CompletedWorker(scout), CompletedWorker(library), recovery_critic, tracer=tracer)
                latest = await stage("evaluated", OrchestrationResult, lambda: coordinator.run(
                    request, search, rubric, mode=result.mode, run_id=result.run_id))
                latest = await stage("finalized", OrchestrationResult, lambda: finalize_proposals(
                    request, latest, writer, verifier,
                    allow_provisional_narrative=rubric.allow_provisional_narrative, tracer=tracer))
                history.outcome = "completed" if latest.final_proposals else "exhausted"
                history.reason = None if latest.final_proposals else "No replacement proposal passed all checks."
    except (BudgetExceeded, ModelResponseError, ValidationError, OrchestrationError) as error:
        history.outcome = "exhausted" if isinstance(error, BudgetExceeded) else "failed"
        history.reason = safe_error_message(error)
    if tracer:
        tracer.event("recovery", "round_" + history.outcome, count=len(latest.final_proposals))
    data = latest.model_dump(mode="python")
    if not latest.final_proposals:
        data["status"] = "insufficient_coverage"
        data["finalist_candidate_ids"] = []
    data["proposal_failures"] = {**result.proposal_failures, **latest.proposal_failures}
    data["recovery_history"] = [history.model_dump(mode="python")]
    data["warnings"] = list(dict.fromkeys([
        *result.warnings, *latest.warnings,
        "One bounded recovery round was attempted after the initial proposal pool was exhausted.",
        *([history.reason] if history.reason else []),
    ]))
    return OrchestrationResult.model_validate(data)
