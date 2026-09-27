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

from src.runtime.budgets import BudgetExceeded
from src.runtime.failures import failure_code
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
from src.sources.merge import capture_excerpts, is_live_source, merge_source_records
from src.workers.evidence import build_source_chunks


RunMode = Literal["sequential", "parallel"]


class OrchestrationError(RuntimeError):
    """A required run stage failed, so the Critic was not given partial input."""

    def __init__(self, stage: str, error: BaseException) -> None:
        self.stage = stage
        self.error_type = type(error).__name__
        self.code = failure_code(error)
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
        self.checkpoint = None

    async def run(
        self,
        request: InputRequest,
        search: ResolvedSearchConfiguration,
        rubric: EvaluationConfiguration,
        *,
        mode: RunMode = "parallel",
        run_id: str | None = None,
    ) -> OrchestrationResult:
        if mode not in ("sequential", "parallel"):
            raise ValueError("mode must be 'sequential' or 'parallel'")
        if request.domain.casefold() != search.domain.casefold():
            raise ValueError("request and resolved search domains must match")

        run_id = run_id or (self.checkpoint.run_id if self.checkpoint else uuid4().hex)
        span = self.tracer.span("orchestrator", task_id=run_id) if self.tracer else nullcontext()
        with span:
            scout_result, library_result = await self._run_branches(request, search, mode)
            try:
                scout_result = ScoutResult.model_validate(scout_result)
                library_result = LibraryResult.model_validate(library_result)
                self._validate_branch_results(request, scout_result, library_result)
                quarantined: set[str] = set()
                source_manifest = self._merge_sources(
                    scout_result.sources, library_result.sources, quarantined=quarantined,
                )
                if quarantined:
                    # An ambiguous ID cannot safely back a candidate or citation.
                    # Remove affected candidates rather than silently rewriting evidence.
                    warning = "Conflicting live sources quarantined: " + ", ".join(sorted(quarantined))
                    scout_result = ScoutResult(
                        candidates=[candidate for candidate in scout_result.candidates
                                    if not any(ref.source_id in quarantined for ref in candidate.evidence)],
                        sources=[source for source in scout_result.sources if source.source_id not in quarantined],
                        warnings=[*scout_result.warnings, warning],
                    )
                    library_result = LibraryResult(
                        sources=[source for source in library_result.sources if source.source_id not in quarantined],
                        chunks=[chunk for chunk in library_result.chunks if chunk.source_id not in quarantined],
                        warnings=[*library_result.warnings, warning],
                    )
                    if self.tracer:
                        self.tracer.event("orchestrator", "source_receipt_quarantined", count=len(quarantined))
                # Retain Library citation IDs and add distinct Scout excerpts only
                # for sources already retrieved by Library. Coverage stays independent.
                library_ids = {source.source_id for source in library_result.sources}
                merged_library = [source for source in source_manifest if source.source_id in library_ids]
                chunks = {chunk.chunk_id: chunk for chunk in library_result.chunks}
                existing_texts = {(chunk.source_id, chunk.text) for chunk in chunks.values()}
                for chunk in build_source_chunks([source for source in merged_library if source.excerpts]):
                    if chunk.chunk_id in chunks and chunks[chunk.chunk_id].text != chunk.text:
                        raise ValueError("conflicting joined evidence chunk")
                    if (chunk.source_id, chunk.text) not in existing_texts:
                        chunks[chunk.chunk_id] = chunk
                        existing_texts.add((chunk.source_id, chunk.text))
                library_result = LibraryResult(
                    sources=merged_library, chunks=list(chunks.values()), warnings=library_result.warnings,
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
            if self.checkpoint:
                self.checkpoint.write("join", {
                    "scout": scout_result.model_dump(mode="json"),
                    "library": library_result.model_dump(mode="json"),
                }, LibraryResult(sources=source_manifest, chunks=library_result.chunks))

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
                    except BudgetExceeded:
                        raise
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
            status: Literal["completed", "partial", "insufficient_coverage"] = "completed"
            if coverage_warnings or not finalists:
                status = "insufficient_coverage"
            elif len(finalists) < request.finalist_count:
                status = "partial"
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
                requested_finalist_count=request.finalist_count,
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
        """Run Scout and Library under the same policy, sequentially or concurrently.

        In parallel mode either branch is required, so a failure cancels and drains
        its sibling instead of leaving provider work running in the background.
        """
        scout_request = request.model_copy(deep=True)
        library_request = request.model_copy(deep=True)
        if mode == "sequential":
            try:
                scout_result = await self.scout.run(scout_request, search)
            except BudgetExceeded:
                raise
            except Exception as error:
                raise OrchestrationError("scout", error) from error
            try:
                library_result = await self.library.run(library_request, search)
            except BudgetExceeded:
                raise
            except Exception as error:
                raise OrchestrationError("library", error) from error
            return scout_result, library_result

        tasks = [
            asyncio.create_task(self.scout.run(scout_request, search)),
            asyncio.create_task(self.library.run(library_request, search)),
        ]
        try:
            # A required branch failure makes further sibling work unusable.
            # Cancel and drain it instead of spending the remaining run budget.
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for label, task in zip(("scout", "library"), tasks):
                    if task not in done:
                        continue
                    if task.cancelled():
                        raise asyncio.CancelledError()
                    error = task.exception()
                    if isinstance(error, BudgetExceeded):
                        raise error
                    if error is not None:
                        raise OrchestrationError(label, error) from error
            return tasks[0].result(), tasks[1].result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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
    def _merge_sources(
        *groups: list[SourceRecord], quarantined: set[str] | None = None,
    ) -> list[SourceRecord]:
        by_id: dict[str, list[SourceRecord]] = {}
        for source in (item for group in groups for item in group):
            by_id.setdefault(source.source_id, []).append(source)

        merged = []
        for source_id in sorted(by_id):
            records = sorted(by_id[source_id], key=lambda item: item.query_id)
            baseline = capture_excerpts(records[0])
            for record in records[1:]:
                try:
                    baseline = merge_source_records(baseline, record)
                except ValueError as error:
                    if quarantined is not None and all(is_live_source(item) for item in records):
                        quarantined.add(source_id)
                        break
                    raise OrchestrationError(
                        "join", ValueError(f"conflicting source records for {source_id!r}")
                    ) from error
            if quarantined is None or source_id not in quarantined:
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
            missing = candidate_ids - set(evaluated_ids)
            explicit_skips = {
                warning.split(" was ", 1)[0].removeprefix("Candidate ")
                for warning in critic_result.warnings
                if warning.startswith("Candidate ") and " was skipped " in warning
                or warning.startswith("Candidate ") and " was not scored " in warning
            }
            if not missing.issubset(explicit_skips):
                raise OrchestrationError(
                    "critic", ValueError("Critic omitted candidates without explicit skip warnings")
                )

        ordered = sorted(
            evaluations,
            key=lambda item: (-item.total_score, item.candidate_id),
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
