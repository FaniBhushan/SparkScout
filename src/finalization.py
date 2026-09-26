"""Turn selected evaluations into complete proposals with checked citations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Protocol

from src.models import (
    CandidateIdea,
    EvaluationResult,
    FinalProposal,
    InputRequest,
    OrchestrationResult,
    ProposalDraft,
)
from src.models.common import EvidenceStance
from src.models.source_record import SourceChunk


class ProposalWriter(Protocol):
    """Produce narrative fields without controlling rank or numeric scores."""

    async def draft(
        self,
        request: InputRequest,
        candidate: CandidateIdea,
        evaluation: EvaluationResult,
        sources: list[dict[str, object]],
        chunks: list[dict[str, object]],
    ) -> ProposalDraft: ...


class ProposalCoverageError(ValueError):
    """A selected candidate lacks cited Library evidence for a proposal."""


async def finalize_proposals(
    request: InputRequest,
    result: OrchestrationResult,
    writer: ProposalWriter,
) -> OrchestrationResult:
    """Draft each finalist while keeping selection and score fields deterministic."""

    if not result.finalist_candidate_ids:
        return result
    candidates = {candidate.candidate_id: candidate for candidate in result.scout.candidates}
    evaluations = {evaluation.candidate_id: evaluation for evaluation in result.critic.evaluations}
    rankings = {row.candidate_id: row for row in result.ranking}
    sources = {source.source_id: source for source in result.source_manifest}
    chunks = {chunk.chunk_id: chunk for chunk in result.library.chunks}
    proposals = []
    for candidate_id in result.finalist_candidate_ids:
        evaluation = evaluations[candidate_id]
        candidate = evaluation.revised_candidate or candidates[candidate_id]
        if candidate.candidate_id != candidate_id:
            raise ValueError("revised candidate ID must match the selected finalist")

        # Only evidence actually cited during discovery or scoring reaches the
        # proposal model. This bounds context and prevents unrelated source use.
        references = list(candidate.evidence)
        for criterion in evaluation.criteria:
            references.extend(criterion.evidence)
        for gate in evaluation.hard_gates:
            references.extend(gate.evidence)
        chunk_ids = {reference.chunk_id for reference in references if reference.chunk_id}
        if not chunk_ids:
            raise ProposalCoverageError(
                f"finalist {candidate_id!r} has no cited Library chunks"
            )
        source_ids = {reference.source_id for reference in references}
        for chunk_id in chunk_ids:
            chunk = chunks.get(chunk_id)
            if chunk is None:
                raise ValueError(f"finalist {candidate_id!r} cites an unknown chunk")
            source_ids.add(chunk.source_id)
        for reference in references:
            if (reference.chunk_id is not None
                    and chunks[reference.chunk_id].source_id != reference.source_id):
                raise ValueError(f"finalist {candidate_id!r} has a mismatched chunk citation")
        missing_sources = source_ids - sources.keys()
        if missing_sources:
            raise ValueError(f"finalist {candidate_id!r} cites missing source records")
        source_context = [
            sources[source_id].model_dump(
                mode="json",
                include={
                    "source_id", "source_type", "title", "canonical_url",
                    "abstract_or_snippet", "license_access_note",
                },
                exclude_none=True,
            )
            for source_id in sorted(source_ids)
        ]
        chunk_context = [
            {"source_id": chunks[chunk_id].source_id,
             "chunk_id": chunk_id, "text": chunks[chunk_id].text}
            for chunk_id in sorted(chunk_ids)
        ]
        draft = await writer.draft(request, candidate, evaluation, source_context, chunk_context)
        draft = ProposalDraft.model_validate(draft)
        _validate_draft_citations(draft, source_ids, chunk_ids, chunks)

        row = rankings[candidate_id]
        proposals.append(FinalProposal(
            proposal_id=f"proposal:{candidate_id}",
            candidate_id=candidate_id,
            rank=row.rank,
            title=candidate.title,
            problem_statement=candidate.problem_statement,
            target_users=candidate.target_users,
            proposed_artifact=candidate.proposed_outcome,
            why_it_matters=candidate.why_it_matters,
            gap_or_differentiation=draft.gap_or_differentiation,
            scoped_mvp=draft.scoped_mvp,
            non_goals=draft.non_goals,
            required_data=draft.required_data,
            required_tools=draft.required_tools,
            access_assumptions=draft.access_assumptions,
            technical_approach=draft.technical_approach,
            alternatives=draft.alternatives,
            criterion_scores=evaluation.criteria,
            total_score=evaluation.total_score,
            risks=draft.risks,
            unknowns=draft.unknowns,
            first_kill_test=draft.first_kill_test,
            evaluation_plan=draft.evaluation_plan,
            citations=draft.citations,
        ))

    # Revalidate the complete output so proposal/ranking consistency survives
    # serialization and future callers cannot silently replace scored fields.
    data = result.model_dump(mode="python")
    data["final_proposals"] = proposals
    data["completed_at"] = datetime.now(timezone.utc)
    return OrchestrationResult.model_validate(data)


def _validate_draft_citations(
    draft: ProposalDraft,
    source_ids: set[str],
    chunk_ids: set[str],
    chunks: Mapping[str, SourceChunk],
) -> None:
    """Restrict citations to prompt evidence and require positive chunk support."""

    has_supporting_chunk = False
    for claim in draft.citations:
        for reference in claim.references:
            if reference.source_id not in source_ids:
                raise ValueError("proposal cites a source outside its supplied evidence")
            if reference.chunk_id is not None:
                if (reference.chunk_id not in chunk_ids
                        or chunks[reference.chunk_id].source_id != reference.source_id):
                    raise ValueError("proposal cites a chunk outside its supplied evidence")
                if reference.stance == EvidenceStance.SUPPORTING:
                    has_supporting_chunk = True
    if not has_supporting_chunk:
        raise ValueError("proposal requires at least one supporting chunk citation")
