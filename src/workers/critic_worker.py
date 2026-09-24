"""Critic worker: evaluate candidates against evidence and a rubric."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Protocol

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
            for candidate in candidates:
                with (
                    self.tracer.span("candidate_evaluation", task_id=candidate.candidate_id)
                    if self.tracer
                    else nullcontext()
                ):
                    evidence = await self._retrieve(candidate, library, rubric)
                    if not evidence:
                        raise ValueError(
                            f"no relevant evidence for candidate {candidate.candidate_id!r}"
                        )
                    assessment = await self.judge.assess(request, candidate, evidence, rubric)
                    evaluations.append(
                        self._make_evaluation(candidate, assessment, evidence, rubric)
                    )
            return CriticResult(evaluations=evaluations)

    async def _retrieve(
        self,
        candidate: CandidateIdea,
        library: LibraryResult,
        rubric: EvaluationConfiguration,
    ) -> list[RetrievedChunk]:
        allowed = {chunk.chunk_id: chunk for chunk in library.chunks}
        hits: dict[str, RetrievedChunk] = {}
        for definition in rubric.criteria.values():
            query = f"{candidate.title} {candidate.problem_statement} {definition.retrieval_focus}"
            results = await self.retriever.search(query, rubric.retrieval_top_k)
            if len(results) > rubric.retrieval_top_k:
                raise ValueError("retriever exceeded retrieval_top_k")
            for hit in results:
                if allowed.get(hit.chunk.chunk_id) != hit.chunk:
                    raise ValueError("retriever returned a chunk outside the Library result")
                old = hits.get(hit.chunk.chunk_id)
                if old is None or hit.score > old.score:
                    hits[hit.chunk.chunk_id] = hit

        selected = []
        token_count = 0
        for hit in sorted(hits.values(), key=lambda item: (-item.score, item.chunk.chunk_id)):
            count = max(hit.chunk.token_count or 0, max(1, len(hit.chunk.text) // 4))
            if len(selected) >= rubric.max_context_chunks:
                break
            if token_count + count > rubric.max_context_tokens:
                continue
            selected.append(hit)
            token_count += count
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
        return EvaluationResult(
            evaluation_id=f"eval:{candidate.candidate_id}",
            candidate_id=candidate.candidate_id,
            criteria=criteria,
            hard_gates=gates,
            gate_passed=not failed,
            total_score=round(sum(item.weighted_score for item in criteria), 4),
            rejection_reasons=failed,
            uncertainty=assessment.uncertainty,
            revised_candidate=assessment.revised_candidate,
            evaluated_at=datetime.now(timezone.utc),
        )
