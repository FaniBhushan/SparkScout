"""Execute independent cases and retain failures alongside successful runs."""

from time import monotonic

from src.adapters import build_available_adapters
from src.application import run_research
from src.guardrails import safe_error_message

from .checks import check_result


async def run_cases(cases, client, *, mode="sequential", pricing=None) -> list[dict]:
    """Use one supplied client so a caller can enforce a suite-wide budget."""
    records = []
    stopped = False
    for case, fingerprint in cases:
        record = {
            "case_id": case.case_id, "input_sha256": fingerprint,
            "checks": {}, "outcome": "skipped", "duration_seconds": 0,
            "result": None, "error": None,
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
            result = await run_research(case.expected_request, client, adapters, mode=mode,
                                        model_pricing=pricing)
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
