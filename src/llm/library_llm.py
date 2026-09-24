"""LLM-backed Library query planning."""

from src.llm.client import LLMClient
from src.llm.query_planner import _LLMQueryPlanner
from src.models import SourceQuery
from src.observability import RunTracer


class LLMLibraryQueryPlanner(_LLMQueryPlanner[SourceQuery]):
    """Plan Library queries using an injected LLM client."""

    def __init__(
        self, llm_client: LLMClient, *, max_output_tokens: int, tracer: RunTracer | None = None
    ) -> None:
        super().__init__(
            llm_client,
            prompt_name="library_query_planner",
            max_output_tokens=max_output_tokens,
            tracer=tracer,
        )
