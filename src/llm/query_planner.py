"""Shared LLM flow for Scout and Library source-query planning."""

from typing import Generic, Literal, TypeVar, cast

from src.llm.client import LLMClient
from src.llm.prompt_call import call_prompt
from src.models import InputRequest, ResolvedSearchConfiguration, SourceQuery
from src.observability import RunTracer


QueryT = TypeVar("QueryT", bound=SourceQuery)
QueryPrompt = Literal["scout_query_planner", "library_query_planner"]


class _LLMQueryPlanner(Generic[QueryT]):
    """Render a branch's query prompt and validate its response."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_name: QueryPrompt,
        max_output_tokens: int,
        tracer: RunTracer | None = None,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.llm_client = llm_client
        self.prompt_name = prompt_name
        self.max_output_tokens = max_output_tokens
        self.tracer = tracer

    async def plan(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
    ) -> list[QueryT]:
        """Use the branch-specific prompt with the same typed request context."""
        return cast(
            list[QueryT],
            await call_prompt(
                self.llm_client,
                self.prompt_name,
                {"REQUEST_JSON": request, "SEARCH_CONFIG_JSON": search},
                max_output_tokens=self.max_output_tokens,
                tracer=self.tracer,
            ),
        )
