"""LLM-backed Scout query planning and candidate generation."""

from typing import cast

from src.llm.client import LLMClient
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
        return cast(
            list[CandidateIdea],
            await call_prompt(
                self.llm_client,
                "scout_candidate_generator",
                {"REQUEST_JSON": request, "SOURCE_RECORDS_JSON": compact_sources},
                max_output_tokens=self.max_output_tokens,
                tracer=self.tracer,
            ),
        )
