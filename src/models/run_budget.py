"""Requested and effective run-wide limits, distinct from per-call output caps."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from .common import ContractModel, Identifier


class BudgetSelection(ContractModel):
    """A user may tighten defaults but never raise the operator ceiling."""

    max_elapsed_seconds: PositiveFloat | None = None
    max_model_tokens: PositiveInt | None = None
    max_source_bytes: PositiveInt | None = None
    max_pdf_pages: PositiveInt | None = None
    max_estimated_cost_usd: PositiveFloat | None = None


class RunBudgetLimits(ContractModel):
    max_elapsed_seconds: PositiveFloat
    max_model_tokens: PositiveInt
    max_source_bytes: PositiveInt = 2_000_000
    max_pdf_pages: PositiveInt = 10
    max_estimated_cost_usd: PositiveFloat | None = None
    provider_call_limits: dict[Identifier, PositiveInt] = Field(default_factory=dict)


class RunBudgetUsage(ContractModel):
    """Reported totals; cost is absent when no trusted rates were configured."""

    model_tokens: NonNegativeInt = 0
    source_bytes: NonNegativeInt = 0
    estimated_cost_usd: NonNegativeFloat | None = None
    provider_calls: dict[Identifier, NonNegativeInt] = Field(default_factory=dict)
    elapsed_seconds: NonNegativeFloat = 0
    reserved_model_tokens: NonNegativeInt = 0
    reserved_cost_usd: NonNegativeFloat = 0


class BudgetPolicy(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    defaults: RunBudgetLimits
    ceilings: RunBudgetLimits

    @model_validator(mode="after")
    def validate_defaults(self) -> "BudgetPolicy":
        for field in ("max_elapsed_seconds", "max_model_tokens", "max_source_bytes", "max_pdf_pages"):
            if getattr(self.defaults, field) > getattr(self.ceilings, field):
                raise ValueError(f"default {field} exceeds operator ceiling")
        if (self.defaults.max_estimated_cost_usd is not None and (
            self.ceilings.max_estimated_cost_usd is None
            or self.defaults.max_estimated_cost_usd > self.ceilings.max_estimated_cost_usd
        )):
            raise ValueError("default cost exceeds operator ceiling")
        return self


def resolve_budget_limits(selection: BudgetSelection, policy: BudgetPolicy) -> RunBudgetLimits:
    """Reject requests above policy instead of silently clamping them."""

    values = {}
    for field in ("max_elapsed_seconds", "max_model_tokens", "max_source_bytes", "max_pdf_pages", "max_estimated_cost_usd"):
        requested = getattr(selection, field)
        value = requested if requested is not None else getattr(policy.defaults, field)
        ceiling = getattr(policy.ceilings, field)
        if value is not None and (ceiling is None or value > ceiling):
            raise ValueError(f"requested {field} exceeds the operator ceiling")
        values[field] = value
    return RunBudgetLimits(**values)
