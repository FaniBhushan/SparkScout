"""Session state and reviewed-preview identity for the Streamlit UI."""

from __future__ import annotations

import json

import streamlit as st


def _initialize() -> None:
    state = st.session_state
    if "ui_values" not in state:
        state.ui_values = {
            "request.domain": "AI engineering",
            "request.time_limit_days": 30,
            "request.desired_candidate_count": 1,
            "request.finalist_count": 1,
        }
        state.ui_explicit = set(state.ui_values)
        state.policy_values = {
            "include_types": [], "exclude_types": [], "required_types": [],
            "max_records_by_type": {},
        }
    if "draft" not in state:
        state.draft = None
    if "preview" not in state:
        state.preview = None
    if "result" not in state:
        state.result = None


def _remember(path: str, key: str) -> None:
    st.session_state.ui_values[path] = st.session_state[key]
    st.session_state.ui_explicit.add(path)


def _fingerprint(prompt: str, data_mode: str, fixture_set: str | None) -> str:
    payload = {
        "values": st.session_state.ui_values,
        "explicit": sorted(st.session_state.ui_explicit),
        "prompt": prompt,
        "mode": data_mode,
        "fixture_set": fixture_set,
        "model": st.session_state.get("model_id", ""),
        "run_mode": st.session_state.get("run_mode", "sequential"),
        "accepted": sorted(_accepted_paths()),
        "acknowledged": sorted(_acknowledged_issues()),
        "cost_enabled": st.session_state.get("ui_cost_enabled", False),
        "pricing": [
            st.session_state.get("saved_pricing_input", 0.0),
            st.session_state.get("saved_pricing_output", 0.0),
        ],
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _accepted_paths() -> set[str]:
    return {
        key.removeprefix("accept:") for key, value in st.session_state.items()
        if key.startswith("accept:") and value
    }


def _acknowledged_issues() -> set[int]:
    return {
        int(key.removeprefix("ack:")) for key, value in st.session_state.items()
        if key.startswith("ack:") and value
    }


