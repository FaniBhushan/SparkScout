"""Small standard-library JSON HTTP helper shared by live adapters."""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SourceAdapterError(RuntimeError):
    """Safe provider error with HTTP status, without echoing secrets or response bodies."""

    def __init__(self, provider_id: str, message: str, *, status: int | None = None) -> None:
        self.provider_id = provider_id
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"{provider_id}: {message}{suffix}")


async def request_json(
    provider_id: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    """Make one bounded HTTP call without blocking the worker event loop."""

    return await asyncio.to_thread(
        _request_json,
        provider_id,
        url,
        headers,
        timeout_seconds,
        body,
    )


def _request_json(
    provider_id: str,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
    body: dict[str, object] | None,
) -> dict[str, object]:
    request_body = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=request_body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(2_000_001)
    except HTTPError as error:
        raise SourceAdapterError(provider_id, "request was rejected", status=error.code) from None
    except (TimeoutError, URLError, OSError) as error:
        raise SourceAdapterError(
            provider_id, f"request failed ({type(error).__name__})"
        ) from None

    if len(raw) > 2_000_000:
        raise SourceAdapterError(provider_id, "response exceeded the 2 MB limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SourceAdapterError(provider_id, "provider returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise SourceAdapterError(provider_id, "provider returned an unexpected response shape")
    return payload
