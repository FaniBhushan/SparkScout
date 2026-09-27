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
from src.guardrails.proposals import ProposalVerificationError, verified_draft
from src.runtime.budgets import BudgetExceeded
from src.llm.client import ModelResponseError
from src.guardrails import SensitiveContentError, safe_error_message
from pydantic import ValidationError
from src.workers.dependency_evidence import dependency_passages


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
    verifier=None,
    *,
    allow_provisional_narrative: bool = False,
    tracer=None,
) -> OrchestrationResult:
    """Fill finalist slots in rank order while preserving earlier successful work.

    A candidate that cannot produce a verified proposal is recorded as a failure,
    then the next eligible candidate is tried. Scores and gate outcomes are never
    modified by proposal writing or citation verification.
    """

    if not any(row.gate_passed for row in result.ranking):
        return result
    candidates = {candidate.candidate_id: candidate for candidate in result.scout.candidates}
    evaluations = {evaluation.candidate_id: evaluation for evaluation in result.critic.evaluations}
    rankings = {row.candidate_id: row for row in result.ranking}
    sources = {source.source_id: source for source in result.source_manifest}
    chunks = {chunk.chunk_id: chunk for chunk in result.library.chunks}
    proposals = list(result.final_proposals)
    warnings = list(result.warnings)
    failures = dict(result.proposal_failures)
    budget_exhausted = result.budget_exhausted
    retained_ids = {proposal.candidate_id for proposal in proposals}
    eligible = sorted((row for row in result.ranking if row.gate_passed),
                      key=lambda row: (row.rank, row.candidate_id))
    for row in eligible:
        if len(proposals) >= request.finalist_count:
            break
        candidate_id = row.candidate_id
        if candidate_id in retained_ids or candidate_id in failures:
            continue
        if tracer:
            tracer.event("finalization", "candidate_attempted", task_id=candidate_id)
        evaluation = evaluations[candidate_id]
        candidate = evaluation.revised_candidate or candidates[candidate_id]
        if candidate.candidate_id != candidate_id:
            raise ValueError("revised candidate ID must match the selected finalist")

        # Only evidence cited during discovery or scoring reaches proposal writing.
        # Discovery references are filtered against Library because Scout and
        # Library search independently; an unseen passage is not evaluated evidence.
        discovery = [reference for reference in candidate.evidence
                     if reference.source_id in sources and (reference.chunk_id is None
                         or (reference.chunk_id in chunks
                             and chunks[reference.chunk_id].source_id == reference.source_id))]
        if len(discovery) != len(candidate.evidence):
            warnings.append(f"Candidate {candidate_id} has discovery citations unavailable in Library; "
                            "its proposal uses the available evaluated evidence.")
            candidate = candidate.model_copy(update={"evidence": discovery})
        references = list(discovery)
        for criterion in evaluation.criteria:
            references.extend(criterion.evidence)
        for gate in evaluation.hard_gates:
            references.extend(gate.evidence)
        chunk_ids = {reference.chunk_id for reference in references if reference.chunk_id}
        if not chunk_ids:
            failures[candidate_id] = "no cited Library chunks"
            warnings.append(f"Candidate {candidate_id} has no cited Library chunks for a proposal.")
            continue
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
        # A Critic score need not cite every access passage it read. Give the
        # writer bounded dependency context too; the verifier still checks it.
        for chunk in dependency_passages(candidate.required_data, result.library.chunks,
                                         excluded=chunk_ids):
            if chunk.source_id in sources:
                chunk_ids.add(chunk.chunk_id)
                source_ids.add(chunk.source_id)
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
             "source_title": sources[chunks[chunk_id].source_id].title,
             "chunk_id": chunk_id, "text": chunks[chunk_id].text}
            for chunk_id in sorted(chunk_ids)
        ]
        audit = None
        try:
            if verifier is not None:
                draft, audit = await verified_draft(
                    request, candidate, evaluation, source_context, chunk_context, writer, verifier,
                    allow_provisional_narrative=allow_provisional_narrative,
                )
            else:
                draft = ProposalDraft.model_validate(await writer.draft(
                    request, candidate, evaluation, source_context, chunk_context,
                ))
            _validate_draft_citations(draft, source_ids, chunk_ids, chunks)
        except SensitiveContentError:
            raise
        except BudgetExceeded:
            # Keep sources and assessments even when the first draft cannot
            # finish. Do not spend a recovery call after a budget stop.
            budget_exhausted = True
            warnings.append("Remaining proposal attempts stopped at the shared budget limit.")
            break
        except (ProposalVerificationError, ValidationError, ModelResponseError, ValueError) as error:
            failures[candidate_id] = safe_error_message(error)
            warnings.append(f"Candidate {candidate_id} needs evidence review; its draft was withheld. "
                            + safe_error_message(error))
            if tracer:
                tracer.event("finalization", "candidate_rejected_try_next", task_id=candidate_id)
            continue
        if audit and audit.caveated_fields:
            warnings.append(f"Candidate {candidate_id} uses unverified narrative hypotheses after "
                            "one correction; review the marked fields before choosing it.")

        row = rankings[candidate_id]
        proposals.append(FinalProposal(
            proposal_id=f"proposal:{candidate_id}",
            candidate_id=candidate_id,
            rank=row.rank,
            title=candidate.title,
            problem_statement=draft.problem_statement or candidate.problem_statement,
            target_users=candidate.target_users,
            proposed_artifact=candidate.proposed_outcome,
            why_it_matters=draft.why_it_matters or candidate.why_it_matters,
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
            unknowns=list(dict.fromkeys([*draft.unknowns, *evaluation.uncertainty])),
            first_kill_test=draft.first_kill_test,
            evaluation_plan=draft.evaluation_plan,
            citations=draft.citations,
            evidence_audit=audit,
        ))

    # Revalidate the complete output so proposal/ranking consistency survives
    # serialization and future callers cannot silently replace scored fields.
    data = result.model_dump(mode="python")
    data["final_proposals"] = proposals
    data["finalist_candidate_ids"] = [proposal.candidate_id for proposal in proposals]
    data["warnings"] = warnings
    data["proposal_failures"] = failures
    data["budget_exhausted"] = budget_exhausted
    data["status"] = ("completed" if len(proposals) >= request.finalist_count
                      else "partial" if proposals else "insufficient_coverage")
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
