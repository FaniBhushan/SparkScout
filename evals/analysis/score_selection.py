"""Replay score selection on saved assessments; no research or model calls."""

import argparse
import hashlib
import json
from pathlib import Path

from src.models import OrchestrationResult


def evaluate_selection(report: dict, finalist_count: int = 2) -> dict:
    """Measure display coverage separately from verified proposal yield."""
    if finalist_count < 1:
        raise ValueError("finalist_count must be positive")
    cases = []
    for case in report.get("cases", []):
        raw = case.get("result")
        if raw is None:
            cases.append({"case_id": case["case_id"], "selected": [],
                          "target_met": False, "gate_warnings": 0, "scored_candidates": 0})
            continue
        result = OrchestrationResult.model_validate(raw)
        # Override only the display target; retain the historical assessments.
        replay = result.model_copy(update={"prepared_run": None,
                                           "requested_finalist_count": finalist_count})
        selected = replay.score_finalist_candidate_ids
        cases.append({
            "case_id": case["case_id"], "selected": selected,
            "target_met": len(selected) == finalist_count,
            "gate_warnings": sum(not row.gate_passed for row in replay.score_ranking
                                 if row.candidate_id in selected),
            "scored_candidates": len(replay.score_ranking),
        })
    return {"mode": report.get("mode"), "case_count": len(cases),
            "cases_at_display_target": sum(case["target_met"] for case in cases),
            "selected_count": sum(len(case["selected"]) for case in cases),
            "selected_with_failed_gates": sum(case["gate_warnings"] for case in cases),
            "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--finalist-count", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path in args.report:
        raw = path.read_bytes()
        rows.append({"source_report": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                     "metrics": evaluate_selection(json.loads(raw), args.finalist_count)})
    output = {"execution": "saved_assessment_replay", "new_model_calls": 0,
              "finalist_count": args.finalist_count, "reports": rows,
              "limitation": "Display coverage does not establish proposal validity or quality."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
    print(f"Selection metrics written to {args.output}")


if __name__ == "__main__":
    main()
