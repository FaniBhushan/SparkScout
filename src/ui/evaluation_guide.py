"""Plain-language evaluation help shown to users in configuration and results."""

from __future__ import annotations

import streamlit as st


CRITERIA_HELP = {
    "problem_value": {
        "label": "Problem value",
        "definition": "How worthwhile it would be to solve the stated problem.",
        "example": "A tool that could save time across a recurring workflow may have high value.",
        "high_low": "High: a meaningful outcome for users. Low: a small or unclear benefit.",
    },
    "real_world_pain_point": {
        "label": "Real-world pain point",
        "definition": "Whether identifiable people face this difficulty in real life today.",
        "example": "Look for documented recurring trouble, current workarounds, or their costs.",
        "high_low": "High: strong evidence of a real recurring difficulty. Low: mostly hypothetical need.",
    },
    "evidence_quality": {
        "label": "Evidence quality",
        "definition": "How reliable and directly relevant the available evidence is.",
        "example": "A source that directly measures the relevant setting is stronger than a broad mention.",
        "high_low": "High: relevant, credible, and clear about limits. Low: indirect, weak, or unclear.",
    },
    "novelty": {
        "label": "Novelty and differentiation",
        "definition": "How clearly the idea differs from existing work or addresses an open gap.",
        "example": "A project may adapt a known method to a distinct user, setting, or constraint.",
        "high_low": "High: a supported and specific distinction. Low: close to existing work without a clear gap.",
    },
    "feasibility": {
        "label": "Feasibility",
        "definition": "How achievable the proposed work is with the available time and skills.",
        "example": "A small prototype using accessible tools is easier to complete than a field deployment.",
        "high_low": "High: scoped to available time and skills. Low: depends on substantial or unavailable work.",
    },
    "data_tool_availability": {
        "label": "Data and tool availability",
        "definition": "Whether required data and tools can be accessed and used as proposed.",
        "example": "Check access conditions and licenses for a dataset before making it a dependency.",
        "high_low": "High: suitable permitted resources are identified. Low: access is missing or uncertain.",
    },
    "technical_depth": {
        "label": "Technical depth",
        "definition": "Whether the project has a meaningful technical method and engineering challenge.",
        "example": "Comparing two suitable methods and explaining the trade-offs adds technical substance.",
        "high_low": "High: appropriate methods and real technical choices. Low: little technical work or a mismatched method.",
    },
    "evaluation_clarity": {
        "label": "Evaluation clarity",
        "definition": "How clearly the team can test whether the project works.",
        "example": "Name a baseline, measurable outcome, and test data before building.",
        "high_low": "High: a concrete, measurable test. Low: success is described only in vague terms.",
    },
    "constraint_fit": {
        "label": "User constraint fit",
        "definition": "How well the idea respects the user's stated limits and exclusions.",
        "example": "A public-data-only request rules out a plan that requires private data.",
        "high_low": "High: fits the stated limits. Low: depends on a resource or activity the user ruled out.",
    },
    "delivery_risk": {
        "label": "Delivery risk",
        "definition": "The chance that dependencies or practical obstacles prevent delivery.",
        "example": "A project needing unavailable hardware has a delivery obstacle.",
        "high_low": "High score means LOW delivery risk. Low score means greater risk of not delivering.",
    },
}

RUBRIC_PRESET_HELP = {
    "balanced": "Balances user value, evidence, feasibility, novelty, and evaluation.",
    "feasibility-first": "Gives more weight to achievable scope and available data and tools.",
    "innovation-first": "Gives more weight to novelty and technical depth.",
    "evidence-first": "Gives more weight to evidence quality and a clear evaluation method.",
}

SEARCH_PRESET_HELP = {
    "balanced": "General-purpose search with a moderate recency window.",
    "academic": "Allows an older publication window for scholarly and foundational work.",
    "build-oriented": "Favors more recent sources useful for implementation planning.",
}


def criterion_help_text(criterion_id: str) -> str:
    """Return the same short definition, example, and score interpretation everywhere."""

    item = CRITERIA_HELP[criterion_id]
    return (
        f"{item['definition']}\n\nExample: {item['example']}\n\n"
        f"{item['high_low']}"
    )


def render_criteria_guide(*, title: str = "How the evaluation criteria work") -> None:
    """Show keyboard- and touch-accessible criterion tips in compact popovers."""

    with st.expander(title):
        st.caption(
            "Each criterion is scored from 0 to 5. The weights determine how much "
            "those scores affect the 0–100 ranking. Problem value is the potential "
            "benefit of solving a problem; real-world pain point is evidence that "
            "people actually experience it. These scores do not replace hard gates."
        )
        for criterion_id, item in CRITERIA_HELP.items():
            label_col, info_col = st.columns([8, 1])
            label_col.write(item["label"])
            with info_col.popover("ⓘ", help=f"Help for {item['label']}"):
                st.markdown(f"**{item['label']}**")
                st.write(item["definition"])
                st.write("Example: " + item["example"])
                st.write(item["high_low"])
        st.caption(
            "A high delivery-risk score means lower risk. A failed hard gate can "
            "block automatic recommendation even when the weighted score is high."
        )
