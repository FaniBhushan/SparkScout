"""LLM-backed draft writer for a selected, evidence-backed finalist."""

from __future__ import annotations

from typing import cast

from src.llm.client import LLMClient
from src.llm.prompt_call import call_prompt
from src.models import CandidateIdea, EvaluationResult, InputRequest, ProposalDraft
from src.observability import RunTracer


class LLMProposalWriter:
    """Render the finalization prompt and validate one structured narrative."""

    def __init__(
        self, llm_client: LLMClient, *, max_output_tokens: int, tracer: RunTracer | None = None
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.llm_client = llm_client
        self.max_output_tokens = max_output_tokens
        self.tracer = tracer

    async def draft(
        self,
        request: InputRequest,
        candidate: CandidateIdea,
        evaluation: EvaluationResult,
        sources: list[dict[str, object]],
        chunks: list[dict[str, object]],
    ) -> ProposalDraft:
        """Ask for narrative fields only; code supplies identity and scores."""

        return cast(
            ProposalDraft,
            await call_prompt(
                self.llm_client,
                "final_proposal",
                {
                    "REQUEST_JSON": request,
                    "CANDIDATE_JSON": candidate,
                    # Ranking and score tables are supplied by code, not rewritten
                    # by the writer. Preserve gates and caveats without duplicating
                    # ten scored rationales and their repeated citations.
                    "EVALUATION_JSON": evaluation.model_dump(
                        mode="json", include={"hard_gates", "uncertainty"}, exclude_none=True,
                    ),
                    "SOURCES_JSON": sources,
                    "CHUNKS_JSON": chunks,
                },
                max_output_tokens=self.max_output_tokens,
                tracer=self.tracer,
                task_id=candidate.candidate_id,
            ),
        )
