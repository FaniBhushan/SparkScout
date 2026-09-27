"""Bounded proposal correction without discarding independent completed work."""

from src.llm.client import ModelResponseError
from src.models import ProposalDraft
from src.guardrails.privacy import SensitiveContentError
from src.guardrails.proposal_policy import qualify_uncertain_narrative
from src.runtime.budgets import BudgetExceeded


class ProposalVerificationError(ValueError):
    """A draft could not be verified within its correction allowance."""


async def verified_draft(request, candidate, evaluation, sources, chunks, writer, verifier,
                         *, allow_provisional_narrative=False):
    """Correct a draft once; verify again instead of trusting the repair itself."""
    if candidate.required_data:
        # Reject missing essential inputs before spending on narrative writing
        # and a full correction cycle. This audit cannot approve a proposal.
        inputs = await verifier.verify(request, {"candidate": {
            "proposed_outcome": candidate.proposed_outcome,
            "required_data": candidate.required_data,
        }}, [], chunks, task_id=candidate.candidate_id + "-inputs")
        failures = [item.rationale for item in inputs.dependencies if item.label != "supported"]
        suitability = inputs.narrative_checks.get("data_task_fit")
        if suitability is None or suitability.label != "supported":
            failures.append(suitability.rationale if suitability else "Task input suitability was not assessed.")
        if inputs.issues or failures or not inputs.dependencies:
            raise ProposalVerificationError("essential input precheck failed: " +
                                            "; ".join([*failures, *inputs.issues]))
    current_evaluation = evaluation
    failure_summary = "invalid response"
    for attempt in range(2):
        try:
            draft = ProposalDraft.model_validate(await writer.draft(
                request, candidate, current_evaluation, sources, chunks,
            ))
            narrative = {
                "candidate": candidate.model_dump(mode="json"),
                "proposal": draft.model_dump(mode="json", exclude={"citations"}),
            }
            # These two draft fields may soften claims without changing the idea.
            for field in ("problem_statement", "why_it_matters"):
                if getattr(draft, field):
                    narrative["candidate"][field] = getattr(draft, field)
            audit = await verifier.verify(request, narrative, draft.citations, chunks,
                                          task_id=candidate.candidate_id)
            if audit.passed:
                qualified = qualify_uncertain_narrative(draft, candidate, audit)
                return qualified if qualified is not None else (draft, audit)
            if attempt == 1 and allow_provisional_narrative:
                qualified = qualify_uncertain_narrative(
                    draft, candidate, audit, allow_unsupported=True,
                )
                if qualified is not None:
                    return qualified
            failures = [f"citation {item.claim_index}: {item.label}"
                        for item in audit.claims if item.label != "supported"]
            failures.extend(f"required data {item.claim_index}: {item.label}"
                            for item in audit.dependencies if item.label != "supported")
            failures.extend(f"{field}: {item.label}"
                            for field, item in audit.narrative_checks.items()
                            if item.label == "unsupported")
            failure_summary = ", ".join(failures or audit.issues or ["audit did not pass"])
            issues = [*audit.issues, *[
                f"Citation {item.claim_index}: {item.label}: {item.rationale}"
                for item in audit.claims if item.label != "supported"
            ], *[f"Required data {item.claim_index}: {item.label}: {item.rationale}"
                 for item in audit.dependencies if item.label != "supported"],
                *[f"{field}: {item.label}: {item.rationale}"
                  for field, item in audit.narrative_checks.items()
                  if item.label not in ("supported", "proposed")]]
        except BudgetExceeded:
            raise  # Never turn an exhausted allowance into a paid correction.
        except ModelResponseError as error:
            if error.reply is None:
                raise  # Unknown billable work and budget failures remain authoritative.
            issues = ["The prior draft or verification response was incomplete."]
        except SensitiveContentError:
            raise
        except ValueError:
            issues = ["The prior response had an invalid schema or citation. Use exact supplied chunk IDs."]
            failure_summary = "invalid verifier or draft response"
        current_evaluation = evaluation.model_copy(update={
            "uncertainty": [*evaluation.uncertainty,
                            "Required draft corrections: " + " ".join(issues)],
        })
    raise ProposalVerificationError(
        "proposal did not pass evidence verification after one correction: " + failure_summary
    )
