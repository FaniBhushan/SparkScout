"""Present failed candidates and record deliberate evidence-risk decisions."""

import streamlit as st

from src.evaluation.review import record_candidate_review
from src.guardrails import safe_error_message
from src.models import OrchestrationResult


def candidate_review_view(result: OrchestrationResult) -> OrchestrationResult:
    """Review existing outputs in memory; widget clicks never start research."""

    failed = [item for item in result.critic.evaluations if not item.gate_passed]
    if not failed:
        return result
    st.subheader("Candidates needing review")
    st.caption(
        "These ideas did not pass automatic recommendation. You can keep an idea "
        "with an evidence gap if all other checks passed. Your decision is saved "
        "in this session and in Download run JSON. Keeping an idea makes no model "
        "calls and does not generate a final proposal."
    )
    candidates = {item.candidate_id: item for item in result.scout.candidates}
    for evaluation in failed:
        candidate = candidates[evaluation.candidate_id]
        eligible = evaluation.can_accept_evidence_risk
        label = "Needs your review" if eligible else "Blocked by other requirements"
        with st.expander(f"{candidate.title} — {label}", expanded=True):
            st.text(candidate.problem_statement)
            st.text("Proposed outcome: " + candidate.proposed_outcome)
            st.caption(f"Score: {evaluation.total_score:.1f}/100. A high score does not clear a failed gate.")
            for caveat in dict.fromkeys([*evaluation.rejection_reasons, *evaluation.uncertainty]):
                st.warning(caveat)
            if candidate.evaluation_method:
                st.text("Proposed test: " + candidate.evaluation_method)
            if not eligible:
                st.info("Resolve the failed requirements before selecting this idea.")
                continue

            key = f"candidate-review:{result.run_id}:{candidate.candidate_id}"
            acknowledged = st.checkbox(
                "I understand the evidence gaps and uncertainty shown above",
                key=f"{key}:acknowledge",
            )
            decision = None
            if st.button("Keep this idea despite the evidence gap", key=f"{key}:accept",
                         disabled=not acknowledged):
                decision = "accepted_risk"
            if st.button("Do not select this idea", key=f"{key}:decline"):
                decision = "declined"
            if decision is not None:
                try:
                    result = record_candidate_review(
                        result, candidate.candidate_id, decision, acknowledged=acknowledged,
                    )
                    st.session_state.result = result
                except ValueError as error:
                    st.error(safe_error_message(error))
            latest = next((item for item in reversed(result.review_decisions)
                           if item.candidate_id == candidate.candidate_id), None)
            if latest is not None:
                if latest.decision == "accepted_risk":
                    st.info("User accepted the risk. The evidence gate remains failed; this is your selection.")
                else:
                    st.caption("Your decision: do not select this idea.")
    return result
