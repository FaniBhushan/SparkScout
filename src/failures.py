"""Stable failure categories for callers, traces, and persisted run metadata."""


class RetryableFailure(RuntimeError):
    """A transient failure with an optional provider-requested delay."""

    retry_after = None


def failure_code(error: BaseException) -> str:
    """Classify safely without storing exception messages or provider bodies."""
    explicit = getattr(error, "code", None)
    if explicit:
        return explicit
    names = {
        "BudgetExceeded": "budget_exhausted", "ValidationError": "invalid_output",
        "TimeoutError": "timeout", "CancelledError": "cancelled",
        "ModelResponseError": "invalid_model_response",
        "SourceAdapterError": "provider_error",
    }
    return names.get(type(error).__name__, "stage_failure")
