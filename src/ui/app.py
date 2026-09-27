"""Compose the reviewed Streamlit research flow."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

from src.adapters import build_available_adapters
from src.adapters.frozen_fixture import DEFAULT_FIXTURE_ROOT
from src.application.service import run_prepared_research
from src.testing.demo import OfflineDemoClient
from src.guardrails import SensitiveContentError, input_advisories, safe_error_message
from src.llm.client import ModelPricing, OpenAITextClient
from src.llm.request_interpreter import LLMRequestInterpreter
from src.models import PreparedRun
from src.observability import RunTracer
from src.application.preflight import prepare_run
from .configuration import interface_catalog, submitted_from_controls
from .controls import _advanced_controls, _prompt_text, _simple_controls
from .state import _accepted_paths, _acknowledged_issues, _fingerprint, _initialize, _reset_search
from .views import _result_view, _show_draft


def main() -> None:
    st.set_page_config(page_title="ScoutSpark", layout="wide")
    _initialize()
    if st.session_state.ui_page == "results" and st.session_state.result is not None:
        st.title("Research results")
        back_col, new_col, _ = st.columns([1, 1, 5])
        if back_col.button("← Back to input"):
            st.session_state.ui_page = "configure"
            st.rerun()
        if new_col.button("Start new search", type="primary"):
            _reset_search()
            st.rerun()
        _result_view(st.session_state.result)
        return

    st.title("ScoutSpark")
    st.caption("Review the source plan and scoring weights before starting research.")

    data_mode = st.radio("Data mode", ["Offline demo", "Live sources"], horizontal=True,
                         key="data_mode")
    if st.session_state.get("last_data_mode") != data_mode:
        if data_mode == "Live sources":
            # These fields remain visible after switching modes. Do not remove
            # them from the reviewed values while leaving their widgets selected.
            st.session_state.ui_values["request.desired_candidate_count"] = 5
            st.session_state.ui_values["request.finalist_count"] = 2
        else:
            st.session_state.ui_values["request.desired_candidate_count"] = 5
            st.session_state.ui_values["request.finalist_count"] = 2
            st.session_state.ui_explicit.update({
                "request.domain", "request.time_limit_days",
                "request.desired_candidate_count", "request.finalist_count",
            })
        for path in ("request.desired_candidate_count", "request.finalist_count"):
            key = f"control:{path}"
            if key in st.session_state:
                st.session_state[key] = st.session_state.ui_values[path]
        st.session_state.last_data_mode = data_mode
    fixture_set = None
    upload_files = []
    upload_rights_confirmed = False
    upload_error = None
    if data_mode == "Offline demo":
        fixtures = sorted(path.name for path in Path(DEFAULT_FIXTURE_ROOT).iterdir() if path.is_dir())
        fixture_set = st.selectbox("Synthetic fixture set", fixtures)
        st.info("Fully offline demo: frozen synthetic sources and deterministic model responses. Not real-world evidence.")
    else:
        uploads = st.file_uploader("Your documents (.txt, .md, .pdf; up to 5)",
                                   type=["txt", "md", "pdf"], accept_multiple_files=True,
                                   key="source_uploads")
        if uploads:
            upload_language = st.selectbox("Language of uploaded documents (your declaration)",
                                           ["en", "de", "fr", "es"])
            upload_files = [(item.name, item.getvalue(), upload_language) for item in uploads]
            fingerprint = tuple(
                (name, hashlib.sha256(raw).hexdigest()) for name, raw, _ in upload_files
            )
            if st.session_state.get("upload_consent_fingerprint") != fingerprint:
                st.session_state.upload_consent_fingerprint = fingerprint
                st.session_state.upload_rights_confirmed = False
            st.info(
                "Upload terms: You confirm that you have the right to submit these files "
                "for analysis. Extracted text may be sent to the selected model provider. "
                "Run results may contain generated summaries or excerpts. Downloaded JSON "
                "omits stored upload snippets and source chunks. This confirmation does not "
                "verify a license."
            )
            upload_rights_confirmed = st.checkbox(
                "I agree to the upload terms", key="upload_rights_confirmed"
            )
            if not upload_rights_confirmed:
                upload_error = "Agree to the upload terms before previewing uploaded documents."
        else:
            st.session_state.upload_consent_fingerprint = None
            st.session_state.upload_rights_confirmed = False
    try:
        adapters = build_available_adapters(
            fixture_set=fixture_set, include_live=data_mode == "Live sources",
            upload_files=upload_files if upload_rights_confirmed else None,
            upload_rights_confirmed=upload_rights_confirmed,
        )
    except ValueError as error:
        upload_error = safe_error_message(error)
        adapters = build_available_adapters(
            fixture_set=fixture_set, include_live=data_mode == "Live sources"
        )
    upload_adapter = adapters.get("user_upload")
    if upload_adapter is not None:
        for warning in upload_adapter.warnings:
            st.warning(warning)
        st.session_state.ui_values["search.uploads"] = [
            item.model_dump(mode="python") for item in upload_adapter.manifest
        ]
        st.session_state.ui_explicit.add("search.uploads")
    else:
        st.session_state.ui_values.pop("search.uploads", None)
        st.session_state.ui_explicit.discard("search.uploads")
    if upload_error:
        st.warning(upload_error)
    if not adapters:
        st.error("No source adapters are ready. Configure credentials or choose Offline demo.")
        return
    catalog = interface_catalog(adapters)
    st.caption("Ready providers: " + ", ".join(catalog.providers))
    model_id = "offline-demo"
    if data_mode == "Live sources":
        model_id = st.text_input("OpenAI model ID", key="model_id")
        if not os.getenv("OPENAI_API_KEY"):
            st.warning("OPENAI_API_KEY is required to draft or run with a live model.")

    mode = st.radio("Configuration mode", ["Simple", "Advanced"], horizontal=True,
                    key="config_mode")
    st.session_state.ui_values["search.mode"] = mode.lower()
    if mode == "Advanced":
        st.session_state.ui_explicit.add("search.mode")
    with st.expander("Simple configuration", expanded=mode == "Simple"):
        _simple_controls(catalog)
    if mode == "Advanced":
        with st.expander("Advanced configuration", expanded=True):
            _advanced_controls(catalog)
    elif any(path.startswith(("budgets.", "search.content_types", "search.provider_ids",
                                   "search.language", "search.evidence_tiers",
                                   "search.published_", "evaluation.weights"))
             for path in st.session_state.ui_explicit):
        st.info("Advanced values are retained while Simple mode is shown. Reopen Advanced to edit them.")

    prompt = _prompt_text()
    input_error = None
    try:
        for warning in input_advisories({"prompt": prompt, "fields": st.session_state.ui_values}):
            st.warning(warning)
    except SensitiveContentError as error:
        input_error = safe_error_message(error)
        st.error(input_error)
    if st.button("Draft fields from prompt", disabled=(
        bool(input_error) or data_mode == "Offline demo" or not prompt
        or not model_id or not os.getenv("OPENAI_API_KEY")
    )):
        try:
            client = OpenAITextClient(model_id)
            for key in list(st.session_state):
                if key.startswith(("accept:", "ack:")):
                    del st.session_state[key]
            st.session_state.draft = asyncio.run(
                LLMRequestInterpreter(client).draft(prompt, adapters)
            )
            st.session_state.draft_providers = tuple(catalog.providers)
            st.session_state.preview = None
        except (ValueError, ValidationError, RuntimeError) as error:
            st.session_state.draft = None
            st.session_state.preview = None
            if isinstance(error, ValidationError):
                st.error(
                    "The model reply did not match the request fields. No search has started. "
                    "Try drafting again, or fill the fields directly."
                )
            else:
                st.error(safe_error_message(error))
    draft = st.session_state.draft
    if draft is not None and st.session_state.get("draft_providers") != tuple(catalog.providers):
        st.warning("Available sources changed. Draft the prompt again before previewing.")
        draft = None
    if draft is not None:
        _show_draft(draft, prompt)

    fingerprint = _fingerprint(prompt, data_mode, fixture_set)
    st.info(
        "Preview checks that your request and settings can run, then shows which "
        "sources, limits, evaluation weights, and budget will be used. It does not "
        "start research or call search providers or the model. Review the plan here "
        "before selecting Start research."
    )
    if st.button("Preview and validate configuration", help="Resolve and check the run plan before any research begins."):
        try:
            if upload_error or input_error:
                raise ValueError(upload_error or input_error)
            submitted = submitted_from_controls(
                st.session_state.ui_values,
                st.session_state.ui_explicit,
                prompt=prompt,
                draft=draft if draft and draft.original_prompt == prompt else None,
                accepted_paths=_accepted_paths(),
                acknowledged_issues=_acknowledged_issues(),
            )
            prepared = prepare_run(submitted, adapters)
            st.session_state.preview = (fingerprint, prepared)
        except (ValueError, ValidationError) as error:
            st.session_state.preview = None
            st.error(safe_error_message(error))

    preview = st.session_state.preview
    ready = preview is not None and preview[0] == fingerprint
    if ready:
        prepared: PreparedRun = preview[1]
        for warning in prepared.warnings:
            st.warning(warning)
        st.subheader("Resolved preview")
        st.write(
            f"{prepared.search.domain} · {prepared.submitted.search.preset} search · "
            f"{prepared.evaluation.preset} rubric · {len(prepared.search.providers)} provider(s)"
        )
        st.json({
            "providers": [provider.model_dump(mode="json") for provider in prepared.search.providers],
            "content_types": prepared.search.content_types,
            "source_types": sorted({item for provider in prepared.search.providers for item in provider.source_types}),
            "criterion_weights": {key: item.weight for key, item in prepared.evaluation.criteria.items()},
            "budgets": prepared.budgets.model_dump(mode="json"),
            "checksum": prepared.configuration_checksum,
        })
        with st.expander("Editable request and resolved details"):
            st.caption("Edit the controls above, then preview again to change these values.")
            st.json({
                "request": prepared.request.model_dump(mode="json"),
                "search": prepared.search.model_dump(mode="json"),
                "evaluation": prepared.evaluation.model_dump(mode="json"),
                "field_origins": prepared.field_origins,
            })
        st.download_button("Download reviewed config for CLI", prepared.submitted.model_dump_json(indent=2),
                           file_name="scoutspark-config.json", mime="application/json")
    elif preview is not None:
        st.info("Configuration changed. Preview again before starting.")

    run_mode = st.radio("Run mode", ["sequential", "parallel"], horizontal=True, key="run_mode")
    if ready and preview[1].budgets.max_estimated_cost_usd is not None and (
        st.session_state.get("saved_pricing_input", 0.0) <= 0
        or st.session_state.get("saved_pricing_output", 0.0) <= 0
    ):
        st.warning("A cost cap needs positive, trusted input and output rates before starting.")
    if st.button("Start research", type="primary", disabled=(
        not ready
        or bool(upload_error)
        or bool(input_error)
        or (data_mode == "Live sources" and (not model_id or not os.getenv("OPENAI_API_KEY")))
        or (ready and preview[1].budgets.max_estimated_cost_usd is not None and (
            st.session_state.get("saved_pricing_input", 0.0) <= 0
            or st.session_state.get("saved_pricing_output", 0.0) <= 0
        ))
    )):
        prepared = preview[1]
        pricing = None
        if prepared.budgets.max_estimated_cost_usd is not None:
            pricing = ModelPricing(
                st.session_state.get("saved_pricing_input", 0.0),
                st.session_state.get("saved_pricing_output", 0.0),
            )
        client = OfflineDemoClient() if data_mode == "Offline demo" else OpenAITextClient(
            model_id, pricing=pricing
        )
        with st.status("Running Scout, Library, Critic, and finalization…", expanded=True) as status:
            progress = st.progress(0, text="Preparing run")
            completed_percent = 0

            def show_progress(record: dict[str, object]) -> None:
                nonlocal completed_percent
                if record.get("event") != "end":
                    return
                stage = record.get("stage")
                steps = {"scout": 30, "library": 50, "critic": 80, "final_proposal": 95}
                if stage in steps:
                    completed_percent = max(completed_percent, steps[stage])
                    progress.progress(completed_percent, text=f"Completed {stage}")

            tracer = RunTracer(uuid4().hex, console=False, on_record=show_progress)
            try:
                result = asyncio.run(run_prepared_research(
                    prepared, client, adapters, tracer=tracer, model_pricing=pricing,
                    mode=run_mode,
                ))
                st.session_state.result = result
                st.session_state.ui_page = "results"
                progress.progress(100, text="Run complete")
                status.update(label="Run complete", state="complete")
            except Exception as error:
                status.update(label="Run failed", state="error")
                st.session_state.result = None
                st.error(safe_error_message(error))
            finally:
                tracer.close()
    if st.session_state.ui_page == "results":
        st.rerun()
