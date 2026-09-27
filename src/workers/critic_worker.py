"""Critic worker: evaluate candidates against evidence and a rubric."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from src.models import (
    CandidateAssessment,
    CandidateIdea,
    CriticResult,
    EvaluationConfiguration,
    InputRequest,
    LibraryResult,
    RetrievedChunk,
)
from src.models.common import EvidenceReference
from src.models.evaluation_result import CriterionScore, EvaluationResult, HardGateResult
from src.observability import RunTracer
from src.retrieval import Retriever
from src.workers.critic_evidence import retrieve_candidate_evidence
from src.runtime.budgets import StageAllowanceExceeded


class CandidateJudge(Protocol):
    """Assess one candidate using only its retrieved evidence context."""

    async def assess(
        self,
        request: InputRequest,
        candidate: CandidateIdea,
        evidence: list[RetrievedChunk],
        rubric: EvaluationConfiguration,
    ) -> CandidateAssessment: ...


class CriticWorker:
    """Retrieve candidate-specific passages and validate rubric judgments.

    Candidates are independent: malformed judgments are reported and skipped so
    one bad response does not discard other completed assessments.
    """

    def __init__(
        self,
        retriever: Retriever,
        judge: CandidateJudge,
        tracer: RunTracer | None = None,
    ) -> None:
        self.retriever = retriever
        self.judge = judge
        self.tracer = tracer

    def with_retriever(self, retriever: Retriever) -> "CriticWorker":
        """Use the same judge and tracing setup with a run-specific index."""

        return CriticWorker(retriever, self.judge, self.tracer)

    async def run(
        self,
        request: InputRequest,
        candidates: list[CandidateIdea],
        library: LibraryResult,
        rubric: EvaluationConfiguration,
    ) -> CriticResult:
        with self.tracer.span("critic") if self.tracer else nullcontext():
            if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
                raise ValueError("candidate IDs must be unique")
            if not library.chunks:
                return CriticResult(warnings=["No source chunks available for evaluation."])
            evaluations = []
            warnings = []
            for candidate_index, candidate in enumerate(candidates):
                with (
                    self.tracer.span("candidate_evaluation", task_id=candidate.candidate_id)
                    if self.tracer
                    else nullcontext()
                ):
                    evidence = await self._retrieve(candidate, library, rubric)
                    if not evidence:
                        warnings.append(
                            f"Candidate {candidate.candidate_id} was skipped because no relevant evidence was found."
                        )
                        self._trace_candidate_skip(candidate, "no_relevant_evidence")
                        continue
                    try:
                        assessment = await self.judge.assess(request, candidate, evidence, rubric)
                    except StageAllowanceExceeded:
                        # Finalization has a separate reserved allowance, so stop
                        # scoring here and let the coordinator use it for proposals.
                        warnings.append("Critic stopped at its stage allowance; retained completed assessments for finalization.")
                        warnings.extend(
                            f"Candidate {pending.candidate_id} was not scored because the research stage allowance was reached."
                            for pending in candidates[candidate_index:])
                        break
                    except ValidationError:
                        warnings.append(
                            f"Candidate {candidate.candidate_id} was not scored because its Critic response failed schema validation."
                        )
                        self._trace_candidate_skip(candidate, "invalid_critic_schema")
                        continue
                    repaired_source_ids = self._repair_chunk_source_ids(assessment, evidence)
                    repaired_citations = self._fill_unambiguous_chunk_ids(assessment, evidence)
                    try:
                        evaluations.append(
                            self._make_evaluation(candidate, assessment, evidence, rubric)
                        )
                    except ValueError as error:
                        # Never score invalid judgments; keep independent candidates moving.
                        category = self._invalid_assessment_category(str(error))
                        warnings.append(
                            f"Candidate {candidate.candidate_id} was not scored because its Critic {category} check failed."
                        )
                        self._trace_candidate_skip(candidate, f"invalid_critic_{category}")
                        continue
                    if repaired_source_ids or repaired_citations:
                        if repaired_citations and not repaired_source_ids:
                            message = "its source-only citation was matched to its unique retrieved chunk ID."
                        else:
                            message = "an unambiguous citation reference was normalized to its retrieved chunk."
                        warnings.append(f"Candidate {candidate.candidate_id} had {message}")
                        if self.tracer:
                            self.tracer.event(
                                "critic", "retrieved_citation_repaired", task_id=candidate.candidate_id
                            )
            return CriticResult(evaluations=evaluations, warnings=warnings)

    def _trace_candidate_skip(self, candidate: CandidateIdea, reason: str) -> None:
        if self.tracer:
            self.tracer.event(
                "critic",
                f"candidate_skipped_{reason}",
                task_id=candidate.candidate_id,
            )

    @staticmethod
    def _invalid_assessment_category(message: str) -> str:
        """Map fixed validation messages to safe, bounded warning categories."""

        if "evidence outside its retrieved context" in message:
            return "citation"
        if "exactly the configured" in message:
            return "assessment_shape"
        return "consistency"

    @staticmethod
    def _fill_unambiguous_chunk_ids(
        assessment: CandidateAssessment, evidence: list[RetrievedChunk]
    ) -> bool:
        """Fill a missing chunk ID only when its source has one retrieved chunk."""

        chunks_by_source: dict[str, list[str]] = {}
        for hit in evidence:
            chunks_by_source.setdefault(hit.chunk.source_id, []).append(hit.chunk.chunk_id)
        repaired = False
        judgments = [*assessment.criteria.values(), *assessment.hard_gates.values()]
        for judgment in judgments:
            for reference in judgment.evidence:
                if reference.chunk_id is not None:
                    continue
                matching = chunks_by_source.get(reference.source_id, [])
                if len(matching) == 1:
                    reference.chunk_id = matching[0]
                    repaired = True
        return repaired

    @staticmethod
    def _repair_chunk_source_ids(
        assessment: CandidateAssessment, evidence: list[RetrievedChunk]
    ) -> bool:
        """Correct a wrong source ID only when the cited retrieved chunk is exact."""

        actual_sources = {hit.chunk.chunk_id: hit.chunk.source_id for hit in evidence}
        repaired = False
        judgments = [*assessment.criteria.values(), *assessment.hard_gates.values()]
        for judgment in judgments:
            for reference in judgment.evidence:
                actual_source = actual_sources.get(reference.chunk_id or "")
                if actual_source is not None and actual_source != reference.source_id:
                    reference.source_id = actual_source
                    repaired = True
        return repaired

    async def _retrieve(
        self,
        candidate: CandidateIdea,
        library: LibraryResult,
        rubric: EvaluationConfiguration,
    ) -> list[RetrievedChunk]:
        selected = await retrieve_candidate_evidence(self.retriever, candidate, library, rubric)
        token_count = sum(max(hit.chunk.token_count or 0, max(1, len(hit.chunk.text) // 4))
                          for hit in selected)
        if self.tracer:
            self.tracer.budget(
                "critic", "context_chunks", len(selected), rubric.max_context_chunks,
                task_id=candidate.candidate_id,
            )
            self.tracer.budget(
                "critic", "context_tokens_estimate", token_count,
                rubric.max_context_tokens, task_id=candidate.candidate_id,
            )
        return selected

    @staticmethod
    def _make_evaluation(
        candidate: CandidateIdea,
        assessment: CandidateAssessment,
        evidence: list[RetrievedChunk],
        rubric: EvaluationConfiguration,
    ) -> EvaluationResult:
        """Recompute scores from the rubric and reject unconfigured citations."""
        if set(assessment.criteria) != set(rubric.criteria):
            raise ValueError("judge must assess exactly the configured criteria")
        if set(assessment.hard_gates) != set(rubric.hard_gates):
            raise ValueError("judge must assess exactly the configured hard gates")
        permitted = {hit.chunk.chunk_id: hit.chunk.source_id for hit in evidence}

        def check_references(references: list[EvidenceReference]) -> None:
            for reference in references:
                if reference.chunk_id is None or permitted.get(reference.chunk_id) != reference.source_id:
                    raise ValueError("judge cited evidence outside its retrieved context")

        criteria = []
        for criterion_id, definition in rubric.criteria.items():
            judgment = assessment.criteria[criterion_id]
            check_references(judgment.evidence)
            criteria.append(
                CriterionScore(
                    criterion_id=criterion_id,
                    score=judgment.score,
                    weight=definition.weight,
                    weighted_score=round(judgment.score / 5 * definition.weight, 4),
                    rationale=judgment.rationale,
                    evidence=judgment.evidence,
                )
            )
        gates = []
        for gate_id in rubric.hard_gates:
            judgment = assessment.hard_gates[gate_id]
            check_references(judgment.evidence)
            gates.append(
                HardGateResult(
                    gate_id=gate_id,
                    passed=judgment.passed,
                    rationale=judgment.rationale,
                    evidence=judgment.evidence,
                )
            )
        failed = [f"{gate.gate_id}: {gate.rationale}" for gate in gates if not gate.passed]
        uncertainty = list(assessment.uncertainty)
        if any(gate.gate_id == "time_scope" and gate.passed for gate in gates):
            uncertainty.append(
                "Time fit is an estimate, not a delivery guarantee; confirm scope, "
                "dependencies, and available effort before starting."
            )
        return EvaluationResult(
            evaluation_id=f"eval:{candidate.candidate_id}",
            candidate_id=candidate.candidate_id,
            criteria=criteria,
            hard_gates=gates,
            gate_passed=not failed,
            total_score=round(sum(item.weighted_score for item in criteria), 4),
            rejection_reasons=failed,
            uncertainty=list(dict.fromkeys(uncertainty)),
            revised_candidate=assessment.revised_candidate,
            evaluated_at=datetime.now(timezone.utc),
        )
