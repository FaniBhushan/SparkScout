"""Required branch failures stop siblings without hiding budget/cancellation types."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.budgets import BudgetExceeded
from src.models import InputRequest
from src.orchestration.coordinator import OrchestrationError, Orchestrator


class BranchFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_exhaustion_has_same_type_in_both_modes(self):
        request = InputRequest(domain="AI engineering", time_limit_days=30)
        for mode in ("sequential", "parallel"):
            scout = SimpleNamespace(run=AsyncMock(side_effect=BudgetExceeded("token budget")))
            library = SimpleNamespace(run=AsyncMock(return_value=object()))
            coordinator = Orchestrator(scout, library, None)
            with self.assertRaisesRegex(BudgetExceeded, "token budget"):
                await coordinator._run_branches(request, None, mode)

    async def test_failed_or_cancelled_branch_drains_sibling(self):
        for error in (ValueError("invalid response"), asyncio.CancelledError()):
            started = asyncio.Event()
            stopped = asyncio.Event()

            async def slow(*args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            async def fail(*args):
                await started.wait()
                raise error

            coordinator = Orchestrator(
                SimpleNamespace(run=fail), SimpleNamespace(run=slow), None
            )
            request = InputRequest(domain="AI engineering", time_limit_days=30)
            expected = OrchestrationError if isinstance(error, ValueError) else asyncio.CancelledError
            with self.assertRaises(expected):
                await asyncio.wait_for(coordinator._run_branches(request, None, "parallel"), 1)
            self.assertTrue(stopped.is_set())
