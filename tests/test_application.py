"""Exercise the shared run setup with frozen sources and an offline model stub."""

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.adapters import FrozenFixtureAdapter
from src.application import LLMOutputLimits, run_research
from src.cli import main
from src.llm.client import ModelReply
from src.models import InputRequest


def prompt_json(prompt: str, label: str):
    """Read one rendered JSON input without depending on schema formatting."""

    start = prompt.index(label) + len(label)
    value, _ = json.JSONDecoder().raw_decode(prompt[start:].lstrip())
    return value


class FakeLLMClient:
    def __init__(self):
        self.calls = []

    async def complete(self, prompt, *, max_output_tokens):
        self.calls.append(max_output_tokens)
        if "bounded web searches for ScoutSpark's Scout worker" in prompt:
            search = prompt_json(prompt, "Resolved search configuration:\n")
            payload = [self._query("scout-q-01", search)]
        elif "independent research landscape" in prompt:
            search = prompt_json(prompt, "Resolved search configuration:\n")
            payload = [self._query("library-q-01", search)]
        elif "idea-discovery worker" in prompt:
            sources = prompt_json(prompt, "Source records:\n")
            payload = [{
                "candidate_id": "candidate-01",
                "title": "Retrieval evaluation capstone",
                "problem_statement": "Students need evidence for retrieval application evaluation.",
                "target_users": ["Students"],
                "proposed_outcome": "A measured retrieval prototype",
                "why_it_matters": "Makes evaluation reproducible.",
                "evidence": [{"source_id": sources[0]["source_id"]}],
            }]
        elif "evidence-based candidate assessor" in prompt:
            rubric = prompt_json(prompt, "Evaluation configuration:\n")
            evidence = prompt_json(prompt, "Retrieved evidence chunks:\n")
            reference = {
                "source_id": evidence[0]["source_id"],
                "chunk_id": evidence[0]["chunk_id"],
            }
            payload = {
                "criteria": {
                    key: {"score": 4, "rationale": "Supported.", "evidence": [reference]}
                    for key in rubric["criteria"]
                },
                "hard_gates": {
                    key: {"passed": True, "rationale": "Supported.", "evidence": [reference]}
                    for key in rubric["hard_gates"]
                },
            }
        else:
            raise AssertionError("unexpected model prompt")
        return ModelReply(text=json.dumps(payload), model="fake")

    @staticmethod
    def _query(query_id, search):
        provider = search["providers"][0]
        return {
            "query_id": query_id,
            "provider_id": provider["provider_id"],
            "text": "retrieval evaluation capstone",
            "source_types": provider["source_types"],
            "content_types": provider["content_types"],
            "max_results": search["max_results_per_query"],
        }


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = InputRequest(
            domain="AI engineering",
            time_limit_days=30,
            desired_candidate_count=1,
            finalist_count=1,
        )
        self.adapters = {
            "frozen_fixture": FrozenFixtureAdapter("ai_engineering_capstone_01")
        }

    async def test_structured_request_runs_through_frozen_fixture(self):
        client = FakeLLMClient()

        result = await run_research(self.request, client, self.adapters)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.mode, "sequential")
        self.assertEqual(result.finalist_candidate_ids, ["candidate-01"])
        self.assertEqual(result.retrieval_index.indexed_chunk_count, 3)
        self.assertEqual({source.provider for source in result.source_manifest}, {"frozen_fixture"})
        self.assertEqual(client.calls, [1000, 3000, 1000, 3000])

    async def test_invalid_source_configuration_stops_before_model_calls(self):
        client = FakeLLMClient()
        request = self.request.model_copy(update={"domain": "unknown domain"})

        with self.assertRaisesRegex(ValueError, "unknown source domain"):
            await run_research(request, client, self.adapters)

        self.assertEqual(client.calls, [])

    def test_output_limits_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            LLMOutputLimits(critic_assessment=0)


class CLITests(unittest.TestCase):
    def test_case_entry_point_returns_json_without_live_search(self):
        case_path = (
            Path(__file__).resolve().parents[1]
            / "evals/cases/development/ai_engineering_capstone_01.json"
        )
        output = StringIO()
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
            patch("src.cli.OpenAITextClient", return_value=FakeLLMClient()),
            redirect_stdout(output),
        ):
            exit_code = main(["--case", str(case_path), "--model", "fake"])

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["mode"], "sequential")
        self.assertEqual(result["status"], "insufficient_coverage")
        self.assertEqual({source["provider"] for source in result["source_manifest"]},
                         {"frozen_fixture"})


if __name__ == "__main__":
    unittest.main()
