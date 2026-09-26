"""Run a versioned prompt, retain usage, and validate its model response."""

from __future__ import annotations

import json
from contextlib import nullcontext

from src.guardrails import check_privacy, emit_advisories
from src.llm.client import LLMClient, ModelReply, ModelResponseError
from src.models import UsageRecord
from src.observability import RunTracer
from src.prompts import PromptName, parse_model_output, render_prompt


async def call_prompt(
    llm_client: LLMClient,
    name: PromptName,
    context: dict[str, object],
    *,
    max_output_tokens: int,
    tracer: RunTracer | None = None,
    task_id: str | None = None,
) -> object:
    """Trace one model call, including usage when output validation fails."""

    with tracer.span(name, task_id=task_id) if tracer else nullcontext():
        emit_advisories(check_privacy(context))
        prompt = render_prompt(name, **context)
        try:
            reply = await llm_client.complete(prompt, max_output_tokens=max_output_tokens)
        except ModelResponseError as error:
            if tracer and error.reply:
                _record_usage(tracer, name, error.reply, task_id=task_id)
            raise
        if tracer:
            _record_usage(tracer, name, reply, task_id=task_id)
        # Scan before schema errors or downstream components can expose raw text.
        check_privacy(reply.text)
        try:
            decoded = json.loads(reply.text)
        except ValueError:
            decoded = reply.text  # The contract parser still reports invalid JSON.
        emit_advisories(check_privacy(decoded))
        return parse_model_output(name, reply.text)


def _record_usage(
    tracer: RunTracer, stage: str, reply: ModelReply, *, task_id: str | None
) -> None:
    tracer.usage(
        stage,
        UsageRecord(
            models=[reply.model],
            model_calls=1,
            prompt_tokens=reply.input_tokens or 0,
            completion_tokens=reply.output_tokens or 0,
            token_usage_available=(
                reply.input_tokens is not None and reply.output_tokens is not None
            ),
            estimated_cost_usd=reply.estimated_cost_usd,
        ),
        task_id=task_id,
    )
