"""Non-blocking input-size advisories shared by the CLI and Streamlit UI."""

from __future__ import annotations

import warnings

from .privacy import _strings, check_privacy


LONG_PROMPT_CHARS = 4000
LARGE_REQUEST_CHARS = 12000
LONG_INPUT_WARNING = (
    "Large input: sending more text can increase model cost and delay. "
    "You can continue without shortening it; configured budgets and provider "
    "context limits still apply."
)


class GuardrailWarning(UserWarning):
    """Non-blocking size or privacy advisory for non-UI callers."""


def input_advisories(value: object) -> list[str]:
    """Long natural-language input is advisory, never truncated or size-blocked."""

    messages = check_privacy(value)
    texts = list(_strings(value))
    if any(len(text) > LONG_PROMPT_CHARS for text in texts) or sum(map(len, texts)) > LARGE_REQUEST_CHARS:
        messages.insert(0, LONG_INPUT_WARNING)
    return messages


def emit_advisories(messages: list[str]) -> None:
    """Python/CLI callers receive warnings on stderr, leaving JSON stdout clean."""

    for message in dict.fromkeys(messages):
        warnings.warn(message, GuardrailWarning, stacklevel=2)
