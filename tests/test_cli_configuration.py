"""The CLI accepts the same reviewed configuration the UI can download."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.ui.cli import main
from src.demo import OfflineDemoClient
from src.llm.client import ModelReply
from src.models import (
    BudgetSelection,
    InputRequest,
    InterpretationReview,
    PromptInterpretationDraft,
    PromptSuggestions,
    RequestSuggestions,
    SearchConfiguration,
    SubmittedRunConfiguration,
)
from tests.test_application import FakeLLMClient


class DraftOnlyClient:
    def __init__(self):
        self.calls = 0

    async def complete(self, prompt, *, max_output_tokens):
        self.calls += 1
        return ModelReply(
            text=json.dumps({"request": {"domain": "AI engineering", "time_limit_days": 30}}),
            model="offline-fake", input_tokens=100, output_tokens=20,
        )


class CLIConfigurationTests(unittest.TestCase):
    def test_large_prompt_warns_on_stderr_and_preserves_json_stdout(self):
        client = DraftOnlyClient()
        output, errors = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.txt"
            path.write_text("AI engineering " * 400, encoding="utf-8")
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
                patch("src.ui.cli.OpenAITextClient", return_value=client),
                redirect_stdout(output), redirect_stderr(errors),
            ):
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("always")
                    main(["--prompt-file", str(path), "--fixture-set", "ai_engineering_capstone_01",
                          "--model", "offline-fake"])
        self.assertEqual(client.calls, 1)
        self.assertEqual(json.loads(output.getvalue())["original_prompt"], ("AI engineering " * 400).strip())
        self.assertIn("cost and delay", errors.getvalue())

    def test_full_config_uses_shared_preflight_and_returns_provenance(self):
        submitted = SubmittedRunConfiguration(
            request=InputRequest(
                domain="AI engineering", time_limit_days=30,
                desired_candidate_count=1, finalist_count=1,
            ),
            search=SearchConfiguration(mode="advanced", preset="build-oriented",
                                       provider_ids=["frozen_fixture"]),
            budgets=BudgetSelection(max_source_bytes=500_000),
        )
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "configuration.json"
            path.write_text(submitted.model_dump_json(), encoding="utf-8")
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
                patch("src.ui.cli.OpenAITextClient", return_value=FakeLLMClient()),
                redirect_stdout(output),
            ):
                exit_code = main([
                    "--config", str(path), "--fixture-set", "ai_engineering_capstone_01",
                    "--model", "offline-fake",
                ])
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["prepared_run"]["submitted"]["search"]["preset"],
                         "build-oriented")
        self.assertEqual(result["prepared_run"]["search"]["providers"][0]["provider_id"],
                         "frozen_fixture")
        self.assertEqual(result["prepared_run"]["budgets"]["max_source_bytes"], 500_000)

    def test_prompt_file_only_drafts_and_never_starts_research(self):
        client = DraftOnlyClient()
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.txt"
            path.write_text("AI engineering in 30 days", encoding="utf-8")
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
                patch("src.ui.cli.OpenAITextClient", return_value=client),
                redirect_stdout(output),
            ):
                exit_code = main([
                    "--prompt-file", str(path),
                    "--fixture-set", "ai_engineering_capstone_01",
                    "--model", "offline-fake",
                ])
        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(json.loads(output.getvalue())["suggestions"]["request"]["time_limit_days"], 30)

    def test_offline_demo_needs_no_api_key_or_model(self):
        submitted = SubmittedRunConfiguration(request=InputRequest(
            domain="AI engineering", time_limit_days=30,
            desired_candidate_count=1, finalist_count=1,
        ))
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "configuration.json"
            path.write_text(submitted.model_dump_json(), encoding="utf-8")
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": ""}),
                redirect_stdout(output),
            ):
                main([
                    "--config", str(path), "--fixture-set", "ai_engineering_capstone_01",
                    "--offline-demo",
                ])
        self.assertEqual(json.loads(output.getvalue())["status"], "completed")

    def test_cli_upload_requires_confirmation_and_redacts_exported_chunks(self):
        request = InputRequest(
            domain="AI engineering", time_limit_days=30,
            desired_candidate_count=1, finalist_count=1,
        )
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(request.model_dump_json(), encoding="utf-8")
            paths = []
            for index in range(3):
                path = Path(directory) / f"notes-{index}.txt"
                path.write_text(f"PRIVATE_CLI_UPLOAD_{index} Capstone context and evaluation notes.",
                                encoding="utf-8")
                paths.extend(["--upload", str(path)])
            with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
                main(["--request", str(request_path), "--model", "offline-test", *paths])
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
                patch("src.ui.cli.OpenAITextClient", return_value=OfflineDemoClient()),
                redirect_stdout(output),
            ):
                main(["--request", str(request_path), "--model", "offline-test",
                      "--confirm-upload-rights", *paths])
        exported = output.getvalue()
        self.assertNotIn("PRIVATE_CLI_UPLOAD", exported)
        result = json.loads(exported)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(all(chunk["text_redacted"] for chunk in result["library"]["chunks"]))

    def test_saved_draft_and_review_run_without_reinterpreting(self):
        draft = PromptInterpretationDraft(
            original_prompt="AI engineering in 30 days",
            suggestions=PromptSuggestions(request=RequestSuggestions(
                domain="AI engineering", time_limit_days=30,
                desired_candidate_count=1, finalist_count=1,
            )),
        )
        review = InterpretationReview(accepted_paths={
            "request.domain", "request.time_limit_days",
            "request.desired_candidate_count", "request.finalist_count",
        })
        client = FakeLLMClient()
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            draft_path = Path(directory) / "draft.json"
            review_path = Path(directory) / "review.json"
            draft_path.write_text(draft.model_dump_json(), encoding="utf-8")
            review_path.write_text(review.model_dump_json(), encoding="utf-8")
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
                patch("src.ui.cli.OpenAITextClient", return_value=client),
                redirect_stdout(output),
            ):
                main([
                    "--draft-file", str(draft_path), "--review-file", str(review_path),
                    "--fixture-set", "ai_engineering_capstone_01", "--model", "offline-fake",
                ])
        result = json.loads(output.getvalue())
        self.assertEqual(result["prepared_run"]["submitted"]["original_prompt"], draft.original_prompt)
        self.assertEqual(result["prepared_run"]["field_origins"]["request.domain"], "deduced")
        self.assertEqual(len(client.calls), 5)


if __name__ == "__main__":
    unittest.main()
