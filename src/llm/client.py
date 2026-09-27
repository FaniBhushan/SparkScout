"""Shared LLM client contract and OpenAI Responses API implementation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from openai import AsyncOpenAI, APITimeoutError, APIConnectionError, APIStatusError

from src.failures import RetryableFailure

from src.prompts import TRUST_BOUNDARY_INSTRUCTIONS


@dataclass(frozen=True)
class ModelReply:
    """Text and token usage returned by a model call."""

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


@dataclass(frozen=True)
class ModelPricing:
    """Configured USD rates per million input and output tokens."""

    input_per_million: float
    output_per_million: float

    def __post_init__(self) -> None:
        if not all(
            isfinite(rate) and rate >= 0
            for rate in (self.input_per_million, self.output_per_million)
        ):
            raise ValueError("model pricing must be finite and non-negative")


class LLMClient(Protocol):
    """Minimal interface needed by LLM-backed worker components."""

    async def complete(
        self, prompt: str, *, max_output_tokens: int
    ) -> ModelReply: ...


class ModelResponseError(RuntimeError):
    """The model returned no usable completed text response."""

    def __init__(self, message: str, *, reply: ModelReply | None = None) -> None:
        super().__init__(message)
        self.reply = reply


class ModelTransportError(ModelResponseError, RetryableFailure):
    """A retryable model transport failure with no trustworthy usage receipt."""

    code = "model_transport"


class ModelTimeoutError(ModelTransportError):
    code = "model_timeout"


class ModelRateLimitError(ModelTransportError):
    code = "model_rate_limit"


class ModelRequestError(ModelResponseError):
    code = "model_request_rejected"


class OpenAITextClient:
    """Make bounded, stateless text requests through the OpenAI SDK."""

    def __init__(
        self,
        model: str,
        sdk_client: AsyncOpenAI | None = None,
        *,
        pricing: ModelPricing | None = None,
        timeout_seconds: float = 60,
        max_retries: int = 0,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if max_retries != 0:
            raise ValueError("SDK retries must be disabled; use the run retry policy")
        self.model = model
        self.pricing = pricing
        self.sdk_client = (
            (sdk_client.with_options(max_retries=0) if isinstance(sdk_client, AsyncOpenAI) else sdk_client)
            if sdk_client is not None
            else AsyncOpenAI(timeout=timeout_seconds, max_retries=max_retries)
        )

    async def complete(
        self, prompt: str, *, max_output_tokens: int
    ) -> ModelReply:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")

        instruction_options = {}
        if prompt.startswith(TRUST_BOUNDARY_INSTRUCTIONS):
            # Promote only the code-owned prefix, never any user/source text.
            # The budget already counted these bytes in the rendered prompt.
            instruction_options["instructions"] = TRUST_BOUNDARY_INSTRUCTIONS
            prompt = prompt[len(TRUST_BOUNDARY_INSTRUCTIONS):]
        try:
            response = await self.sdk_client.responses.create(
                model=self.model, input=prompt, max_output_tokens=max_output_tokens,
                store=False, **instruction_options,
            )
        except APITimeoutError:
            raise ModelTimeoutError("model request timed out") from None
        except APIConnectionError:
            raise ModelTransportError("model connection failed") from None
        except APIStatusError as error:
            if error.status_code == 429 and getattr(error, "code", None) != "insufficient_quota":
                failure = ModelRateLimitError("model rate limit reached")
            elif error.status_code >= 500:
                failure = ModelTransportError("model service temporarily unavailable")
            else:
                raise ModelRequestError("model request was rejected") from None
            from src.retry import retry_after_seconds
            failure.retry_after = retry_after_seconds(error.response.headers.get("retry-after"))
            raise failure from None
        usage = getattr(response, "usage", None)
        estimated_cost = None
        if usage is not None and self.pricing is not None:
            estimated_cost = (
                usage.input_tokens * self.pricing.input_per_million
                + usage.output_tokens * self.pricing.output_per_million
            ) / 1_000_000
        reply = ModelReply(
            text=getattr(response, "output_text", "") or "",
            model=getattr(response, "model", self.model),
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            estimated_cost_usd=estimated_cost,
        )
        if response.status != "completed":
            raise ModelResponseError(
                f"model response status was {response.status!r}", reply=reply
            )
        if not reply.text.strip():
            raise ModelResponseError("model response contained no text", reply=reply)
        return reply
