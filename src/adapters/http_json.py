"""Small standard-library JSON HTTP helper shared by live adapters."""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.runtime.failures import RetryableFailure
from src.runtime.retry import retry_after_seconds


class SourceAdapterError(RuntimeError):
    """Safe provider error with HTTP status, without echoing secrets or response bodies."""

    def __init__(self, provider_id: str, message: str, *, status: int | None = None) -> None:
        self.provider_id = provider_id
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"{provider_id}: {message}{suffix}")


class SourceTimeoutError(SourceAdapterError, RetryableFailure):
    code = "provider_timeout"


class SourceRateLimitError(SourceAdapterError, RetryableFailure):
    code = "provider_rate_limit"


class SourceUnavailableError(SourceAdapterError, RetryableFailure):
    code = "provider_unavailable"


class SourcePayloadError(SourceAdapterError):
    code = "provider_invalid_payload"


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
        if error.code == 429 or (error.code == 403 and (
            error.headers.get("Retry-After") or error.headers.get("X-RateLimit-Remaining") == "0"
        )):
            failure = SourceRateLimitError(provider_id, "rate limit reached", status=error.code)
        elif error.code >= 500:
            failure = SourceUnavailableError(provider_id, "service unavailable", status=error.code)
        else:
            raise SourceAdapterError(provider_id, "request was rejected", status=error.code) from None
        failure.retry_after = retry_after_seconds(error.headers.get("Retry-After"))
        raise failure from None
    except (TimeoutError, URLError, OSError) as error:
        error_class = SourceTimeoutError if isinstance(error, TimeoutError) or isinstance(
            getattr(error, "reason", None), TimeoutError
        ) else SourceUnavailableError
        raise error_class(
            provider_id, f"request failed ({type(error).__name__})"
        ) from None

    if len(raw) > 2_000_000:
        raise SourcePayloadError(provider_id, "response exceeded the 2 MB limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SourcePayloadError(provider_id, "provider returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise SourcePayloadError(provider_id, "provider returned an unexpected response shape")
    return payload
