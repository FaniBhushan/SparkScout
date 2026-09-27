"""Small Critic component eval, separate from the runtime research pipeline.

Validate or score saved predictions offline. Only an explicit --model selection
makes paid model calls. Gold labels are never included in the Critic input.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter

from src.guardrails import safe_error_message
from src.models import CandidateAssessment, CandidateIdea, EvaluationConfiguration, InputRequest, RetrievedChunk
from src.models.common import ContractModel, Identifier, NonEmptyText
from src.models.source_record import SourceChunk


DATASET = Path(__file__).resolve().parent / "claim_support.json"
Label = Literal["supported", "unsupported", "contradictory"]


class ClaimCase(ContractModel):
    id: Identifier
    claim: NonEmptyText
    evidence: NonEmptyText
    expected: Label
    target: Literal["claim", "narrative", "dependency", "task_data_fit"] = "claim"
    required_data: list[NonEmptyText] = Field(default_factory=list)


class ClaimDataset(ContractModel):
    version: str = Field(pattern=r"^\d+\.\d+$")
    synthetic: Literal[True]
    cases: list[ClaimCase] = Field(min_length=1)


class Prediction(ContractModel):
    id: Identifier
    label: Literal["supported", "unsupported", "contradictory", "invalid"]


def load_cases(path: Path = DATASET) -> ClaimDataset:
    dataset = ClaimDataset.model_validate_json(path.read_text(encoding="utf-8"))
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


async def collect_predictions(dataset: ClaimDataset, judge, diagnostics=None) -> list[Prediction]:
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
            if diagnostics is not None:
                diagnostics.append({"id": case.id, "assessment": assessment.model_dump(mode="json")})
        except ValueError as error:
            label = "invalid"  # Malformed/blocked output is not excluded from the score.
            if diagnostics is not None:
                diagnostics.append({"id": case.id, "error_type": type(error).__name__})
        predictions.append(Prediction(id=case.id, label=label))
    return predictions


async def collect_verifier_predictions(dataset: ClaimDataset, verifier, diagnostics=None) -> list[Prediction]:
    """Measure the production verifier on exactly the same claim/evidence pairs."""
    from src.models.common import ClaimEvidence
    predictions = []
    for case in dataset.cases:
        chunk = {"source_id": case.id, "chunk_id": f"{case.id}-c0", "text": case.evidence}
        claim = ClaimEvidence(claim=case.claim if case.target == "claim" else case.evidence, references=[{
            "source_id": case.id, "chunk_id": chunk["chunk_id"],
        }])
        try:
            narrative = {}
            if case.target == "narrative":
                narrative = {"proposal": {"gap_or_differentiation": case.claim}}
            elif case.target == "dependency":
                narrative = {"proposal": {"required_data": [case.claim]}}
            elif case.target == "task_data_fit":
                narrative = {"candidate": {"proposed_outcome": case.claim},
                             "proposal": {"required_data": case.required_data}}
            audit = await verifier.verify({}, narrative, [claim], [chunk], task_id=case.id)
            if case.target == "narrative":
                label = audit.narrative_checks["gap_or_differentiation"].label
                label = "supported" if label == "proposed" else label
            elif case.target == "dependency":
                label = audit.dependencies[0].label
            elif case.target == "task_data_fit":
                label = audit.narrative_checks["data_task_fit"].label
            else:
                label = audit.claims[0].label
            if diagnostics is not None:
                diagnostics.append({"id": case.id, "audit": audit.model_dump(mode="json")})
        except ValueError as error:
            label = "invalid"
            if diagnostics is not None:
                diagnostics.append({"id": case.id, "error_type": type(error).__name__})
                # Schema locations/types are useful without logging model text
                # or Pydantic's potentially sensitive input_value payloads.
                if hasattr(error, "errors"):
                    diagnostics[-1]["validation_errors"] = [
                        {"location": list(item["loc"]), "type": item["type"]}
                        for item in error.errors()]
        predictions.append(Prediction(id=case.id, label=label))
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate-only", action="store_true")
    action.add_argument("--predictions", type=Path, help="offline JSON list of {id, label}")
    action.add_argument("--model", help="explicitly enable paid Critic calls for all cases")
    parser.add_argument("--dataset", type=Path, default=DATASET, help="frozen claim-support dataset")
    parser.add_argument("--judge", choices=["critic", "verifier"], default="critic")
    parser.add_argument("--output", type=Path, help="save a new JSON report, refusing overwrite")
    parser.add_argument("--max-cost-usd", type=float, help="required per-invocation estimated spending cap")
    parser.add_argument("--input-rate", type=float, help="USD per million input tokens")
    parser.add_argument("--output-rate", type=float, help="USD per million output tokens")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output already exists")
    if args.model and any(
        value is None or not isfinite(value) or value <= 0
        for value in (args.max_cost_usd, args.input_rate, args.output_rate)
    ):
        parser.error("paid evaluation requires positive finite --max-cost-usd, --input-rate and --output-rate")
    dataset = load_cases(args.dataset)
    if args.judge != "verifier" and any(case.target != "claim" for case in dataset.cases):
        parser.error("narrative/dependency cases require --judge verifier")
    budget = None
    diagnostics = []
    execution_error = None
    if args.validate_only:
        print(f"Validated {len(dataset.cases)} synthetic claim-support cases; no model calls.")
        return 0
    if args.predictions:
        predictions = TypeAdapter(list[Prediction]).validate_json(args.predictions.read_text())
    else:
        from src.runtime.budgets import BudgetedLLMClient, RunBudget
        from src.runtime.environment import load_local_environment
        from src.llm.client import ModelPricing, OpenAITextClient
        from src.llm.critic_llm import LLMCandidateJudge
        from src.llm.proposal_verifier import LLMProposalVerifier
        from src.models import RunBudgetLimits

        load_local_environment()
        pricing = ModelPricing(args.input_rate, args.output_rate)
        budget = RunBudget(RunBudgetLimits(
            max_elapsed_seconds=300, max_model_tokens=100000,
            max_estimated_cost_usd=args.max_cost_usd,
        ), pricing=pricing)
        # Hidden SDK retries would bypass per-attempt reservations. Fail closed
        # on transport failures instead; no automatic paid reruns.
        client = OpenAITextClient(args.model, pricing=pricing, max_retries=0)
        judge = LLMCandidateJudge(BudgetedLLMClient(client, budget), max_output_tokens=1000)
        verifier = LLMProposalVerifier(BudgetedLLMClient(client, budget), max_output_tokens=1000)

        async def evaluate():
            try:
                operation = (collect_predictions(dataset, judge, diagnostics) if args.judge == "critic"
                             else collect_verifier_predictions(dataset, verifier, diagnostics))
                return await asyncio.wait_for(operation, timeout=300)
            finally:
                await client.sdk_client.close()

        try:
            predictions = asyncio.run(evaluate())
        except Exception as error:
            # A failed evaluation still has billable/unknown usage. Preserve its
            # receipt before returning an error; never score an unfinished suite.
            execution_error = error
            predictions = []
    report = {
        "dataset_version": dataset.version,
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "dataset_path": str(args.dataset),
        "model": args.model,
        "resolved_models": sorted(client.resolved_models) if args.model else [],
        "judge": args.judge,
        "prompt_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted((DATASET.parents[2] / "src/prompts").glob("*.md"))},
        "budget_usage": budget.snapshot() if budget else None,
        "max_cost_usd": args.max_cost_usd,
        "pricing_per_million": {"input": args.input_rate, "output": args.output_rate},
        "predictions": [item.model_dump() for item in predictions],
        "diagnostics": diagnostics,
        "execution_error": safe_error_message(execution_error) if execution_error else None,
        "metrics": score_predictions(dataset, predictions) if execution_error is None else None,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, indent=2)
    print(json.dumps(report, indent=2))
    if execution_error is not None:
        raise execution_error
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(safe_error_message(error)) from None
