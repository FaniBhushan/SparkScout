"""Coordinate Scout, Library, Critic, and deterministic finalist selection."""

from __future__ import annotations

import asyncio
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Literal
import unicodedata
from uuid import uuid4

from src.models import (
    EvaluationConfiguration,
    CriticResult,
    InputRequest,
    LibraryResult,
    OrchestrationResult,
    RankedCandidate,
    ResolvedSearchConfiguration,
    ScoutResult,
    SourceRecord,
)
from src.models.orchestration_result import RetrievalIndexInfo
from src.models.source_record import RetrievalStatus
from src.observability import RunTracer
from src.retrieval import HybridInMemoryRetriever, load_retrieval_index_configuration
from src.workers.critic_worker import CriticWorker
from src.workers.library_worker import LibraryWorker
from src.workers.scout_worker import ScoutWorker


RunMode = Literal["sequential", "parallel"]


class OrchestrationError(RuntimeError):
    """A required run stage failed, so the Critic was not given partial input."""

    def __init__(self, stage: str, error: BaseException) -> None:
        self.stage = stage
        self.error_type = type(error).__name__
        super().__init__(f"{stage} stage failed ({self.error_type}): {error}")


class Orchestrator:
    """Coordinate workers; workers never select finalists or share mutable state."""

    def __init__(
        self,
        scout: ScoutWorker,
        library: LibraryWorker,
        critic: CriticWorker,
        tracer: RunTracer | None = None,
    ) -> None:
        self.scout = scout
        self.library = library
        self.critic = critic
        self.tracer = tracer

    async def run(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
        rubric: EvaluationConfiguration,
        *,
        mode: RunMode = "parallel",
    ) -> OrchestrationResult:
        if mode not in ("sequential", "parallel"):
            raise ValueError("mode must be 'sequential' or 'parallel'")
        if request.domain.casefold() != search.domain.casefold():
            raise ValueError("request and resolved search domains must match")

        run_id = uuid4().hex
        span = self.tracer.span("orchestrator", task_id=run_id) if self.tracer else nullcontext()
        with span:
            scout_result, library_result = await self._run_branches(request, search, mode)
            try:
                scout_result = ScoutResult.model_validate(scout_result)
                library_result = LibraryResult.model_validate(library_result)
                self._validate_branch_results(request, scout_result, library_result)
                source_manifest = self._merge_sources(
                    scout_result.sources, library_result.sources
                )
            except OrchestrationError:
                raise
            except Exception as error:
                raise OrchestrationError("join", error) from error

            near_duplicate = self._find_near_duplicate_candidates(scout_result.candidates)
            if near_duplicate is not None:
                first_id, duplicate_id = near_duplicate
                raise OrchestrationError(
                    "join",
                    ValueError(
                        f"Scout candidates {first_id!r} and {duplicate_id!r} appear to be "
                        "near-duplicates by target users, problem, and outcome"
                    ),
                )

            coverage_warnings = self._minimum_coverage_warnings(request, search, library_result)

            if self.tracer:
                self.tracer.event("orchestrator", "join_validated", task_id=run_id)
                self.tracer.budget(
                    "orchestrator", "candidate_count", len(scout_result.candidates),
                    request.desired_candidate_count, task_id=run_id,
                )
                self.tracer.budget(
                    "orchestrator", "source_count", len(source_manifest),
                    search.max_sources * 2, task_id=run_id,
                )

            if coverage_warnings:
                critic_result = CriticResult(
                    warnings=["Critic skipped because minimum Library coverage was not met."]
                )
                retrieval_index = None
                if self.tracer:
                    self.tracer.event("orchestrator", "critic_skipped", task_id=run_id)
            else:
                with (
                    self.tracer.span("critic_stage", task_id=run_id)
                    if self.tracer
                    else nullcontext()
                ):
                    retriever = None
                    try:
                        settings = load_retrieval_index_configuration()
                        corpus_chars = sum(len(chunk.text) for chunk in library_result.chunks)
                        retriever = HybridInMemoryRetriever(library_result.chunks, settings)
                        # The audit output must contain the exact chunks indexed for Critic.
                        library_result = LibraryResult(
                            sources=library_result.sources,
                            chunks=retriever.chunks,
                            warnings=library_result.warnings,
                        )
                        retrieval_index = RetrievalIndexInfo(
                            index_id=f"{run_id}:library",
                            indexed_chunk_count=len(retriever.chunks),
                            corpus_chars=corpus_chars,
                            index_bytes_estimate=retriever.index_bytes,
                            chunk_size_chars=settings.chunk_size_chars,
                            chunk_overlap_chars=settings.chunk_overlap_chars,
                            max_corpus_chars=settings.max_corpus_chars,
                            max_chunks=settings.max_chunks,
                            max_index_bytes=settings.max_index_bytes,
                            retrieval_top_k=rubric.retrieval_top_k,
                            max_context_chunks=rubric.max_context_chunks,
                            max_context_tokens=rubric.max_context_tokens,
                        )
                        if self.tracer:
                            self.tracer.event(
                                "retrieval_index", "index_created",
                                task_id=run_id, count=retrieval_index.indexed_chunk_count,
                            )
                        run_critic = self.critic.with_retriever(retriever)
                        critic_result = CriticResult.model_validate(
                            await run_critic.run(
                                request.model_copy(deep=True),
                                [candidate.model_copy(deep=True) for candidate in scout_result.candidates],
                                library_result.model_copy(deep=True),
                                rubric,
                            )
                        )
                    except Exception as error:
                        raise OrchestrationError("critic", error) from error
                    finally:
                        if self.tracer and retriever is not None:
                            self.tracer.event(
                                "retrieval_index", "index_scope_ended", task_id=run_id
                            )

            rankings = (
                []
                if coverage_warnings
                else self._rank(scout_result.candidates, critic_result)
            )
            passing_ids = [row.candidate_id for row in rankings if row.gate_passed]
            finalists = passing_ids[: request.finalist_count]
            warnings = self._combine_warnings(
                scout_result.warnings, library_result.warnings, critic_result.warnings,
                coverage_warnings,
            )
            status: Literal["completed", "insufficient_coverage"] = "completed"
            if coverage_warnings or len(finalists) < request.finalist_count:
                status = "insufficient_coverage"
            if len(finalists) < request.finalist_count and not coverage_warnings:
                warnings.append(
                    f"Only {len(finalists)} of {request.finalist_count} requested finalists "
                    "passed evaluation gates."
                )
            if not library_result.chunks and "No source chunks available for evaluation." not in warnings:
                warnings.append("No source chunks were available for candidate evaluation.")
            if not scout_result.candidates and not any("candidate" in item.lower() for item in warnings):
                warnings.append("Scout returned no candidate ideas.")
            if self.tracer:
                self.tracer.event(
                    "orchestrator", "run_completed", task_id=run_id,
                    count=len(finalists),
                )
            return OrchestrationResult(
                run_id=run_id,
                mode=mode,
                status=status,
                scout=scout_result,
                library=library_result,
                critic=critic_result,
                retrieval_index=retrieval_index,
                source_manifest=source_manifest,
                ranking=rankings,
                finalist_candidate_ids=finalists,
                warnings=warnings,
                completed_at=datetime.now(timezone.utc),
            )

    async def _run_branches(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
        mode: RunMode,
    ):
        scout_request = request.model_copy(deep=True)
        library_request = request.model_copy(deep=True)
        if mode == "sequential":
            try:
                scout_result = await self.scout.run(scout_request, search)
            except Exception as error:
                raise OrchestrationError("scout", error) from error
            try:
                library_result = await self.library.run(library_request, search)
            except Exception as error:
                raise OrchestrationError("library", error) from error
            return scout_result, library_result

        outcomes = await asyncio.gather(
            self.scout.run(scout_request, search),
            self.library.run(library_request, search),
            return_exceptions=True,
        )
        labels = ("scout", "library")
        for label, outcome in zip(labels, outcomes):
            if isinstance(outcome, BaseException):
                raise OrchestrationError(label, outcome) from outcome
        return outcomes[0], outcomes[1]

    @staticmethod
    def _validate_branch_results(request, scout, library) -> None:
        candidate_ids = [candidate.candidate_id for candidate in scout.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise OrchestrationError("join", ValueError("Scout returned duplicate candidate IDs"))
        if len(candidate_ids) > request.desired_candidate_count:
            raise OrchestrationError(
                "join", ValueError("Scout exceeded desired_candidate_count")
            )

        scout_source_ids = {source.source_id for source in scout.sources}
        for candidate in scout.candidates:
            for evidence in candidate.evidence:
                if evidence.source_id not in scout_source_ids:
                    raise OrchestrationError(
                        "join",
                        ValueError(
                            f"candidate {candidate.candidate_id!r} cites a source absent from Scout"
                        ),
                    )

        library_source_ids = {source.source_id for source in library.sources}
        chunk_ids = [chunk.chunk_id for chunk in library.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise OrchestrationError("join", ValueError("Library returned duplicate chunk IDs"))
        for chunk in library.chunks:
            if chunk.source_id not in library_source_ids:
                raise OrchestrationError(
                    "join", ValueError(f"chunk {chunk.chunk_id!r} has no Library source")
                )

    @staticmethod
    def _minimum_coverage_warnings(request, search, library) -> list[str]:
        usable_sources = [
            source
            for source in library.sources
            if source.retrieval_status in (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL)
        ]
        warnings = []
        if len(usable_sources) < search.minimum_source_count:
            warnings.append(
                f"Library returned {len(usable_sources)} usable sources; "
                f"at least {search.minimum_source_count} are required."
            )
        available_types = {source.source_type for source in usable_sources}
        required_types = set(search.required_source_types) | set(request.source_policy.required_types)
        missing_types = sorted(required_types - available_types)
        if missing_types:
            warnings.append(
                "Library did not find required source types: " + ", ".join(missing_types) + "."
            )
        if not library.chunks:
            warnings.append("Library returned no usable chunks for Critic evaluation.")
        return warnings

    @staticmethod
    def _find_near_duplicate_candidates(candidates):
        """Flag near-copies using high text similarity in problem and outcome.

        Titles are intentionally ignored. This conservative lexical check catches
        copy-like variants; it does not claim to detect all semantic duplicates.
        """

        def normalize(text: str) -> str:
            normalized = unicodedata.normalize("NFKC", text).casefold()
            return " ".join(re.findall(r"[\w]+", normalized))

        def similarity(left: str, right: str) -> float:
            return SequenceMatcher(None, normalize(left), normalize(right), autojunk=False).ratio()

        for index, candidate in enumerate(candidates):
            users = {normalize(user) for user in candidate.target_users}
            for other in candidates[:index]:
                other_users = {normalize(user) for user in other.target_users}
                user_overlap = len(users & other_users) / max(1, len(users | other_users))
                if (
                    user_overlap >= 0.8
                    and similarity(candidate.problem_statement, other.problem_statement) >= 0.9
                    and similarity(candidate.proposed_outcome, other.proposed_outcome) >= 0.9
                ):
                    return other.candidate_id, candidate.candidate_id
        return None

    @staticmethod
    def _merge_sources(*groups: list[SourceRecord]) -> list[SourceRecord]:
        by_id: dict[str, list[SourceRecord]] = {}
        for source in (item for group in groups for item in group):
            by_id.setdefault(source.source_id, []).append(source)

        merged = []
        for source_id in sorted(by_id):
            records = sorted(by_id[source_id], key=lambda item: item.query_id)
            baseline = records[0]
            for record in records[1:]:
                identity = (baseline.provider, baseline.source_type, baseline.canonical_url,
                            baseline.content_hash)
                other = (record.provider, record.source_type, record.canonical_url,
                         record.content_hash)
                if identity != other:
                    raise OrchestrationError(
                        "join", ValueError(f"conflicting source records for {source_id!r}")
                    )
            merged.append(baseline)
        return merged

    @staticmethod
    def _rank(candidates, critic_result) -> list[RankedCandidate]:
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        evaluations = critic_result.evaluations
        evaluated_ids = [evaluation.candidate_id for evaluation in evaluations]
        if len(evaluated_ids) != len(set(evaluated_ids)) or set(evaluated_ids) - candidate_ids:
            raise OrchestrationError("critic", ValueError("Critic returned unknown or duplicate IDs"))
        if set(evaluated_ids) != candidate_ids:
            raise OrchestrationError("critic", ValueError("Critic did not evaluate every candidate"))

        ordered = sorted(
            evaluations,
            key=lambda item: (not item.gate_passed, -item.total_score, item.candidate_id),
        )
        return [
            RankedCandidate(
                candidate_id=evaluation.candidate_id,
                evaluation_id=evaluation.evaluation_id,
                rank=rank,
                total_score=evaluation.total_score,
                gate_passed=evaluation.gate_passed,
            )
            for rank, evaluation in enumerate(ordered, start=1)
        ]

    @staticmethod
    def _combine_warnings(*groups: list[str]) -> list[str]:
        return list(dict.fromkeys(warning for group in groups for warning in group))
