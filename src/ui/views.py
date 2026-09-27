"""Review and result views for the Streamlit interface."""

from __future__ import annotations

import streamlit as st

from src.guardrails import SensitiveContentError, check_privacy, safe_error_message
from src.models import PromptInterpretationDraft
from .candidate_review import candidate_review_view
from .evaluation_guide import render_criteria_guide
from .scorecards import render_scorecards


def _show_draft(draft: PromptInterpretationDraft, prompt: str) -> None:
    if draft.original_prompt != prompt:
        st.warning("The prompt changed. Draft it again before previewing.")
        return
    st.subheader("Review proposed fields")
    for warning in draft.warnings:
        st.warning(warning)
    suggestions = draft.suggestions
    for section in ("request", "search", "evaluation"):
        for field, value in getattr(suggestions, section).model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        ).items():
            path = f"{section}.{field}"
            unsupported = any(issue.kind == "unsupported" and issue.path == path for issue in draft.issues)
            uncertain = path in suggestions.uncertain_paths
            st.checkbox(
                f"{path}: {value}", key=f"accept:{path}",
                disabled=unsupported or uncertain or path == "search.allow_other_domain",
                help="Uncertain or unsupported values must be entered explicitly in the controls."
                if unsupported or uncertain else None,
            )
    for index, issue in enumerate(draft.issues):
        st.warning(f"{issue.kind}: {issue.message}")
        st.checkbox("I reviewed this issue", key=f"ack:{index}")
    st.caption("Unchecked suggestions are ignored. Edited controls override accepted suggestions.")


def _result_view(result) -> None:
    try:
        for warning in check_privacy(result):
            st.warning(warning)
    except SensitiveContentError as error:
        st.error(safe_error_message(error))
        return
    st.subheader("Run result")
    st.write(f"Detailed proposal status: {result.status} · Mode: {result.mode} · Run ID: {result.run_id}")
    render_criteria_guide(title="Understand the evaluation scores")
    st.json(result.budget_usage.model_dump(mode="json") if result.budget_usage else {})
    for warning in result.warnings:
        st.warning(warning)
    render_scorecards(result)
    result = candidate_review_view(result)
    with st.expander("Selected source receipts", expanded=False):
        st.dataframe([
            {
                "source_id": source.source_id,
                "provider": source.provider,
                "source_type": source.source_type,
                "title": source.title,
                "url": str(source.canonical_url) if source.canonical_url else "",
            }
            for source in result.source_manifest
        ], hide_index=True)
    with st.expander("Configuration and provenance"):
        st.json(result.prepared_run.model_dump(mode="json") if result.prepared_run else {})
    st.download_button("Download run JSON", result.model_dump_json(indent=2),
                       file_name=f"scoutspark-{result.run_id}.json", mime="application/json")
