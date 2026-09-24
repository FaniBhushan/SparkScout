"""Assemble one research run independently of its CLI or future UI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.adapters.base import SourceAdapter
from src.configuration import resolve_search_configuration
from src.evaluation import load_evaluation_configuration
from src.llm import (
    LLMCandidateGenerator,
    LLMCandidateJudge,
    LLMLibraryQueryPlanner,
    LLMScoutQueryPlanner,
)
from src.llm.client import LLMClient
from src.models import InputRequest, OrchestrationResult, SearchLimits
from src.observability import RunTracer
from src.orchestration.coordinator import Orchestrator, RunMode
from src.retrieval import InMemoryRetriever
from src.workers.critic_worker import CriticWorker
from src.workers.library_worker import LibraryWorker
from src.workers.scout_worker import ScoutWorker


@dataclass(frozen=True)
class LLMOutputLimits:
    """Per-call output caps; these are not yet a run-wide token budget."""

    scout_queries: int = 1000
    candidate_generation: int = 3000
    library_queries: int = 1000
    critic_assessment: int = 3000

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("all LLM output limits must be positive")


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
) -> OrchestrationResult:
    """Resolve permissions, wire workers, and execute one structured request."""

    # Validate configuration before any worker can spend model or provider calls.
    search = resolve_search_configuration(
        request,
        available_adapters,
        preset_name=search_preset,
        requested_limits=requested_limits,
    )
    rubric = load_evaluation_configuration(rubric_preset, weights=weights)

    scout = ScoutWorker(
        available_adapters,
        LLMScoutQueryPlanner(
            llm_client, max_output_tokens=output_limits.scout_queries, tracer=tracer
        ),
        LLMCandidateGenerator(
            llm_client, max_output_tokens=output_limits.candidate_generation, tracer=tracer
        ),
        tracer=tracer,
    )
    library = LibraryWorker(
        available_adapters,
        LLMLibraryQueryPlanner(
            llm_client, max_output_tokens=output_limits.library_queries, tracer=tracer
        ),
        tracer=tracer,
    )
    # The coordinator replaces this empty template index with Library chunks for each run.
    critic = CriticWorker(
        InMemoryRetriever([]),
        LLMCandidateJudge(
            llm_client, max_output_tokens=output_limits.critic_assessment, tracer=tracer
        ),
        tracer=tracer,
    )
    return await Orchestrator(scout, library, critic, tracer=tracer).run(
        request, search, rubric, mode=mode
    )
