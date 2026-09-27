"""Deterministic structural checks; semantic quality requires human review."""

from src.models import OrchestrationResult
from src.models.source_record import RetrievalStatus

from .cases import ResearchCase


def check_result(case: ResearchCase, result: OrchestrationResult) -> dict[str, bool | None]:
    """Compare actual outputs with gold expectations without changing the request."""
    expected_status = {"success": "completed", "insufficient_coverage": "insufficient_coverage"}.get(
        case.expected["outcome"], case.expected["outcome"]
    )
    sources = {source.source_id for source in result.source_manifest}
    chunks = {chunk.chunk_id: chunk.source_id for chunk in result.library.chunks}
    references = [ref for proposal in result.final_proposals
                  for claim in proposal.citations for ref in claim.references]
    rubric = result.prepared_run.evaluation
    evaluations = result.critic.evaluations
    usable_source_count = sum(
        source.retrieval_status in (RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL)
        for source in result.source_manifest
    )
    scores_valid = all(
        {score.criterion_id for score in item.criteria} == set(rubric.criteria)
        and len(item.criteria) == len(rubric.criteria)
        and all(score.weight == rubric.criteria[score.criterion_id].weight
                and abs(score.weighted_score - score.score / 5 * score.weight) < 0.01
                for score in item.criteria)
        and abs(item.total_score - sum(score.weighted_score for score in item.criteria)) < 0.01
        and {gate.gate_id for gate in item.hard_gates} == set(rubric.hard_gates)
        and item.gate_passed == all(gate.passed for gate in item.hard_gates)
        for item in evaluations
    )
    ordered = sorted(evaluations, key=lambda item: (not item.gate_passed, -item.total_score, item.candidate_id))
    finalists = [item.candidate_id for item in ordered if item.gate_passed][:case.expected_request.finalist_count]
    target = case.expected.get("finalist_count", 0)
    # A requested count is a target; preserve usable partial outputs. Exact
    # attainment is reported separately, never manufactured with synthetic ideas.
    count_ok = (0 < len(result.final_proposals) <= target if expected_status == "completed"
                else len(result.final_proposals) == target)
    return {
        "expected_outcome": (result.status in ("completed", "partial")
                             if expected_status == "completed" else result.status == expected_status),
        "proposal_count": count_ok,
        "required_source_types": set(case.expected.get("required_source_types", [])) <= {
            source.source_type for source in result.source_manifest},
        "minimum_source_count": usable_source_count >= result.prepared_run.search.minimum_source_count,
        "citation_integrity": (all(ref.source_id in sources and (
            ref.chunk_id is None or chunks.get(ref.chunk_id) == ref.source_id
        ) for ref in references) and all(proposal.citations for proposal in result.final_proposals))
            if result.final_proposals else None,
        "scoring_consistency": scores_valid if evaluations else None,
        "ranking_consistency": [row.candidate_id for row in result.ranking] == [item.candidate_id for item in ordered]
            and result.finalist_candidate_ids == finalists
            and all(row.rank == index and row.total_score == item.total_score
                    and row.gate_passed == item.gate_passed
                    for index, (row, item) in enumerate(zip(result.ranking, ordered), 1)),
    }
