"""Small deterministic checks; no model calls and no matched values in messages.

These patterns catch obvious credentials and contact details, not all sensitive
data. A clean scan is not proof that content is safe to share.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterator, Mapping

from pydantic import BaseModel, ValidationError


LONG_PROMPT_CHARS = 4000
LARGE_REQUEST_CHARS = 12000
LONG_INPUT_WARNING = (
    "Large input: sending more text can increase model cost and delay. "
    "You can continue without shortening it; configured budgets and provider "
    "context limits still apply."
)
CONTACT_WARNING = (
    "Possible personal contact information detected. Review it before sending "
    "or sharing this content; detection is incomplete."
)
_SECRETS = re.compile(
    r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16})\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----|"
    r"(?i:\b(?:api[_ -]?key|access[_ -]?token|password|secret)"
    r"\s*[=:]\s*[\"']?[A-Za-z0-9_./+\-=]{16,})"
)
_CONTACT = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b|"
    r"(?<!\w)\+\d[\d ()-]{7,}\d\b"
)
_CREDENTIAL_FIELD = re.compile(r"(?:api[_ -]?key|access[_ -]?token|password|secret)", re.I)


class SensitiveContentError(ValueError):
    """Content is blocked without including the detected credential."""


class GuardrailWarning(UserWarning):
    """Non-blocking size or privacy advisory for non-UI callers."""


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, BaseModel):
        yield from _strings(value.model_dump(mode="json"))
    elif isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and isinstance(item, str) and _CREDENTIAL_FIELD.fullmatch(key):
                # JSON separates the field name and value; retain that context
                # so a long password without a provider-specific prefix is caught.
                yield f"{key}={item}"
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _strings(item)


def check_privacy(value: object) -> list[str]:
    """Block recognizable secrets; warn, without quoting, about contact details."""

    contact_found = False
    for text in _strings(value):
        if _SECRETS.search(text):
            raise SensitiveContentError(
                "Possible credential or private key detected. Remove it before "
                "sending or displaying this content. No detected value is shown."
            )
        contact_found = contact_found or bool(_CONTACT.search(text))
    return [CONTACT_WARNING] if contact_found else []


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


def safe_error_message(error: Exception) -> str:
    """Do not echo rejected model/input values through UI or CLI errors."""

    if isinstance(error, ValidationError):
        # Input values and validator context can contain entire documents.
        message = "; ".join(
            f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
            for item in error.errors(include_input=False, include_context=False, include_url=False)
        )
    else:
        message = str(error)
    return _CONTACT.sub("[contact omitted]", _SECRETS.sub("[credential omitted]", message))
