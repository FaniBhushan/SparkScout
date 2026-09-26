"""Small Critic component eval, separate from the runtime research pipeline.

Validate or score saved predictions offline. Only an explicit --model selection
makes paid model calls. Gold labels are never included in the Critic input.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter

from src.guardrails import safe_error_message
from src.models import CandidateAssessment, CandidateIdea, EvaluationConfiguration, InputRequest, RetrievedChunk
from src.models.common import ContractModel, Identifier, NonEmptyText
from src.models.source_record import SourceChunk


DATASET = Path(__file__).parent / "guardrails" / "claim_support.json"
Label = Literal["supported", "unsupported", "contradictory"]


class ClaimCase(ContractModel):
    id: Identifier
    claim: NonEmptyText
    evidence: NonEmptyText
    expected: Label


class ClaimDataset(ContractModel):
    version: Literal["1.0"]
    synthetic: Literal[True]
    cases: list[ClaimCase] = Field(min_length=1)


class Prediction(ContractModel):
    id: Identifier
    label: Literal["supported", "unsupported", "contradictory", "invalid"]


def load_cases() -> ClaimDataset:
    dataset = ClaimDataset.model_validate_json(DATASET.read_text(encoding="utf-8"))
    if len({case.id for case in dataset.cases}) != len(dataset.cases):
        raise ValueError("claim-support case IDs must be unique")
    return dataset


def score_predictions(dataset: ClaimDataset, predictions: list[Prediction]) -> dict:
    """Count invalid judgments as wrong; never silently omit difficult cases."""

    by_id = {item.id: item.label for item in predictions}
    if len(by_id) != len(predictions) or set(by_id) != {case.id for case in dataset.cases}:
        raise ValueError("predictions must contain every case ID exactly once")
    labels = ("supported", "unsupported", "contradictory")
    confusion = {label: dict.fromkeys((*labels, "invalid"), 0) for label in labels}
    for case in dataset.cases:
        confusion[case.expected][by_id[case.id]] += 1
    correct = sum(confusion[label][label] for label in labels)
    false_support = sum(confusion[label]["supported"] for label in labels if label != "supported")
    non_support = sum(case.expected != "supported" for case in dataset.cases)
    return {
        "count": len(dataset.cases), "accuracy": correct / len(dataset.cases),
        "false_support_rate": false_support / non_support if non_support else None,
        "confusion": confusion,
    }


def assessment_label(assessment: CandidateAssessment, case: ClaimCase) -> str:
    """Use the Critic's existing evidence stance, not an extra model judge."""

    if set(assessment.criteria) != {"claim_support"} or set(assessment.hard_gates) != {"supported_claim"}:
        return "invalid"
    references = assessment.criteria["claim_support"].evidence
    all_references = [*references, *assessment.hard_gates["supported_claim"].evidence]
    if any(ref.source_id != case.id or ref.chunk_id not in (None, f"{case.id}-c0") for ref in all_references):
        return "invalid"
    stances = {ref.stance.value for ref in references}
    if not stances or stances == {"missing"}:
        label = "unsupported"
    elif stances == {"supporting"} and all(ref.chunk_id == f"{case.id}-c0" for ref in references):
        label = "supported"
    elif stances == {"contradicting"}:
        label = "contradictory"
    else:
        return "invalid"
    if assessment.hard_gates["supported_claim"].passed != (label == "supported"):
        return "invalid"
    return label


async def collect_predictions(dataset: ClaimDataset, judge) -> list[Prediction]:
    """Nine bounded component calls for the starter set; no search or generation."""

    rubric = EvaluationConfiguration(
        preset="claim-support-eval",
        criteria={"claim_support": {
            "label": "Whether the candidate's problem statement is supported by the supplied chunk",
            "weight": 100,
            "retrieval_focus": "Assess this exact claim only; use supporting, contradicting, or missing evidence.",
        }},
        hard_gates={"supported_claim": "Pass only if the chunk supports the exact claim."},
    )
    request = InputRequest(domain="AI engineering", time_limit_days=30)
    predictions = []
    for case in dataset.cases:
        candidate = CandidateIdea(
            candidate_id=case.id, title="Synthetic claim-support check",
            problem_statement=case.claim, target_users=["Evaluation reviewers"],
            proposed_outcome="Check the claim against the supplied evidence.",
            why_it_matters="Unsupported assertions should not become proposal facts.",
        )
        evidence = [RetrievedChunk(score=1, chunk=SourceChunk(
            source_id=case.id, chunk_id=f"{case.id}-c0", ordinal=0,
            text=case.evidence, content_hash=hashlib.sha256(case.evidence.encode()).hexdigest(),
        ))]
        try:
            assessment = await judge.assess(request, candidate, evidence, rubric)
            label = assessment_label(assessment, case)
        except ValueError:
            label = "invalid"  # Malformed/blocked output is not excluded from the score.
        predictions.append(Prediction(id=case.id, label=label))
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate-only", action="store_true")
    action.add_argument("--predictions", type=Path, help="offline JSON list of {id, label}")
    action.add_argument("--model", help="explicitly enable paid Critic calls for all cases")
    args = parser.parse_args()
    dataset = load_cases()
    if args.validate_only:
        print(f"Validated {len(dataset.cases)} synthetic claim-support cases; no model calls.")
        return 0
    if args.predictions:
        predictions = TypeAdapter(list[Prediction]).validate_json(args.predictions.read_text())
    else:
        from src.llm.client import OpenAITextClient
        from src.llm.critic_llm import LLMCandidateJudge

        judge = LLMCandidateJudge(OpenAITextClient(args.model), max_output_tokens=1000)
        predictions = asyncio.run(collect_predictions(dataset, judge))
    print(json.dumps({
        "dataset_version": dataset.version,
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "model": args.model,
        "predictions": [item.model_dump() for item in predictions],
        "metrics": score_predictions(dataset, predictions),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(safe_error_message(error)) from None
