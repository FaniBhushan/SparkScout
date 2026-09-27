"""Tavily web search adapter; captures short result snippets without raw pages."""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from src.models.scout_query import SourceQuery
from src.models.source_record import RetrievalStatus, SourceRecord
from src.sources.merge import canonical_source_url

from .http_json import SourceAdapterError, SourcePayloadError, request_json


class TavilyAdapter:
    """Search the web and retain only result metadata and permitted snippets."""

    provider_id = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 20,
        max_results: int = 20,
    ) -> None:
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results

    async def search(self, query: SourceQuery) -> list[SourceRecord]:
        """Return normalized web receipts without requesting full page content."""
        if query.provider_id != self.provider_id:
            raise ValueError(f"query provider must be {self.provider_id!r}")
        if "web_article" not in query.source_types:
            return []
        if not self.api_key:
            raise SourceAdapterError(self.provider_id, "TAVILY_API_KEY is not configured")

        result_limit = min(query.max_results, self.max_results, 20)
        payload = await request_json(
            self.provider_id,
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ScoutSpark/0.1",
            },
            timeout_seconds=self.timeout_seconds,
            body={
                "query": query.text,
                "topic": "general",
                "search_depth": "basic",
                "max_results": result_limit,
                "chunks_per_source": 1,
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
            },
        )
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise SourcePayloadError(self.provider_id, "search results were not a list")

        captured_at = datetime.now(timezone.utc)
        sources = []
        include_snippet = "page_snippet" in query.content_types
        for item in results[:result_limit]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            url = item.get("url")
            if not isinstance(title, str) or not title.strip() or not isinstance(url, str):
                continue
            snippet = item.get("content")
            snippet = snippet.strip()[:2000] if isinstance(snippet, str) and snippet.strip() else None
            if not include_snippet:
                snippet = None
            parsed_date = _parse_date(item.get("published_date"))
            # Canonicalize before assigning an ID so tracking links share identity.
            url = canonical_source_url(url)
            source_id = "web-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
            content_hash = hashlib.sha256(
                f"{title}\n{snippet or ''}".encode("utf-8")
            ).hexdigest()
            hostname = urlparse(url).hostname
            sources.append(
                SourceRecord(
                    source_id=source_id,
                    provider=self.provider_id,
                    source_type="web_article",
                    title=title.strip()[:500],
                    published_at=parsed_date,
                    captured_at=captured_at,
                    canonical_url=url,
                    query_id=query.query_id,
                    domain_tags=[hostname] if hostname else [],
                    abstract_or_snippet=snippet,
                    license_access_note="Search result snippet only; check the page's access and reuse terms.",
                    content_hash=content_hash,
                    retrieval_status=RetrievalStatus.SUCCESS,
                    provider_record_id=url,
                )
            )
        return sources


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
