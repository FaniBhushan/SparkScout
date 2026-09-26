"""Exercise the shared run setup with frozen sources and an offline model stub."""

import asyncio
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.adapters import FrozenFixtureAdapter
from src.application import LLMOutputLimits, run_prepared_research, run_research
from src.cli import main
from src.llm.client import ModelReply
from src.models import BudgetSelection, InputRequest, SubmittedRunConfiguration
from src.budgets import BudgetExceeded
from src.preflight import prepare_run
from src.models import OrchestrationResult
from pydantic import ValidationError


def prompt_json(prompt: str, label: str):
    """Read one rendered JSON input without depending on schema formatting."""

    start = prompt.index(label) + len(label)
    block = prompt[start:].lstrip()
    if block.startswith('<data name="'):
        block = block.split("\n", 1)[1]
    value, _ = json.JSONDecoder().raw_decode(block)
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
        elif "draft one implementable capstone proposal" in prompt:
            evidence = prompt_json(prompt, "Evidence chunks:\n")
            reference = {
                "source_id": evidence[0]["source_id"],
                "chunk_id": evidence[0]["chunk_id"],
            }
            payload = {
                "gap_or_differentiation": "Compare retrieval and answer quality separately.",
                "scoped_mvp": ["Build one retrieval pipeline", "Measure answer quality"],
                "non_goals": ["Train a foundation model"],
                "required_data": ["Public test documents"],
                "required_tools": ["Python"],
                "access_assumptions": ["Public documents remain accessible"],
                "technical_approach": "Index documents and evaluate grounded answers.",
                "alternatives": [{
                    "name": "Keyword baseline",
                    "description": "Use exact term matching.",
                    "tradeoff": "Cheaper but less flexible.",
                }],
                "risks": ["Evidence may not generalize."],
                "unknowns": ["Document access terms"],
                "first_kill_test": "Check whether public documents support evaluation.",
                "evaluation_plan": {
                    "method": "Compare a retrieval system with a keyword baseline.",
                    "objective_metrics": ["Recall@5", "citation precision"],
                    "success_criteria": ["Recall@5 exceeds baseline"],
                },
                "citations": [{
                    "claim": "A retrieval evaluation is feasible with the supplied evidence.",
                    "references": [reference],
                }],
            }
        else:
            raise AssertionError("unexpected model prompt")
        return ModelReply(
            text=json.dumps(payload), model="fake", input_tokens=500, output_tokens=100
        )

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
        self.assertEqual(len(result.final_proposals), 1)
        self.assertEqual(result.final_proposals[0].total_score,
                         result.critic.evaluations[0].total_score)
        self.assertEqual({source.provider for source in result.source_manifest}, {"frozen_fixture"})
        self.assertEqual(client.calls, [1000, 3000, 1000, 3000, 4000])
        self.assertEqual(result.budget_usage.model_tokens, 3000)
        self.assertEqual(result.budget_usage.provider_calls, {"frozen_fixture": 2})

    async def test_prepared_run_uses_reviewed_configuration_without_resolving_again(self):
        prepared = prepare_run(
            SubmittedRunConfiguration(request=self.request), self.adapters
        )
        client = FakeLLMClient()

        with patch("src.application.prepare_run", side_effect=AssertionError("re-resolved")):
            result = await run_prepared_research(prepared, client, self.adapters)

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            result.prepared_run.configuration_checksum, prepared.configuration_checksum
        )
        self.assertEqual(result.prepared_run.search, prepared.search)

    async def test_prepared_run_rejects_stale_or_mutated_choices_before_model_calls(self):
        prepared = prepare_run(
            SubmittedRunConfiguration(request=self.request), self.adapters
        )
        client = FakeLLMClient()
        with self.assertRaisesRegex(ValueError, "no longer available"):
            await run_prepared_research(prepared, client, {})
        self.assertEqual(client.calls, [])

        prepared.search.max_sources += 1
        with self.assertRaisesRegex(ValidationError, "checksum"):
            await run_prepared_research(prepared, client, self.adapters)
        self.assertEqual(client.calls, [])

    async def test_run_time_budget_cancels_slow_model_call(self):
        class SlowClient(FakeLLMClient):
            async def complete(self, prompt, *, max_output_tokens):
                await asyncio.sleep(0.03)
                return await super().complete(prompt, max_output_tokens=max_output_tokens)

        prepared = prepare_run(
            SubmittedRunConfiguration(
                request=self.request,
                budgets=BudgetSelection(max_elapsed_seconds=0.001),
            ), self.adapters
        )
        client = SlowClient()
        with self.assertRaisesRegex(BudgetExceeded, "time budget"):
            await run_prepared_research(prepared, client, self.adapters)
        self.assertEqual(client.calls, [])

    async def test_both_run_modes_finalize_multiple_distinct_candidates(self):
        class TwoCandidateClient(FakeLLMClient):
            async def complete(self, prompt, *, max_output_tokens):
                reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
                if "idea-discovery worker" in prompt:
                    payload = json.loads(reply.text)
                    second = dict(payload[0])
                    second.update({
                        "candidate_id": "candidate-02",
                        "title": "Dataset access checker",
                        "problem_statement": "Researchers need to verify dataset access before projects start.",
                        "target_users": ["Researchers"],
                        "proposed_outcome": "An access-checking tool",
                    })
                    return ModelReply(
                        text=json.dumps([*payload, second]), model="fake",
                        input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                    )
                return reply

        request = self.request.model_copy(update={
            "desired_candidate_count": 2, "finalist_count": 2
        })
        for mode in ("sequential", "parallel"):
            with self.subTest(mode=mode):
                result = await run_research(request, TwoCandidateClient(), self.adapters,
                                            mode=mode)

                self.assertEqual(result.status, "completed")
                self.assertEqual([proposal.candidate_id for proposal in result.final_proposals],
                                 ["candidate-01", "candidate-02"])
                self.assertEqual([proposal.rank for proposal in result.final_proposals], [1, 2])

    async def test_invalid_source_configuration_stops_before_model_calls(self):
        client = FakeLLMClient()
        request = self.request.model_copy(update={"domain": "unknown domain"})

        with self.assertRaisesRegex(ValueError, "unknown source domain"):
            await run_research(request, client, self.adapters)

        self.assertEqual(client.calls, [])

    async def test_final_proposal_rejects_unseen_chunk_citation(self):
        class BadCitationClient(FakeLLMClient):
            async def complete(self, prompt, *, max_output_tokens):
                reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
                if "draft one implementable capstone proposal" in prompt:
                    payload = json.loads(reply.text)
                    payload["citations"][0]["references"][0]["chunk_id"] = "unseen-c0"
                    return ModelReply(
                        text=json.dumps(payload), model="fake",
                        input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                    )
                return reply

        with self.assertRaisesRegex(ValueError, "outside its supplied evidence"):
            await run_research(self.request, BadCitationClient(), self.adapters)

    async def test_final_proposal_reports_coverage_when_scoring_cites_no_chunks(self):
        class UncitedJudgeClient(FakeLLMClient):
            async def complete(self, prompt, *, max_output_tokens):
                reply = await super().complete(prompt, max_output_tokens=max_output_tokens)
                if "evidence-based candidate assessor" in prompt:
                    payload = json.loads(reply.text)
                    for judgment in [*payload["criteria"].values(),
                                     *payload["hard_gates"].values()]:
                        judgment["evidence"] = []
                    return ModelReply(
                        text=json.dumps(payload), model="fake",
                        input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                    )
                return reply

        result = await run_research(self.request, UncitedJudgeClient(), self.adapters)

        self.assertEqual(result.status, "insufficient_coverage")
        self.assertEqual(result.final_proposals, [])
        self.assertTrue(any("no cited Library chunks" in item for item in result.warnings))

    async def test_serialized_result_rejects_tampered_proposal_citation(self):
        result = await run_research(self.request, FakeLLMClient(), self.adapters)
        data = result.model_dump(mode="python")
        data["final_proposals"][0]["citations"][0]["references"][0]["chunk_id"] = "wrong"

        with self.assertRaisesRegex(ValidationError, "unknown or mismatched chunk"):
            OrchestrationResult.model_validate(data)

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
        self.assertEqual(len(result["final_proposals"]), 1)
        self.assertEqual({source["provider"] for source in result["source_manifest"]},
                         {"frozen_fixture"})

    def test_standalone_structured_request_returns_final_proposal(self):
        request = InputRequest(
            domain="AI engineering",
            time_limit_days=30,
            desired_candidate_count=1,
            finalist_count=1,
        )
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(request.model_dump_json(), encoding="utf-8")
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test"}),
                patch("src.cli.OpenAITextClient", return_value=FakeLLMClient()),
                redirect_stdout(output),
            ):
                exit_code = main([
                    "--request", str(request_path),
                    "--fixture-set", "ai_engineering_capstone_01",
                    "--model", "fake",
                ])

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["final_proposals"]), 1)


if __name__ == "__main__":
    unittest.main()
