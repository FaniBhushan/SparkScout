"""Configurable source registry and request-level source policy."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, HttpUrl, PositiveFloat, PositiveInt, model_validator

from .common import ContractModel, Identifier, NonEmptyText


class EvidenceTier(str, Enum):
    PRIMARY = "primary"
    SCHOLARLY = "scholarly"
    OPPORTUNITY = "opportunity"
    SYNTHETIC = "synthetic"
    USER_SUPPLIED = "user_supplied"


class SourcePolicy(ContractModel):
    """Optional user constraints applied to the configured source registry."""

    include_types: list[Identifier] = Field(default_factory=list)
    exclude_types: list[Identifier] = Field(default_factory=list)
    required_types: list[Identifier] = Field(default_factory=list)
    max_records_by_type: dict[Identifier, PositiveInt] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_type_sets(self) -> "SourcePolicy":
        included = set(self.include_types)
        excluded = set(self.exclude_types)
        required = set(self.required_types)
        overlap = (included | required) & excluded
        if overlap:
            raise ValueError(f"source types cannot be included and excluded: {sorted(overlap)}")
        if included and not required.issubset(included):
            raise ValueError("required_types must be present in include_types when include_types is set")
        return self


class SourceTypeDefinition(ContractModel):
    evidence_tier: EvidenceTier
    allowed_uses: list[Identifier] = Field(default_factory=list)
    prohibited_uses: list[Identifier] = Field(default_factory=list)
    default_max_records: PositiveInt = 25
    default_max_age_days: PositiveInt | None = None


class ProviderDefinition(ContractModel):
    adapter: Identifier
    enabled: bool = True
    emits: list[Identifier] = Field(min_length=1)
    capabilities: list[Identifier] = Field(default_factory=list)
    domains: list[NonEmptyText] = Field(default_factory=lambda: ["*"])
    base_url: HttpUrl | None = None
    credential_env_vars: list[Identifier] = Field(default_factory=list)
    timeout_seconds: PositiveFloat = 30
    max_requests_per_run: PositiveInt = 10
    supports_language: bool = False


class DomainRoute(ContractModel):
    required_types: list[Identifier] = Field(default_factory=list)
    preferred_types: list[Identifier] = Field(default_factory=list)
    providers: list[Identifier] = Field(min_length=1)
    fallback_providers: list[Identifier] = Field(default_factory=list)


class SourceConfiguration(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    domains: list[Identifier] = Field(default_factory=list)
    source_types: dict[Identifier, SourceTypeDefinition] = Field(min_length=1)
    providers: dict[Identifier, ProviderDefinition] = Field(min_length=1)
    routes: dict[NonEmptyText, DomainRoute] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_registry_references(self) -> "SourceConfiguration":
        unknown_domains = set(self.routes) - set(self.domains) if self.domains else set()
        if unknown_domains:
            raise ValueError(f"routes use unknown domains: {sorted(unknown_domains)}")
        known_types = set(self.source_types)
        known_providers = set(self.providers)

        for provider_id, provider in self.providers.items():
            unknown = set(provider.emits) - known_types
            if unknown:
                raise ValueError(f"provider {provider_id!r} emits unknown types: {sorted(unknown)}")

        for domain, route in self.routes.items():
            unknown_types = (set(route.required_types) | set(route.preferred_types)) - known_types
            if unknown_types:
                raise ValueError(f"route {domain!r} uses unknown types: {sorted(unknown_types)}")
            unknown_providers = (set(route.providers) | set(route.fallback_providers)) - known_providers
            if unknown_providers:
                raise ValueError(
                    f"route {domain!r} uses unknown providers: {sorted(unknown_providers)}"
                )
        return self
