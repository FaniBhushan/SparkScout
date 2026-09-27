"""A single optional retry, with server delay and run deadline enforcement."""

import asyncio
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import isfinite


def retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, seconds) if isfinite(seconds) else None


async def wait_before_retry(error, budget) -> None:
    """Decline long waits instead of retrying sooner than a provider requested."""
    delay = error.retry_after
    if delay is None:
        delay = random.uniform(0.25, 0.75)
    if delay > 30 or delay >= budget.remaining_seconds():
        raise error
    await asyncio.sleep(delay)
    budget.check_time()
