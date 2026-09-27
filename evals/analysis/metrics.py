"""Summarize quantitative pipeline metrics from saved end-to-end reports."""

import argparse
import csv
import json
from math import isfinite
from pathlib import Path

from src.models import RetrievalStatus


def summarize(report: dict) -> dict:
    """Compute structural, coverage, gate, latency, and usage metrics."""
    cases = report.get("cases", [])
    requested = returned = target_met = usable_sources = required_types = covered_types = 0
    citation_pass = citation_fail = citation_not_evaluated = 0
    gates_passed = gates_failed = 0
    durations = []
    case_rows = []

    for case in cases:
        duration = case.get("duration_seconds")
        if isinstance(duration, (float, int)) and isfinite(duration) and duration >= 0:
            durations.append(duration)
        counts = case.get("proposal_counts") or {}
        case_requested = counts.get("requested", 0)
        case_returned = counts.get("returned", 0)
        requested += case_requested
        returned += case_returned
        target_met += int(bool(counts.get("target_met")))
        result = case.get("result") or {}
        manifest = result.get("source_manifest", [])
        usable = [source for source in manifest if source.get("retrieval_status") in (
            RetrievalStatus.SUCCESS.value, RetrievalStatus.PARTIAL.value
        )]
        usable_sources += len(usable)
        required = set((result.get("prepared_run") or {}).get("search", {}).get(
            "required_source_types", case.get("expected_source_types", [])
        ))
        covered = required & {source.get("source_type") for source in usable}
        required_types += len(required)
        covered_types += len(covered)
        citation_check = (case.get("checks") or {}).get("citation_integrity")
        if citation_check is True:
            citation_pass += 1
        elif citation_check is False:
            citation_fail += 1
        else:
            citation_not_evaluated += 1
        case_gates_passed = case_gates_failed = 0
        evaluations = list((result.get("critic") or {}).get("evaluations", []))
        seen_evaluations = {item.get("evaluation_id") for item in evaluations}
        for attempt in result.get("recovery_history", []):
            for evaluation in attempt.get("previous_evaluations", []):
                if evaluation.get("evaluation_id") not in seen_evaluations:
                    evaluations.append(evaluation)
                    seen_evaluations.add(evaluation.get("evaluation_id"))
        for evaluation in evaluations:
            for gate in evaluation.get("hard_gates", []):
                if gate.get("passed") is True:
                    case_gates_passed += 1
                elif gate.get("passed") is False:
                    case_gates_failed += 1
        gates_passed += case_gates_passed
        gates_failed += case_gates_failed
        case_rows.append({
            "case_id": case.get("case_id"), "outcome": case.get("outcome"),
            "proposals_returned": case_returned, "proposals_requested": case_requested,
            "target_met": bool(counts.get("target_met")), "usable_sources": len(usable),
            "required_source_types_covered": sorted(covered),
            "required_source_types_missing": sorted(required - covered),
            "citation_integrity": citation_check, "duration_seconds": duration,
            "recovery_rounds": len(result.get("recovery_history", [])),
        })

    usage = report.get("suite_budget_usage") or {}
    known_durations = sorted(durations)
    percentile_95 = known_durations[max(0, int(0.95 * len(known_durations) + 0.999) - 1)] if known_durations else None
    return {
        "report_mode": report.get("mode"), "execution": report.get("execution"),
        "model": report.get("model"), "fixture_kind": report.get("fixture_kind"),
        "case_count": len(cases), "case_outcomes": {
            outcome: sum(case.get("outcome") == outcome for case in cases)
            for outcome in ("passed", "failed", "error", "skipped")
        },
        "proposal_yield": {
            "returned": returned, "requested": requested,
            "target_attainment": returned / requested if requested else None,
            "cases_at_target": target_met,
        },
        "source_coverage": {
            "usable_source_records": usable_sources, "required_source_types_covered": covered_types,
            "required_source_types_total": required_types,
            "required_type_coverage": covered_types / required_types if required_types else None,
        },
        "citation_integrity": {
            "cases_passed": citation_pass, "cases_failed": citation_fail,
            "cases_not_evaluated": citation_not_evaluated,
        },
        "hard_gates": {"passed": gates_passed, "failed": gates_failed,
                       "not_evaluated": gates_passed + gates_failed == 0},
        "latency_seconds": {
            "total": sum(durations), "mean_per_case": sum(durations) / len(durations) if durations else None,
            "p95_case": percentile_95,
        },
        "usage": {"model_tokens": usage.get("model_tokens"),
                  "estimated_cost_usd": usage.get("estimated_cost_usd"),
                  "max_cost_usd": report.get("max_cost_usd"),
                  "cost_source": "application estimate; provider billing may differ"},
        "cases": case_rows,
    }


def summarize_quality(reports: list[tuple[Path, dict]], human_scores_paths: list[Path] | None = None) -> dict:
    """Aggregate valid model-judge scores while retaining errors and sample size."""
    latest_report = reports[-1][1]
    merged = {}
    usage_total = {"model_tokens": 0, "estimated_cost_usd": 0.0, "elapsed_seconds": 0.0}
    for _, report in reports:
        usage = report.get("budget_usage", {})
        for field in usage_total:
            usage_total[field] += usage.get(field, 0) or 0
        for row in report.get("reviews", []):
            key = (row.get("report"), row.get("case_id"), row.get("proposal_id"))
            prior = merged.get(key)
            if prior is None or row.get("review") or not prior.get("review"):
                merged[key] = row
    reviews = list(merged.values())
    valid = [row for row in reviews if row.get("review")]
    dimensions = {}
    names = sorted({name for row in valid for name in row["review"].get("dimensions", {})})
    for name in names:
        scores = [row["review"]["dimensions"][name]["score"] for row in valid
                  if name in row["review"].get("dimensions", {})]
        dimensions[name] = {"mean": sum(scores) / len(scores) if scores else None,
                            "n": len(scores), "scores": scores}
    dimensions_by_mode = {}
    for mode in sorted({row.get("mode", "unknown") for row in valid}):
        mode_rows = [row for row in valid if row.get("mode", "unknown") == mode]
        dimensions_by_mode[mode] = {}
        for name in names:
            scores = [row["review"]["dimensions"][name]["score"] for row in mode_rows
                      if name in row["review"].get("dimensions", {})]
            dimensions_by_mode[mode][name] = {
                "mean": sum(scores) / len(scores) if scores else None, "n": len(scores),
            }
    result = {
        "reviewer": latest_report.get("reviewer"), "model": latest_report.get("model"),
        "human_review": False, "proposal_count": len(reviews),
        "reviewed_count": len(valid), "error_count": len(reviews) - len(valid),
        "dimensions": dimensions, "dimensions_by_mode": dimensions_by_mode,
        "budget_usage_across_reports": usage_total,
        "rubric_sha256": latest_report.get("rubric_sha256"),
        "prompt_template_sha256": latest_report.get("prompt_template_sha256"),
        "proposal_prompt_hashes_present": sum(bool(row.get("prompt_sha256")) for row in reviews),
        "source_quality_reports": [str(path) for path, _ in reports],
    }
    result["model_scores_by_proposal"] = [{
        "case_id": row.get("case_id"), "run_id": row.get("run_id"),
        "proposal_id": row.get("proposal_id"), "dimensions": row["review"]["dimensions"],
        "issues": row["review"].get("issues", []),
    } for row in valid]
    if human_scores_paths:
        result["human_agreement"] = compare_human_scores(valid, human_scores_paths)
    else:
        result["human_agreement"] = {"status": "pending", "reason": "No human score CSV supplied."}
    return result


def compare_human_scores(model_rows: list[dict], csv_paths: list[Path]) -> dict:
    """Compare independently entered human scores with model scores by run/proposal."""
    dimensions = sorted({name for row in model_rows
                         for name in row["review"].get("dimensions", {})})
    index = {(row.get("case_id"), row.get("run_id"), row.get("proposal_id")): row
             for row in model_rows}
    matched = []
    unmatched = 0
    for csv_path in csv_paths:
        with csv_path.open(newline="", encoding="utf-8") as file:
            for human in csv.DictReader(file):
                if not any(human.get(name, "").strip() for name in dimensions):
                    continue
                key = (human.get("case_id"), human.get("run_id"), human.get("proposal_id"))
                model = index.get(key)
                if model is None:
                    unmatched += 1
                    continue
                for name in dimensions:
                    raw = human.get(name, "").strip()
                    if raw:
                        try:
                            score = int(raw)
                        except ValueError:
                            continue
                        matched.append({"dimension": name,
                                        "model": model["review"]["dimensions"][name]["score"],
                                        "human": score, "case_id": key[0],
                                        "proposal_id": key[2]})
    by_dimension = {}
    for name in dimensions:
        rows = [row for row in matched if row["dimension"] == name]
        by_dimension[name] = {
            "n": len(rows),
            "exact_agreement": (sum(row["model"] == row["human"] for row in rows) / len(rows)
                                if rows else None),
            "mean_absolute_difference": (sum(abs(row["model"] - row["human"]) for row in rows) / len(rows)
                                         if rows else None),
            "disagreements": [row for row in rows if row["model"] != row["human"]],
        }
    return {"status": "compared" if matched else "pending", "matched_dimension_scores": len(matched),
            "unmatched_human_rows": unmatched, "by_dimension": by_dimension}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--quality-report", type=Path, action="append",
                        help="optional saved blind-judge output to summarize separately")
    parser.add_argument("--human-scores", type=Path, action="append",
                        help="optional completed human_scores.csv for agreement analysis")
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output directory already exists")
    reports = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in args.report]
    payload = {"reports": [{"source_report": str(path), "metrics": summarize(report)}
                           for path, report in reports]}
    if args.quality_report:
        quality_reports = [(path, json.loads(path.read_text(encoding="utf-8")))
                           for path in args.quality_report]
        payload["quality_review"] = {
            "metrics": summarize_quality(quality_reports, args.human_scores),
        }
    args.output.mkdir(parents=True)
    (args.output / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# Quantitative Evaluation Metrics", ""]
    for item in payload["reports"]:
        metric = item["metrics"]
        proposal = metric["proposal_yield"]
        lines += [f"## {item['source_report']}", "",
                  f"- Mode/execution: {metric['report_mode']} / {metric['execution']}",
                  f"- Cases: {metric['case_count']} ({metric['case_outcomes']})",
                  f"- Proposals: {proposal['returned']} returned / {proposal['requested']} requested "
                  f"({proposal['target_attainment'] if proposal['target_attainment'] is not None else 'n/a'})",
                  f"- Required source-type coverage: {metric['source_coverage']['required_type_coverage']}",
                  f"- Citation checks: {metric['citation_integrity']}",
                  f"- Hard gates: {metric['hard_gates']}",
                  f"- Latency: {metric['latency_seconds']}",
                  f"- Model tokens / estimated cost: {metric['usage']['model_tokens']} / "
                  f"${metric['usage']['estimated_cost_usd']}", ""]
    quality = payload.get("quality_review", {}).get("metrics")
    if quality:
        lines += ["## Blind LLM judge (not human scores)", "",
                  f"- Reviews: {quality['reviewed_count']} / {quality['proposal_count']} "
                  f"({quality['error_count']} errors)",
                  f"- Model and estimated usage: {quality['model']} / "
                  f"{quality['budget_usage_across_reports']}",
                  "- Dimension means and sample sizes:"]
        lines += [f"  - {name}: {values['mean']:.2f} (n={values['n']})"
                  for name, values in quality["dimensions"].items()]
        lines += ["- Dimension means by scheduling mode (descriptive; proposals differ):"]
        for mode, dimensions in quality["dimensions_by_mode"].items():
            lines.append(f"  - {mode}: " + ", ".join(
                f"{name} {values['mean']:.2f} (n={values['n']})"
                for name, values in dimensions.items()
            ))
        lines += ["", "Model-judge scores are separate from human ratings and are not ground truth.", ""]
        human = quality["human_agreement"]
        lines += [f"Human agreement: {human['status']} ({human.get('matched_dimension_scores', 0)} matched dimension scores).", ""]
    lines += ["Metrics are descriptive, not quality judgments. Missing outputs are not scored as good.",
              "Cost is the application's estimate and may differ from provider billing."]
    (args.output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Metrics written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
