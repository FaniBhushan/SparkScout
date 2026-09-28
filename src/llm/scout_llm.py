"""LLM-backed Scout query planning and candidate generation."""

from typing import cast

from pydantic import ValidationError

from src.guardrails.privacy import safe_validation_hints
from src.llm.client import LLMClient, ModelResponseError
from src.llm.prompt_call import call_prompt
from src.llm.query_planner import _LLMQueryPlanner

from src.models import (
    CandidateIdea,
    InputRequest,
    ScoutQuery,
    SourceRecord,
)
from src.observability import RunTracer


class LLMScoutQueryPlanner(_LLMQueryPlanner[ScoutQuery]):
    """Plan Scout queries using an injected LLM client."""

    def __init__(
        self, llm_client: LLMClient, *, max_output_tokens: int, tracer: RunTracer | None = None
    ) -> None:
        super().__init__(
            llm_client,
            prompt_name="scout_query_planner",
            max_output_tokens=max_output_tokens,
            tracer=tracer,
        )


class LLMCandidateGenerator:
    """Generate Scout candidates using an injected LLM client."""

    def __init__(
        self, llm_client: LLMClient, *, max_output_tokens: int, tracer: RunTracer | None = None
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.llm_client = llm_client
        self.max_output_tokens = max_output_tokens
        self.tracer = tracer

    async def generate(
        self,
        request: InputRequest,
        sources: list[SourceRecord],
        *, recovery_feedback: dict | None = None,
    ) -> list[CandidateIdea]:
        if not sources:
            return []

        compact_sources = [
            source.model_dump(
                mode="json",
                include={
                    "source_id",
                    "provider",
                    "source_type",
                    "title",
                    "published_at",
                    "canonical_url",
                    "abstract_or_snippet",
                    "license_access_note",
                },
                exclude_none=True,
            )
            for source in sources
        ]
        # One short captured passage can supply fields/permissions absent from
        # a search summary. Bound it per source instead of sending whole documents.
        for compact, source in zip(compact_sources, sources):
            excerpts = [chunk for chunk in source.evidence_chunks if len(chunk.text) <= 1200]
            if excerpts:
                compact["evidence_excerpt"] = {
                    "chunk_id": excerpts[0].chunk_id, "text": excerpts[0].text,
                }
                if len(excerpts) > 1:
                    compact["additional_evidence_excerpt"] = {
                        "chunk_id": excerpts[1].chunk_id, "text": excerpts[1].text,
                    }
        candidates = await generate_candidate_batches(
            self.llm_client, request, compact_sources,
            max_output_tokens=self.max_output_tokens, tracer=self.tracer,
            recovery_feedback=recovery_feedback,
        )
        # Synthetic ideas can influence subsequent batches, but never leave generation.
        return [item for item in candidates if item.origin != "synthetic"]


async def generate_candidate_batches(
    client: LLMClient, request: InputRequest, sources: list[dict], *,
    max_output_tokens: int, tracer: RunTracer | None,
    recovery_feedback: dict | None = None,
) -> list[CandidateIdea]:
    """Bound generation output and retain valid ideas when a later batch is malformed.

    Use at most three ideas per response, with a finite batch count and one extra
    attempt for a truncated initial response. Compact idea summaries prevent
    repeated ideas without resending full prior outputs. Shared run budgets
    remain authoritative; budget and transport failures still propagate.
    """

    from src.llm.candidate_batches import merge_candidates

    batch_size = min(3, max(1, max_output_tokens // 700))
    batch_limit = (request.desired_candidate_count + batch_size - 1) // batch_size
    candidates: list[CandidateIdea] = []
    initial_recovery_used = False
    active_recovery_feedback = dict(recovery_feedback or {})
    for batch_index in range(batch_limit + 1):
        if len(candidates) >= request.desired_candidate_count:
            break
        if batch_index >= batch_limit and not initial_recovery_used:
            break
        requested_count = min(batch_size, request.desired_candidate_count - len(candidates))
        context = {
            "REQUEST_JSON": request, "SOURCE_RECORDS_JSON": sources,
            "BATCH_JSON": {
                "requested_count": requested_count,
                "recovery_feedback": active_recovery_feedback or None,
                "existing_ideas": [
                    {"target_users": item.target_users, "problem_statement": item.problem_statement,
                     "proposed_outcome": item.proposed_outcome, "origin": item.origin}
                    for item in candidates
                ],
            },
        }
        try:
            batch = cast(list[CandidateIdea], await call_prompt(
                client, "scout_candidate_generator", context,
                max_output_tokens=max_output_tokens, tracer=tracer,
                task_id=f"batch-{batch_index + 1}", validation_retry_limit=0,
            ))
        except (ValidationError, ModelResponseError) as error:
            from src.runtime.budgets import StageAllowanceExceeded
            if isinstance(error, StageAllowanceExceeded):
                if tracer:
                    tracer.event("candidate_generation", "stage_allowance_reached", count=len(candidates))
                break
            if isinstance(error, ModelResponseError) and error.reply is None:
                raise
            if tracer:
                tracer.event("candidate_generation", "batch_response_failed", count=len(candidates))
            if candidates:
                break
            if initial_recovery_used:
                raise
            if isinstance(error, ValidationError):
                # Share only contract paths and Pydantic error codes—not rejected
                # output or message text—with the lower-cost recovery attempt.
                active_recovery_feedback["response_schema_issues"] = safe_validation_hints(error)
            # Retry only the failed initial batch with a smaller output request.
            initial_recovery_used = True
            batch_size = max(1, batch_size // 2)
            continue
        merged = merge_candidates(candidates, batch[:requested_count], sources)
        if len(merged) == len(candidates):
            break  # More paid attempts on unchanged evidence are unlikely to help.
        candidates = merged
        if tracer:
            tracer.event("candidate_generation", "batch_retained", count=len(candidates))
    return candidates
