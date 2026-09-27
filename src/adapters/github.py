"""GitHub repository search adapter using the public REST API."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from src.models.scout_query import SourceQuery
from src.models.source_record import RetrievalStatus, SourceRecord

from .http_json import SourcePayloadError, request_json


class GitHubAdapter:
    provider_id = "github"
    endpoint = "https://api.github.com/search/repositories"

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout_seconds: float = 20,
        max_results: int = 100,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results

    async def search(self, query: SourceQuery) -> list[SourceRecord]:
        if query.provider_id != self.provider_id:
            raise ValueError(f"query provider must be {self.provider_id!r}")
        if "code_repository" not in query.source_types:
            return []
        if "metadata" not in query.content_types:
            return []

        result_limit = min(query.max_results, self.max_results, 100)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ScoutSpark/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.endpoint}?{urlencode({'q': query.text, 'sort': 'updated', 'order': 'desc', 'per_page': result_limit})}"
        payload = await request_json(
            self.provider_id,
            url,
            headers=headers,
            timeout_seconds=self.timeout_seconds,
        )
        results = payload.get("items", [])
        if not isinstance(results, list):
            raise SourcePayloadError(self.provider_id, "repository results were not a list")

        captured_at = datetime.now(timezone.utc)
        sources = []
        for item in results[:result_limit]:
            if not isinstance(item, dict):
                continue
            repo_id = item.get("id")
            name = item.get("full_name")
            url = item.get("html_url")
            if not isinstance(repo_id, int) or not isinstance(name, str) or not isinstance(url, str):
                continue
            description = item.get("description")
            snippet = description.strip()[:1500] if isinstance(description, str) and description.strip() else None
            owner = item.get("owner")
            owner_name = owner.get("login") if isinstance(owner, dict) else None
            topics = item.get("topics")
            tags = [topic for topic in topics if isinstance(topic, str)] if isinstance(topics, list) else []
            created = _parse_datetime(item.get("created_at"))
            updated = _parse_datetime(item.get("pushed_at") or item.get("updated_at"))
            license_data = item.get("license")
            license_name = license_data.get("spdx_id") if isinstance(license_data, dict) else None
            content_hash = hashlib.sha256(
                f"{name}\n{snippet or ''}\n{updated or ''}".encode("utf-8")
            ).hexdigest()
            sources.append(
                SourceRecord(
                    source_id=f"github-{repo_id}",
                    provider=self.provider_id,
                    source_type="code_repository",
                    title=name,
                    authors_or_owners=[owner_name] if isinstance(owner_name, str) else [],
                    published_at=created,
                    captured_at=captured_at,
                    canonical_url=url,
                    query_id=query.query_id,
                    domain_tags=tags,
                    abstract_or_snippet=snippet,
                    license_access_note=f"Repository license: {license_name or 'not specified'}.",
                    content_hash=content_hash,
                    retrieval_status=RetrievalStatus.SUCCESS,
                    provider_record_id=str(repo_id),
                )
            )
        return sources


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
