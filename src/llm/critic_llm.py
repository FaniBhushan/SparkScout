"""LLM-backed Critic assessment from retrieved Library evidence."""

from typing import cast

from src.llm.client import LLMClient
from src.llm.prompt_call import call_prompt
from src.models import (
    CandidateAssessment,
    CandidateIdea,
    EvaluationConfiguration,
    InputRequest,
    RetrievedChunk,
)
from src.observability import RunTracer


class LLMCandidateJudge:
    """Return a validated raw assessment; CriticWorker scores and checks citations."""

    def __init__(
        self, llm_client: LLMClient, *, max_output_tokens: int, tracer: RunTracer | None = None
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.llm_client = llm_client
        self.max_output_tokens = max_output_tokens
        self.tracer = tracer

    async def assess(
        self,
        request: InputRequest,
        candidate: CandidateIdea,
        evidence: list[RetrievedChunk],
        rubric: EvaluationConfiguration,
    ) -> CandidateAssessment:
        compact_evidence = [
            {
                "source_id": hit.chunk.source_id,
                "chunk_id": hit.chunk.chunk_id,
                "text": hit.chunk.text,
            }
            for hit in evidence
        ]
        return cast(
            CandidateAssessment,
            await call_prompt(
                self.llm_client,
                "critic_candidate_judge",
                {
                    "REQUEST_JSON": request,
                    "CANDIDATE_JSON": candidate,
                    "EVALUATION_CONFIGURATION_JSON": rubric,
                    "RETRIEVED_EVIDENCE_JSON": compact_evidence,
                },
                max_output_tokens=self.max_output_tokens,
                tracer=self.tracer,
                task_id=candidate.candidate_id,
            ),
        )
