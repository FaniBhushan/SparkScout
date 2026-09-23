"""Candidate evaluations returned by the Critic worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel, NonEmptyText
from .evaluation_result import EvaluationResult


class CriticResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
