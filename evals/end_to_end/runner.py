"""Execute independent cases and retain failures alongside successful runs."""

from time import monotonic

from src.adapters import build_available_adapters
from src.application.service import run_prepared_research
from src.models import SubmittedRunConfiguration
from src.application.preflight import prepare_run
from src.guardrails import safe_error_message

from .checks import check_result


async def run_cases(cases, client, *, mode="sequential", pricing=None,
                    checkpoint_root=None, resume=False) -> list[dict]:
    """Use one supplied client so a caller can enforce a suite-wide budget."""
    records = []
    stopped = False
    for case, fingerprint in cases:
        record = {
            "case_id": case.case_id, "input_sha256": fingerprint,
            "checks": {}, "outcome": "skipped", "duration_seconds": 0,
            "result": None, "error": None,
            "proposal_counts": {"requested": case.expected_request.finalist_count,
                                "returned": 0, "target_met": False},
            "expected_source_types": case.expected.get("required_source_types", []),
            "human_review": {key: case.expected.get(key, []) for key in (
                "must_satisfy", "forbidden_outcomes", "relevant_source_ids")},
        }
        if stopped:
            record["error"] = "Suite stopped after a model or budget failure."
            records.append(record)
            continue
        start = monotonic()
        try:
            adapters = build_available_adapters(fixture_set=case.fixture_set)
            prepared = prepare_run(SubmittedRunConfiguration(request=case.expected_request), adapters)
            record["expected_source_types"] = list(prepared.search.required_source_types)
            if checkpoint_root is None:
                result = await run_prepared_research(prepared, client, adapters, mode=mode,
                                                    model_pricing=pricing)
            else:
                directory = checkpoint_root / case.case_id
                result = await run_prepared_research(
                    prepared, client, adapters, mode=mode, model_pricing=pricing,
                    checkpoint_dir=directory, resume=resume and (directory / "state.json").exists(),
                )
            record["checks"] = check_result(case, result)
            record["proposal_counts"] = {
                "requested": case.expected_request.finalist_count,
                "returned": len(result.final_proposals),
                "target_met": len(result.final_proposals) == case.expected_request.finalist_count,
            }
            record["outcome"] = "passed" if all(value is not False for value in record["checks"].values()) else "failed"
            record["result"] = result.model_dump(mode="json")
        except Exception as error:
            record["outcome"] = "error"
            record["error"] = {"type": type(error).__name__, "message": safe_error_message(error)}
            # Transport failures can hide billable work. Stop all later cases on
            # errors; never retry automatically or claim a partial run passed.
            stopped = True
        record["duration_seconds"] = round(monotonic() - start, 3)
        records.append(record)
    return records
