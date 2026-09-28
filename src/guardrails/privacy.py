"""Deterministic privacy checks; no matched values in diagnostic messages.

These patterns catch obvious credentials and contact details, not all sensitive
data. A clean scan is not proof that content is safe to share.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from pydantic import BaseModel, ValidationError


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
_SAFE_SCHEMA_FIELDS = frozenset({
    "candidate_id", "origin", "title", "problem_statement", "target_users",
    "proposed_outcome", "why_it_matters", "evaluation_method", "domain_tags",
    "required_data", "required_tools", "access_assumptions", "evidence",
    "source_id", "chunk_id", "stance", "note",
})


class SensitiveContentError(ValueError):
    """Content is blocked without including the detected credential."""


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


def safe_error_message(error: Exception) -> str:
    """Do not echo rejected model/input values through UI or CLI errors."""

    # Orchestration wraps failures with their raw exception text. Follow the
    # cause for model schema failures so the UI never displays rejected output.
    if isinstance(error.__cause__, ValidationError):
        stage = getattr(error, "stage", "research")
        details = safe_validation_summary(error.__cause__)
        suffix = f" Schema issue: {details}." if details else ""
        return (
            f"The {stage} stage could not read the model's response after retrying. "
            f"Your configuration is still available. Try Start research again.{suffix}"
        )
    if isinstance(error, ValidationError):
        message = safe_validation_summary(error)
    else:
        message = str(error)
    return _CONTACT.sub("[contact omitted]", _SECRETS.sub("[credential omitted]", message))


def safe_validation_hints(error: ValidationError) -> list[str]:
    """Return schema paths and error codes without model values or messages."""

    summaries = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        path = []
        for part in item["loc"]:
            if isinstance(part, int):
                path.append(str(part))
            elif isinstance(part, str) and part in _SAFE_SCHEMA_FIELDS:
                path.append(part)
            else:
                # Unknown keys can be model-generated and may contain user data.
                path.append("field")
        error_type = item.get("type", "invalid")
        if not isinstance(error_type, str) or not re.fullmatch(r"[a-z0-9_.-]{1,40}", error_type):
            error_type = "invalid"
        summaries.append(f"{'.'.join(path) or 'response'} ({error_type})")
    return summaries[:5]


def safe_validation_summary(error: ValidationError) -> str:
    """Format the safe field-level schema hints for a short user-facing message."""

    return "; ".join(safe_validation_hints(error))
