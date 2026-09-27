"""Resume, replay, and privacy checks using deterministic local providers."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.application.service import run_prepared_research
from src.testing.demo import OfflineDemoClient
from src.models import SubmittedRunConfiguration, InputRequest
from src.adapters import FrozenFixtureAdapter
from src.persistence import CheckpointError, RunStore
from src.application.preflight import prepare_run
from src.runtime.budgets import BudgetExceeded
from test_application import FakeLLMClient
from test_user_upload import _adapter, _submitted


class InterruptingClient(FakeLLMClient):
    model = "fixed-test-model"
    fail = False

    async def complete(self, prompt, *, max_output_tokens):
        if self.fail and "independent research landscape" in prompt:
            raise RuntimeError("simulated interruption")
        return await super().complete(prompt, max_output_tokens=max_output_tokens)


class CheckpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapters = {"frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")}
        request = InputRequest(domain="AI engineering", time_limit_days=30,
                               desired_candidate_count=1, finalist_count=1)
        self.prepared = prepare_run(SubmittedRunConfiguration(request=request), self.adapters)

    async def test_resume_reuses_scout_and_preserves_budget_and_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            client = InterruptingClient()
            client.fail = True
            with self.assertRaises(RuntimeError):
                await run_prepared_research(self.prepared, client, self.adapters, checkpoint_dir=directory)
            state = json.loads((Path(directory) / "state.json").read_text())["payload"]
            self.assertIn("scout", state["stages"])
            self.assertNotIn("library", state["stages"])
            self.assertGreater(state["budget"]["reserved_model_tokens"], 0)
            resumed = InterruptingClient()
            result = await run_prepared_research(self.prepared, resumed, self.adapters,
                                                  checkpoint_dir=directory, resume=True)
            self.assertEqual(result.run_id, state["run_id"])
            self.assertEqual(resumed.calls, [1000, 3000, 4000, 2000])
            self.assertEqual(result.budget_usage.model_tokens, 3600)
            self.assertGreater(result.budget_usage.reserved_model_tokens, 0)
            replay_client = InterruptingClient()
            replay = await run_prepared_research(self.prepared, replay_client, self.adapters,
                checkpoint_dir=directory, resume=True, frozen=True)
            self.assertEqual(replay.final_proposals, result.final_proposals)
            self.assertEqual(replay_client.calls, [])
            self.assertEqual(replay.budget_usage.model_tokens, result.budget_usage.model_tokens)

    async def test_frozen_miss_makes_no_calls_and_identity_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            client = InterruptingClient()
            client.fail = True
            with self.assertRaises(RuntimeError):
                await run_prepared_research(self.prepared, client, self.adapters, checkpoint_dir=directory)
            client.fail = False
            client.calls.clear()
            with self.assertRaises(CheckpointError):
                await run_prepared_research(self.prepared, client, self.adapters,
                    checkpoint_dir=directory, resume=True, frozen=True)
            self.assertEqual(client.calls, [])
            with self.assertRaisesRegex(CheckpointError, "changed"):
                await run_prepared_research(self.prepared, client, self.adapters,
                    checkpoint_dir=directory, resume=True, mode="parallel")

    async def test_upload_content_and_derived_outputs_never_persist(self):
        adapter = _adapter()
        adapters = {"user_upload": adapter}
        prepared = prepare_run(_submitted(adapter), adapters)
        with tempfile.TemporaryDirectory() as directory:
            first = await run_prepared_research(prepared, OfflineDemoClient(), adapters,
                                                checkpoint_dir=directory)
            raw = (Path(directory) / "state.json").read_text()
            self.assertNotIn("PRIVATE_UPLOAD_TEXT", raw)
            self.assertNotIn("Capstone context", raw)
            self.assertEqual(json.loads(raw)["payload"]["stages"], {})
            # Rebuilding volatile stages cannot replenish an already exhausted
            # provider allowance, even though the uploaded files are local.
            with self.assertRaises(BudgetExceeded):
                await run_prepared_research(prepared, OfflineDemoClient(), adapters,
                                           checkpoint_dir=directory, resume=True)
            with self.assertRaises((ValueError, CheckpointError)):
                await run_prepared_research(prepared, OfflineDemoClient(), {},
                                           checkpoint_dir=directory, resume=True)


class StoreTests(unittest.TestCase):
    def test_checksum_and_exclusive_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory, {})
            try:
                with self.assertRaises(BlockingIOError):
                    RunStore(directory, {}, resume=True)
            finally:
                store.close()
            path = Path(directory) / "state.json"
            data = json.loads(path.read_text())
            data["payload"]["budget"] = {"model_tokens": 0}
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(CheckpointError, "checksum"):
                RunStore(directory, {}, resume=True)

    def test_failed_atomic_replace_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory, {})
            original = store.path.read_bytes()
            try:
                with patch("src.persistence.store.os.replace", side_effect=OSError("disk failure")):
                    with self.assertRaises(OSError):
                        store.save_budget({"model_tokens": 10})
                self.assertEqual(store.path.read_bytes(), original)
                self.assertEqual(list(Path(directory).glob(".state-*")), [])
            finally:
                store.close()
