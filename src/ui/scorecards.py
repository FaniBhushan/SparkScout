"""Present score selections and evidence readiness without additional model calls."""

import streamlit as st

from .evaluation_guide import CRITERIA_HELP


def render_scorecards(result) -> None:
    """Expand the score finalists and retain every remaining idea for comparison."""
    selected = set(result.score_finalist_candidate_ids)
    candidates = {item.candidate_id: item for attempt in result.recovery_history
                  for item in attempt.previous_candidates}
    candidates.update({item.candidate_id: item for item in result.scout.candidates})
    evaluations = {item.candidate_id: item for attempt in result.recovery_history
                   for item in attempt.previous_evaluations}
    evaluations.update({item.candidate_id: item for item in result.critic.evaluations})
    proposals = {item.candidate_id: item for item in result.final_proposals}
    ordered = result.score_ranking
    target = (result.prepared_run.request.finalist_count if result.prepared_run
              else result.requested_finalist_count)
    st.subheader(f"Top {target} finalists by weighted score")
    st.caption("Scores reflect your criterion weights. Review gate warnings and evidence before choosing an idea.")
    if len(selected) < target:
        st.warning(f"Only {len(selected)} candidates were scored; {target} finalists were requested.")
    for finalist in (True, False):
        rows = [row for row in ordered if (row.candidate_id in selected) == finalist]
        if not finalist and rows:
            st.subheader("Other candidate ideas")
        for row in rows:
            candidate = candidates.get(row.candidate_id)
            evaluation = evaluations[row.candidate_id]
            rank = row.rank
            title = candidate.title if candidate else row.candidate_id
            with st.expander(f"#{rank} {title} — {row.total_score:.1f}/100", expanded=finalist):
                if not finalist:
                    st.caption(f"Not a finalist: score rank {rank} is outside the requested top {target}. Ties use candidate ID.")
                if candidate:
                    st.markdown("**Proposal sketch**")
                    st.caption(
                        "A concept summary from Scout. It is not a verified detailed proposal; "
                        "review the gates and evidence caveats below."
                    )
                    st.text(candidate.problem_statement)
                    st.text("Target users: " + ", ".join(candidate.target_users))
                    st.text("Proposed outcome: " + candidate.proposed_outcome)
                    st.text("Why it matters: " + candidate.why_it_matters)
                    if candidate.evaluation_method:
                        st.text("Initial test: " + candidate.evaluation_method)
                    if candidate.required_data:
                        st.text("Required data: " + ", ".join(candidate.required_data))
                    if candidate.required_tools:
                        st.text("Required tools: " + ", ".join(candidate.required_tools))
                    if candidate.access_assumptions:
                        st.text("Access assumptions: " + ", ".join(candidate.access_assumptions))
                for gate in evaluation.hard_gates:
                    if not gate.passed:
                        st.warning(f"{gate.gate_id.replace('_', ' ')}: {gate.rationale}")
                for caveat in evaluation.uncertainty:
                    st.caption(caveat)
                st.dataframe([{
                    "Criterion": CRITERIA_HELP.get(score.criterion_id, {"label": score.criterion_id})["label"],
                    "Score / 5": score.score, "Weight %": score.weight,
                    "Contribution / 100": score.weighted_score, "Reason": score.rationale,
                } for score in evaluation.criteria], hide_index=True)
                proposal = proposals.get(row.candidate_id)
                if proposal is None:
                    reason = result.proposal_failures.get(row.candidate_id)
                    if reason:
                        st.warning("Detailed proposal withheld: " + reason)
                    elif not evaluation.gate_passed:
                        st.info("This scored idea remains visible. A detailed proposal was withheld because the gates above failed.")
                    elif result.budget_exhausted:
                        st.info("Detailed proposal unavailable: the run reached its budget limit.")
                    else:
                        st.caption("No detailed proposal was generated for this idea.")
                else:
                    st.text("MVP:\n" + "\n".join(proposal.scoped_mvp))
                    st.write("Evaluation:", proposal.evaluation_plan.model_dump(mode="json"))
                    for caveat in proposal.unknowns:
                        st.warning(caveat)
                    sources = {source.source_id: source for source in result.source_manifest}
                    for claim in proposal.citations:
                        st.text(claim.claim)
                        for reference in claim.references:
                            source = sources[reference.source_id]
                            st.caption(f"{source.title} · {source.canonical_url or source.source_id}")
    unscored = [item for item in result.scout.candidates if item.candidate_id not in evaluations]
    if unscored:
        with st.expander("Ideas without a score", expanded=not bool(ordered)):
            st.caption("These ideas could not be ranked. See the run warnings for coverage, budget, or assessment failures.")
            for candidate in unscored:
                st.markdown(f"**{candidate.title}**")
                st.text(candidate.problem_statement)
                st.text("Proposed outcome: " + candidate.proposed_outcome)
                st.text("Target users: " + ", ".join(candidate.target_users))
                st.caption("This idea could not be scored, so it is not ranked as a finalist.")
