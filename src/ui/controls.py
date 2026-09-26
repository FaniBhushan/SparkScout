"""Simple and Advanced Streamlit configuration controls."""

from __future__ import annotations

import streamlit as st

from .state import _remember


def _field(path: str, default: object, render, label: str, **kwargs):
    """Keep non-widget copies so Advanced choices survive hiding that mode."""

    key = f"control:{path}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state.ui_values.get(path, default)
    return render(label, key=key, on_change=_remember, args=(path, key), **kwargs)


def _policy_change(field: str, key: str) -> None:
    st.session_state.policy_values[field] = st.session_state[key]
    st.session_state.ui_values["search.source_policy"] = dict(st.session_state.policy_values)
    st.session_state.ui_explicit.add("search.source_policy")


def _policy_widget(field: str, render, label: str, **kwargs):
    key = f"policy:{field}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state.policy_values[field]
    return render(label, key=key, on_change=_policy_change, args=(field, key), **kwargs)


def _comma_change(path: str, key: str) -> None:
    st.session_state.ui_values[path] = [
        part.strip() for part in st.session_state[key].split(",") if part.strip()
    ]
    st.session_state.ui_explicit.add(path)


def _text_list(path: str, label: str) -> None:
    key = f"text:{path}"
    if key not in st.session_state:
        st.session_state[key] = ", ".join(st.session_state.ui_values.get(path, []))
    st.text_input(label, key=key, on_change=_comma_change, args=(path, key))


def _domain_control(domains: list[str]) -> None:
    options = ["Choose domain", *domains, "Other"]
    current = st.session_state.ui_values.get("request.domain", "")
    initial = current.replace(" ", "_").casefold()
    selected = initial if initial in domains else "Other" if current else "Choose domain"
    if "domain_choice" not in st.session_state:
        st.session_state.domain_choice = selected

    def change_domain() -> None:
        choice = st.session_state.domain_choice
        if choice in domains:
            st.session_state.ui_values["request.domain"] = choice.replace("_", " ")
            st.session_state.ui_explicit.add("request.domain")
            st.session_state.ui_values["search.allow_other_domain"] = False
        elif choice == "Choose domain":
            st.session_state.ui_values.pop("request.domain", None)
            st.session_state.ui_explicit.discard("request.domain")

    st.selectbox("Domain", options, key="domain_choice", on_change=change_domain)
    if st.session_state.domain_choice == "Other":
        _field("request.domain", "", st.text_input, "Other domain")
        _field("search.allow_other_domain", False, st.checkbox, "Allow approved all-domain providers")


def _simple_controls(catalog) -> None:
    st.subheader("Simple configuration")
    _domain_control(catalog.domains)
    _field("request.time_limit_days", 30, st.number_input, "Time available (days)", min_value=1)
    _text_list("request.interests", "Interests or subdomain (comma separated)")
    _field("search.preset", "balanced", st.selectbox, "Search preset", options=catalog.search_presets)
    _policy_widget(
        "include_types", st.multiselect, "Optional source types",
        options=catalog.source_types,
    )
    _field(
        "search.recency_days", None, st.selectbox, "Recency",
        options=[None, 365, 1095, 1825, 3650],
        format_func=lambda value: "Preset default" if value is None else f"Last {value} days",
    )
    _field(
        "evaluation.rubric_preset", catalog.default_rubric,
        st.selectbox, "Evaluation priority", options=catalog.rubric_presets,
    )
    st.caption("Other settings use the catalog defaults. Frozen fixtures are synthetic evidence only.")


def _advanced_controls(catalog) -> None:
    st.subheader("Advanced configuration")
    _field("search.provider_ids", [], st.multiselect, "Ready providers (empty = automatic)",
           options=catalog.providers)
    _field("search.content_types", [], st.multiselect, "Content types (empty = automatic)",
           options=catalog.content_types)
    if catalog.languages:
        _field("search.language", None, st.selectbox, "Document language (declared)",
               options=[None, *catalog.languages],
               format_func=lambda value: "Any" if value is None else value)
    _policy_widget("required_types", st.multiselect, "Required source types",
                   options=catalog.source_types)
    _policy_widget("exclude_types", st.multiselect, "Excluded source types",
                   options=catalog.source_types)
    _field("search.evidence_tiers", [], st.multiselect, "Evidence tiers (empty = all)",
           options=catalog.evidence_tiers)
    _field("search.fallback_policy", "skip_unavailable", st.selectbox,
           "Unavailable optional providers", options=["skip_unavailable", "fail_if_unavailable"])

    st.markdown("**Dates and search caps**")
    col1, col2 = st.columns(2)
    with col1:
        _field("search.published_from", None, st.date_input, "Published from", value=None)
    with col2:
        _field("search.published_to", None, st.date_input, "Published to", value=None)
    _field("search.limits", None, _limits_widget, "Query and source limits", catalog=catalog)
    caps = st.session_state.policy_values["max_records_by_type"]
    cap_type = st.selectbox("Per-type cap to set", ["None", *catalog.source_types])
    if cap_type != "None":
        key = f"cap:{cap_type}"
        if key not in st.session_state:
            st.session_state[key] = caps.get(cap_type, 0)

        def change_cap() -> None:
            value = st.session_state[key]
            if value:
                st.session_state.policy_values["max_records_by_type"][cap_type] = value
            else:
                st.session_state.policy_values["max_records_by_type"].pop(cap_type, None)
            st.session_state.ui_values["search.source_policy"] = dict(st.session_state.policy_values)
            st.session_state.ui_explicit.add("search.source_policy")

        st.number_input("Maximum records for this type (0 = preset)", min_value=0,
                        max_value=catalog.max_sources, key=key, on_change=change_cap)
    if caps:
        st.caption(f"Active per-type caps: {caps}")

    st.markdown("**Run budgets and retrieval**")
    _field("budgets.max_elapsed_seconds", float(catalog.default_elapsed_seconds), st.number_input,
           "Maximum run time (seconds)", min_value=1.0,
           max_value=float(catalog.max_elapsed_seconds))
    _field("budgets.max_model_tokens", catalog.default_model_tokens, st.number_input,
           "Maximum model tokens", min_value=1, max_value=catalog.max_model_tokens)
    _field("budgets.max_source_bytes", catalog.default_source_bytes, st.number_input,
           "Maximum normalized source bytes", min_value=1,
           max_value=catalog.max_source_bytes)
    _field("budgets.max_pdf_pages", catalog.default_pdf_pages, st.number_input,
           "Maximum uploaded PDF pages", min_value=1, max_value=catalog.max_pdf_pages)
    def change_cost_toggle() -> None:
        st.session_state.ui_cost_enabled = st.session_state.cost_enabled
        if st.session_state.cost_enabled:
            st.session_state.ui_values.setdefault("budgets.max_estimated_cost_usd", 1.0)
            st.session_state.ui_explicit.add("budgets.max_estimated_cost_usd")
        else:
            st.session_state.ui_explicit.discard("budgets.max_estimated_cost_usd")

    if "cost_enabled" not in st.session_state:
        st.session_state.cost_enabled = st.session_state.get("ui_cost_enabled", False)
    cost_enabled = st.checkbox("Enforce an estimated USD cost cap", key="cost_enabled",
                               on_change=change_cost_toggle)
    if cost_enabled:
        _field("budgets.max_estimated_cost_usd", 1.0, st.number_input,
               "Estimated cost cap (USD)", min_value=0.01,
               max_value=float(catalog.max_estimated_cost_usd), step=0.01)
        for label, name in (
            ("Input USD / million tokens", "pricing_input"),
            ("Output USD / million tokens", "pricing_output"),
        ):
            if name not in st.session_state:
                st.session_state[name] = st.session_state.get(f"saved_{name}", 0.0)

            def remember_pricing(widget_name: str = name) -> None:
                st.session_state[f"saved_{widget_name}"] = st.session_state[widget_name]

            st.number_input(label, min_value=0.0, key=name, on_change=remember_pricing)
        st.caption("Use trusted rates for the selected model. Estimates are not provider billing guarantees.")
    else:
        st.session_state.ui_explicit.discard("budgets.max_estimated_cost_usd")
    _field("evaluation.retrieval_top_k", catalog.default_retrieval_top_k,
           st.number_input, "Retrieval top-k per criterion",
           min_value=1, max_value=catalog.max_context_chunks)
    _field("request.desired_candidate_count", 1, st.number_input,
           "Candidate ideas", min_value=1, max_value=20)
    _field("request.finalist_count", 1, st.number_input,
           "Final proposals", min_value=1, max_value=5)

    st.markdown("**Exact scoring weights**")
    def change_weights_toggle() -> None:
        st.session_state.ui_custom_weights = st.session_state.custom_weights
        if st.session_state.custom_weights:
            preset = st.session_state.ui_values.get("evaluation.rubric_preset", catalog.default_rubric)
            st.session_state.ui_values.setdefault(
                "evaluation.weights", dict(catalog.rubric_weights[preset])
            )
            st.session_state.ui_explicit.add("evaluation.weights")
        else:
            st.session_state.ui_explicit.discard("evaluation.weights")

    if "custom_weights" not in st.session_state:
        st.session_state.custom_weights = st.session_state.get("ui_custom_weights", False)
    custom = st.checkbox("Use custom weights", key="custom_weights",
                         on_change=change_weights_toggle)
    if custom:
        preset = st.session_state.ui_values.get("evaluation.rubric_preset", catalog.default_rubric)
        default_weights = catalog.rubric_weights[preset]
        weights = dict(st.session_state.ui_values.get("evaluation.weights") or default_weights)
        for criterion_id, label in catalog.criteria_labels.items():
            key = f"weight:{criterion_id}"
            if key not in st.session_state:
                st.session_state[key] = weights[criterion_id]

            def change_weight(criterion: str = criterion_id, widget_key: str = key) -> None:
                current = dict(st.session_state.ui_values.get("evaluation.weights") or default_weights)
                current[criterion] = st.session_state[widget_key]
                st.session_state.ui_values["evaluation.weights"] = current
                st.session_state.ui_explicit.add("evaluation.weights")

            st.number_input(label, min_value=0, max_value=100, key=key,
                            on_change=change_weight)
        st.caption(f"Weight total: {sum((st.session_state.ui_values.get('evaluation.weights') or weights).values())}%")
    else:
        st.session_state.ui_explicit.discard("evaluation.weights")
    st.caption("Language filtering applies only to user-declared upload language. Live providers do not supply a verified document language. No remote pages are fetched.")


def _limits_widget(label: str, *, key: str, on_change, args, catalog):
    """Collect one complete SearchLimits object when any cap is changed."""

    preset = st.session_state.ui_values.get("search.preset", "balanced")
    current = st.session_state.ui_values.get("search.limits") or catalog.preset_limits[preset]
    values = {}
    for name, ceiling in (
        ("max_queries", catalog.max_queries),
        ("max_results_per_query", catalog.max_results_per_query),
        ("max_sources", catalog.max_sources),
    ):
        widget_key = f"limit:{name}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = current[name]

        def change_limit(field: str = name, changed_key: str = widget_key) -> None:
            limits = dict(st.session_state.ui_values.get("search.limits") or current)
            limits[field] = st.session_state[changed_key]
            st.session_state.ui_values["search.limits"] = limits
            st.session_state.ui_explicit.add("search.limits")

        values[name] = st.number_input(name.replace("_", " ").title(), min_value=1,
                                        max_value=ceiling, key=widget_key,
                                        on_change=change_limit)
    return values


def _prompt_text() -> str:
    prompt = st.text_area("Describe your capstone request", key="request_prompt", height=100)
    instructions = st.text_area("Optional search or scoring instructions", key="config_instructions", height=70)
    parts = [prompt.strip()]
    if instructions.strip():
        parts.append("Search and evaluation preferences: " + instructions.strip())
    return "\n\n".join(part for part in parts if part)


