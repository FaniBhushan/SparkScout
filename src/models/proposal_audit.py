"""Independent claim judgments retained with verified proposals."""

from typing import Literal

from pydantic import Field

from .common import ContractModel, NonEmptyText


class ClaimVerdict(ContractModel):
    claim_index: int = Field(ge=0)
    label: Literal["supported", "unsupported", "contradictory"]
    rationale: NonEmptyText
    evidence_quotes: list[NonEmptyText] = Field(default_factory=list)


class NarrativeVerdict(ContractModel):
    label: Literal["supported", "proposed", "unsupported", "contradictory"]
    rationale: NonEmptyText
    evidence_quotes: list[NonEmptyText] = Field(default_factory=list)


class ProposalAudit(ContractModel):
    quotes_redacted: bool = False
    caveated_fields: list[Literal["problem_statement", "why_it_matters", "gap_or_differentiation"]] = Field(default_factory=list)
    claims: list[ClaimVerdict]
    dependencies: list[ClaimVerdict] = Field(default_factory=list)
    narrative_checks: dict[str, NarrativeVerdict] = Field(default_factory=dict)
    issues: list[NonEmptyText] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (bool(self.claims) and not self.issues
                and all(claim.label == "supported" for claim in [*self.claims, *self.dependencies])
                and all(check.label in ("supported", "proposed")
                        for check in self.narrative_checks.values()))

    @property
    def accepted(self) -> bool:
        """Distinguish full support from the explicitly authorized demo caveat."""
        if self.passed:
            return True
        uncertain = {key for key, value in self.narrative_checks.items()
                     if value.label == "unsupported"}
        return (uncertain.issubset(set(self.caveated_fields))
                and bool(self.claims) and not self.issues
                and all(item.label == "supported" for item in [*self.claims, *self.dependencies])
                and all(value.label in ("supported", "proposed", "unsupported")
                        for value in self.narrative_checks.values()))


class StatementVerdict(NarrativeVerdict):
    """Model-facing flat check; code maps IDs back to the public audit sections."""

    check_id: NonEmptyText


class StatementAudit(ContractModel):
    checks: list[StatementVerdict]
