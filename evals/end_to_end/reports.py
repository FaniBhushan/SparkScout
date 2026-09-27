"""Write a report and an unscored human-review sheet to a new directory."""

import csv
import json
from pathlib import Path

from src.guardrails import check_privacy

from .cases import ROOT


def write_report(destination: Path, report: dict) -> None:
    """Refuse to overwrite previous evidence; export proposals in results.json."""
    check_privacy(report)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rubric = json.loads((ROOT / "rubrics/proposal_quality.json").read_text())
    (destination / "human_rubric.json").write_text(json.dumps(rubric, indent=2), encoding="utf-8")
    fields = ["case_id", "run_id", "system_variant", "proposal_id", "reviewer_id",
              *rubric["dimensions"], "notes"]
    with (destination / "human_scores.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in report["cases"]:
            result = record["result"]
            if result:
                for proposal in result["final_proposals"]:
                    writer.writerow({"case_id": record["case_id"], "run_id": result["run_id"],
                                     "system_variant": report["mode"], "proposal_id": proposal["proposal_id"]})
    lines = ["# End-to-end evaluation", "", f"Execution: {report['execution']}",
             "", "| Case | Outcome | Proposals returned / target | Failed checks | Not evaluated |",
             "| --- | --- | --- | --- | --- |"]
    for record in report["cases"]:
        failures = ", ".join(key for key, passed in record["checks"].items() if passed is False)
        skipped = ", ".join(key for key, passed in record["checks"].items() if passed is None)
        counts = record.get("proposal_counts")
        count_text = f"{counts['returned']} / {counts['requested']}" if counts else "—"
        lines.append(f"| {record['case_id']} | {record['outcome']} | {count_text} | {failures} | {skipped} |")
    lines += ["", "Human quality scores are pending. Review proposals and constraints in results.json.",
              "Offline demo token counts are synthetic; its outputs do not measure model quality."]
    (destination / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
