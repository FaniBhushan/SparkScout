"""Instantiate only implemented and credential-ready source adapters."""

from __future__ import annotations

import os
from typing import Sequence

from src.models import SourceConfiguration

from .base import SourceAdapter
from .frozen_fixture import FrozenFixtureAdapter
from .github import GitHubAdapter
from .tavily import TavilyAdapter
from .user_upload import UserUploadAdapter


def build_available_adapters(
    *,
    fixture_set: str | None = None,
    include_live: bool = False,
    upload_files: Sequence[tuple[str, bytes, str]] | None = None,
    upload_rights_confirmed: bool = False,
    sources: SourceConfiguration | None = None,
) -> dict[str, SourceAdapter]:
    """Build approved adapters without making searches or model calls.

    Frozen fixtures are opt-in and live providers are opt-in. Missing credentials
    leave a provider unavailable so the resolver can reject unmet requirements.
    """

    if sources is None:
        # Delay this import because configuration also references the adapter protocol.
        from src.configuration.loader import load_source_configuration

        catalog = load_source_configuration()
    else:
        catalog = sources
    available: dict[str, SourceAdapter] = {}
    if fixture_set is not None:
        fixture = catalog.providers.get("frozen_fixture")
        if fixture is None or not fixture.enabled or fixture.adapter != "frozen_fixture":
            raise ValueError("frozen_fixture is not enabled in the source catalog")
        available["frozen_fixture"] = FrozenFixtureAdapter(fixture_set)

    if upload_files:
        definition = catalog.providers.get("user_upload")
        if definition is None or not definition.enabled or definition.adapter != "user_upload":
            raise ValueError("user_upload is not enabled in the source catalog")
        available["user_upload"] = UserUploadAdapter(
            upload_files, rights_confirmed=upload_rights_confirmed
        )

    if include_live:
        github = catalog.providers.get("github")
        if github is not None and github.enabled and github.adapter == "github":
            available["github"] = GitHubAdapter(timeout_seconds=github.timeout_seconds)
        tavily = catalog.providers.get("tavily")
        if (
            tavily is not None
            and tavily.enabled
            and tavily.adapter == "tavily"
            and os.getenv("TAVILY_API_KEY")
            and all(os.getenv(name) for name in tavily.credential_env_vars)
        ):
            available["tavily"] = TavilyAdapter(timeout_seconds=tavily.timeout_seconds)
    return available
