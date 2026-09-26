"""Auditable output of one sequential or parallel coordinator run."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from .common import ContractModel, EvidenceStance, Identifier, NonEmptyText
from .critic_result import CriticResult
from .final_proposal import FinalProposal
from .library_result import LibraryResult
from .run_configuration import PreparedRun
from .run_budget import RunBudgetUsage
from .scout_result import ScoutResult
from .source_record import SourceRecord


class RankedCandidate(ContractModel):
    candidate_id: Identifier
    evaluation_id: Identifier
    rank: int = Field(ge=1)
    total_score: float = Field(ge=0, le=100)
    gate_passed: bool


class RetrievalIndexInfo(ContractModel):
    """Auditable settings for the temporary index used by one run."""

    index_id: Identifier
    backend: Literal["hybrid_tfidf_in_memory"] = "hybrid_tfidf_in_memory"
    backend_version: Literal["1"] = "1"
    embedding_model: Literal["local_tfidf"] = "local_tfidf"
    embedding_version: Literal["1"] = "1"
    indexed_chunk_count: PositiveInt
    corpus_chars: PositiveInt
    index_bytes_estimate: PositiveInt
    chunk_size_chars: PositiveInt
    chunk_overlap_chars: int = Field(ge=0)
    max_corpus_chars: PositiveInt
    max_chunks: PositiveInt
    max_index_bytes: PositiveInt
    retrieval_top_k: PositiveInt
    max_context_chunks: PositiveInt
    max_context_tokens: PositiveInt
    retention: Literal["run_only"] = "run_only"


class OrchestrationResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    mode: Literal["sequential", "parallel"]
    status: Literal["completed", "insufficient_coverage"]
    scout: ScoutResult
    library: LibraryResult
    critic: CriticResult
    retrieval_index: RetrievalIndexInfo | None = None
    prepared_run: PreparedRun | None = None
    budget_usage: RunBudgetUsage | None = None
    final_proposals: list[FinalProposal] = Field(default_factory=list)
    source_manifest: list[SourceRecord] = Field(default_factory=list)
    ranking: list[RankedCandidate] = Field(default_factory=list)
    finalist_candidate_ids: list[Identifier] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
    completed_at: datetime

    @model_validator(mode="after")
    def validate_proposals(self) -> "OrchestrationResult":
        """Keep serialized proposals tied to this run's ranking and evidence."""

        if self.retrieval_index is not None and self.retrieval_index.index_id != f"{self.run_id}:library":
            raise ValueError("retrieval index ID must belong to this run")
        if not self.final_proposals:
            return self
        proposal_ids = [proposal.candidate_id for proposal in self.final_proposals]
        if proposal_ids != self.finalist_candidate_ids:
            raise ValueError("final proposals must match selected finalists in order")
        rows = {row.candidate_id: row for row in self.ranking}
        evaluations = {item.candidate_id: item for item in self.critic.evaluations}
        source_ids = {source.source_id for source in self.source_manifest}
        chunk_sources = {chunk.chunk_id: chunk.source_id for chunk in self.library.chunks}
        for proposal in self.final_proposals:
            row = rows.get(proposal.candidate_id)
            evaluation = evaluations.get(proposal.candidate_id)
            if row is None or evaluation is None:
                raise ValueError("final proposal has no selected ranking and evaluation")
            if proposal.rank != row.rank or abs(proposal.total_score - row.total_score) > 0.01:
                raise ValueError("final proposal rank and score must match the ranking")
            if proposal.criterion_scores != evaluation.criteria:
                raise ValueError("final proposal criterion scores must match Critic")
            supporting_chunk = False
            for claim in proposal.citations:
                for reference in claim.references:
                    if reference.source_id not in source_ids:
                        raise ValueError("final proposal cites a source outside the manifest")
                    if reference.chunk_id is not None:
                        if chunk_sources.get(reference.chunk_id) != reference.source_id:
                            raise ValueError("final proposal cites an unknown or mismatched chunk")
                        if reference.stance == EvidenceStance.SUPPORTING:
                            supporting_chunk = True
            if not supporting_chunk:
                raise ValueError("final proposal needs a supporting chunk citation")
        return self
