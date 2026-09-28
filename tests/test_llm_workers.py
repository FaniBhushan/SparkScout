"""Prompt wiring tests for Scout and Library LLM components."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from src.evaluation import load_evaluation_configuration
from src.llm.client import ModelReply, ModelResponseError
from src.llm.critic_llm import LLMCandidateJudge
from src.llm.library_llm import LLMLibraryQueryPlanner
from src.llm.scout_llm import LLMCandidateGenerator, LLMScoutQueryPlanner
from src.models import CandidateAssessment, CandidateIdea, InputRequest, LibraryResult, ResolvedSearchConfiguration, SourceRecord
from src.models.source_record import RetrievalStatus, SourceChunk
from src.observability import RunTracer
from src.retrieval import InMemoryRetriever
from src.workers.critic_worker import CriticWorker


class FakeLLMClient:
    def __init__(
        self,
        text: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.estimated_cost_usd = estimated_cost_usd
        self.calls: list[tuple[str, int]] = []

    async def complete(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        self.calls.append((prompt, max_output_tokens))
        return ModelReply(
            text=self.text,
            model="fake-model",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            estimated_cost_usd=self.estimated_cost_usd,
        )


class LLMWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.request = InputRequest(domain="AI engineering", time_limit_days=30)
        self.search = ResolvedSearchConfiguration(
            domain="AI engineering",
            providers=[{
                "provider_id": "fixture",
                "source_types": ["dataset"],
                "content_types": ["text"],
            }],
            content_types=["text"],
            max_queries=2,
            max_results_per_query=2,
            max_sources=2,
        )
        self.source = SourceRecord(
            source_id="source-1",
            provider="fixture",
            source_type="dataset",
            title="Capstone dataset",
            captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            canonical_url="https://example.org/dataset",
            query_id="scout-q-01",
            abstract_or_snippet="Students struggle to find suitable datasets.",
            content_hash="source-hash",
            retrieval_status=RetrievalStatus.SUCCESS,
        )

    async def test_scout_planner_renders_and_validates_queries(self) -> None:
        client = FakeLLMClient(json.dumps([{
            "query_id": "scout-q-01",
            "provider_id": "fixture",
            "text": "student dataset pain points",
            "source_types": ["dataset"],
            "content_types": ["text"],
            "max_results": 2,
        }]))

        queries = await LLMScoutQueryPlanner(client, max_output_tokens=500).plan(
            self.request, self.search
        )

        self.assertEqual(queries[0].query_id, "scout-q-01")
        prompt, limit = client.calls[0]
        self.assertEqual(limit, 500)
        from test_application import prompt_json
        self.assertEqual(prompt_json(prompt, "Request:\n")["domain"], "AI engineering")
        search = prompt_json(prompt, "Resolved search configuration:\n")
        self.assertEqual(search["providers"][0]["provider_id"], "fixture")

    async def test_library_planner_uses_independent_prompt(self) -> None:
        client = FakeLLMClient(json.dumps([{
            "query_id": "library-q-01",
            "provider_id": "fixture",
            "text": "AI engineering datasets",
            "source_types": ["dataset"],
            "content_types": ["text"],
            "max_results": 2,
        }]))

        queries = await LLMLibraryQueryPlanner(client, max_output_tokens=400).plan(
            self.request, self.search
        )

        self.assertEqual(queries[0].query_id, "library-q-01")
        prompt, limit = client.calls[0]
        self.assertEqual(limit, 400)
        self.assertIn("independent research landscape", prompt)
        self.assertNotIn("candidate-01", prompt)

    async def test_candidate_generator_uses_compact_sources(self) -> None:
        client = FakeLLMClient(json.dumps([{
            "candidate_id": "candidate-01",
            "title": "Dataset fit checker",
            "problem_statement": "Students cannot assess dataset fit quickly.",
            "target_users": ["Students"],
            "proposed_outcome": "A dataset fit checker",
            "why_it_matters": "Reduces wasted project setup time.",
            "evidence": [{"source_id": "source-1"}],
        }]))

        candidates = await LLMCandidateGenerator(client, max_output_tokens=800).generate(
            self.request, [self.source]
        )

        self.assertEqual(candidates[0].candidate_id, "candidate-01")
        prompt, limit = client.calls[0]
        self.assertEqual(limit, 800)
        self.assertIn("source-1", prompt)
        self.assertIn("Students struggle to find suitable datasets.", prompt)
        self.assertNotIn("source-hash", prompt)
        self.assertNotIn("scout-q-01", prompt)

    async def test_empty_sources_skip_candidate_model_call(self) -> None:
        client = FakeLLMClient("invalid")

        candidates = await LLMCandidateGenerator(client, max_output_tokens=800).generate(
            self.request, []
        )

        self.assertEqual(candidates, [])
        self.assertEqual(client.calls, [])

    async def test_invalid_model_json_is_rejected(self) -> None:
        client = FakeLLMClient("not JSON")

        with self.assertRaises(ValidationError):
            await LLMScoutQueryPlanner(client, max_output_tokens=500).plan(
                self.request, self.search
            )
        self.assertEqual(len(client.calls), 2)

    async def test_query_envelopes_work_in_both_planners_without_paid_retry(self) -> None:
        query = {
            "query_id": "q-01", "provider_id": "fixture", "text": "dataset fit",
            "source_types": ["dataset"], "content_types": ["text"], "max_results": 2,
        }
        for planner in (LLMScoutQueryPlanner, LLMLibraryQueryPlanner):
            for key in ("items", "queries"):
                with self.subTest(planner=planner.__name__, key=key):
                    client = FakeLLMClient(json.dumps({key: [query]}))
                    result = await planner(client, max_output_tokens=500).plan(
                        self.request, self.search
                    )
                    self.assertEqual(result[0].text, query["text"])
                    self.assertEqual(len(client.calls), 1)

    def test_query_prompt_schema_matches_provider_json_object_mode(self) -> None:
        from src.prompts import render_prompt, parse_model_output

        for name in ("scout_query_planner", "library_query_planner"):
            prompt = render_prompt(name, REQUEST_JSON=self.request, SEARCH_CONFIG_JSON=self.search)
            schema = json.loads(prompt.split("# Output schema\n\n")[1])
            self.assertEqual(schema["type"], "object")
            self.assertEqual(schema["required"], ["queries"])
            self.assertEqual(schema["properties"]["queries"]["type"], "array")
            self.assertIn("$defs", schema)
            self.assertEqual(parse_model_output(name, {"queries": []}), [])

    async def test_query_repair_preserves_validation_and_rejects_ambiguity(self) -> None:
        query = {
            "query_id": "q-01", "provider_id": "fixture", "text": "dataset fit",
            "source_types": ["dataset"], "content_types": ["text"], "max_results": 2,
        }
        invalid_outputs = [
            {"items": [query], "extra": "must not be discarded"},
            {"queries": [{**query, "unknown_field": "invalid"}]},
            {"items": [{**query, "max_results": "2"}]},
            {"queries": [{key: value for key, value in query.items() if key != "text"}]},
            {"items": query},
        ]
        for planner in (LLMScoutQueryPlanner, LLMLibraryQueryPlanner):
            for output in invalid_outputs:
                with self.subTest(planner=planner.__name__, output=output):
                    client = FakeLLMClient(json.dumps(output))
                    with self.assertRaises(ValidationError):
                        await planner(client, max_output_tokens=500).plan(self.request, self.search)
                    self.assertEqual(len(client.calls), 2)

    def test_wrapped_validation_error_has_actionable_message_without_model_output(self) -> None:
        from src.guardrails import safe_error_message
        from src.orchestration.coordinator import OrchestrationError
        from src.prompts import parse_model_output

        try:
            parse_model_output("scout_query_planner", '{"unexpected": "private model text"}')
        except ValidationError as error:
            try:
                raise OrchestrationError("scout", error) from error
            except OrchestrationError as wrapped:
                message = safe_error_message(wrapped)
        self.assertIn("scout stage", message)
        self.assertIn("Start research", message)
        self.assertNotIn("private model text", message)
        self.assertNotIn("input_value", message)

    async def test_schema_validation_retries_once_and_records_each_usage(self) -> None:
        valid = json.dumps([{
            "query_id": "scout-q-01", "provider_id": "fixture", "text": "dataset fit",
            "source_types": ["dataset"], "content_types": ["text"], "max_results": 2,
        }])

        class SequentialClient:
            def __init__(self):
                self.calls = []

            async def complete(self, prompt, *, max_output_tokens):
                self.calls.append(prompt)
                return ModelReply(
                    text="invalid JSON" if len(self.calls) == 1 else valid,
                    model="fake-model", input_tokens=10, output_tokens=3,
                )

        client = SequentialClient()
        queries = await LLMScoutQueryPlanner(client, max_output_tokens=500).plan(
            self.request, self.search
        )

        self.assertEqual(queries[0].query_id, "scout-q-01")
        self.assertEqual(len(client.calls), 2)
        self.assertIn("Schema correction", client.calls[1])

    def _critic_inputs(self):
        candidate = CandidateIdea(
            candidate_id="candidate-01",
            title="Dataset fit checker",
            problem_statement="Students cannot assess dataset fit quickly.",
            target_users=["Students"],
            proposed_outcome="A dataset fit checker",
            why_it_matters="Reduces setup time.",
        )
        chunk = SourceChunk(
            chunk_id="source-1-c0",
            source_id="source-1",
            ordinal=0,
            text="Students struggle to find suitable datasets.",
            content_hash="chunk-hash",
        )
        library = LibraryResult(sources=[self.source], chunks=[chunk])
        rubric = load_evaluation_configuration()
        return candidate, library, rubric

    async def test_critic_assessment_scores_and_traces_usage(self) -> None:
        candidate, library, rubric = self._critic_inputs()
        reference = {"source_id": "source-1", "chunk_id": "source-1-c0"}
        client = FakeLLMClient(
            json.dumps({
                "criteria": {
                    key: {"score": 4, "rationale": "Supported by source.", "evidence": [reference]}
                    for key in rubric.criteria
                },
                "hard_gates": {
                    key: {"passed": True, "rationale": "Supported by source.", "evidence": [reference]}
                    for key in rubric.hard_gates
                },
            }),
            input_tokens=130,
            output_tokens=40,
            estimated_cost_usd=0.002,
        )
        with tempfile.TemporaryDirectory() as directory:
            tracer = RunTracer("critic-test", log_dir=Path(directory), console=False)
            try:
                judge = LLMCandidateJudge(client, max_output_tokens=600, tracer=tracer)
                result = await CriticWorker(
                    InMemoryRetriever(library.chunks), judge, tracer=tracer
                ).run(self.request, [candidate], library, rubric)
            finally:
                tracer.close()
            events = [json.loads(line) for line in tracer.trace_path.read_text().splitlines()]

        self.assertEqual(result.evaluations[0].total_score, 80)
        self.assertTrue(result.evaluations[0].gate_passed)
        prompt, limit = client.calls[0]
        self.assertEqual(limit, 600)
        self.assertIn("source-1-c0", prompt)
        self.assertNotIn("chunk-hash", prompt)
        usage = next(event for event in events if event["event"] == "usage")
        self.assertEqual(usage["stage"], "critic_candidate_judge")
        self.assertEqual(usage["task_id"], candidate.candidate_id)
        self.assertEqual((usage["prompt_tokens"], usage["completion_tokens"]), (130, 40))
        self.assertEqual(usage["estimated_cost_usd"], 0.002)

    async def test_critic_skips_candidate_with_unretrieved_citation(self) -> None:
        candidate, library, rubric = self._critic_inputs()
        bad_reference = {"source_id": "unseen", "chunk_id": "unseen-c0"}
        client = FakeLLMClient(json.dumps({
            "criteria": {
                key: {"score": 4, "rationale": "Claim.", "evidence": [bad_reference]}
                for key in rubric.criteria
            },
            "hard_gates": {
                key: {"passed": True, "rationale": "Claim.", "evidence": [bad_reference]}
                for key in rubric.hard_gates
            },
        }))

        result = await CriticWorker(
            InMemoryRetriever(library.chunks),
            LLMCandidateJudge(client, max_output_tokens=600),
        ).run(self.request, [candidate], library, rubric)
        self.assertEqual(result.evaluations, [])
        self.assertIn("candidate-01", result.warnings[0])

    async def test_critic_fills_source_only_citation_when_chunk_match_is_unique(self) -> None:
        candidate, library, rubric = self._critic_inputs()
        source_only_reference = {"source_id": "source-1"}
        client = FakeLLMClient(json.dumps({
            "criteria": {
                key: {"score": 4, "rationale": "Supported by source.", "evidence": [source_only_reference]}
                for key in rubric.criteria
            },
            "hard_gates": {
                key: {"passed": True, "rationale": "Supported by source.", "evidence": [source_only_reference]}
                for key in rubric.hard_gates
            },
        }))

        result = await CriticWorker(
            InMemoryRetriever(library.chunks),
            LLMCandidateJudge(client, max_output_tokens=600),
        ).run(self.request, [candidate], library, rubric)

        self.assertEqual(len(result.evaluations), 1)
        reference = result.evaluations[0].criteria[0].evidence[0]
        self.assertEqual((reference.source_id, reference.chunk_id), ("source-1", "source-1-c0"))
        self.assertTrue(any("unique retrieved chunk ID" in warning for warning in result.warnings))

    async def test_invalid_critic_candidate_does_not_stop_other_candidates(self) -> None:
        candidate, library, rubric = self._critic_inputs()
        second = candidate.model_copy(update={"candidate_id": "candidate-02", "title": "Second idea"})

        class SequenceJudge:
            async def assess(self, request, current, evidence, evaluation):
                source = "unseen" if current.candidate_id == "candidate-01" else "source-1"
                reference = {"source_id": source, "chunk_id": f"{source}-c0"}
                return CandidateAssessment.model_validate({
                    "criteria": {
                        key: {"score": 4, "rationale": "Reviewed.", "evidence": [reference]}
                        for key in evaluation.criteria
                    },
                    "hard_gates": {
                        key: {"passed": True, "rationale": "Reviewed.", "evidence": [reference]}
                        for key in evaluation.hard_gates
                    },
                })

        result = await CriticWorker(
            InMemoryRetriever(library.chunks), SequenceJudge()
        ).run(self.request, [candidate, second], library, rubric)

        self.assertEqual([item.candidate_id for item in result.evaluations], ["candidate-02"])
        self.assertEqual(len(result.warnings), 1)

    async def test_malformed_output_records_usage_and_error(self) -> None:
        client = FakeLLMClient("invalid JSON", input_tokens=20, output_tokens=3)
        with tempfile.TemporaryDirectory() as directory:
            tracer = RunTracer("invalid-output", log_dir=Path(directory), console=False)
            try:
                with self.assertRaises(ValidationError):
                    await LLMLibraryQueryPlanner(
                        client, max_output_tokens=100, tracer=tracer
                    ).plan(self.request, self.search)
            finally:
                tracer.close()
            events = [json.loads(line) for line in tracer.trace_path.read_text().splitlines()]

        self.assertEqual(
            [event["event"] for event in events],
            ["start", "usage", "response_retry", "usage", "error"],
        )
        self.assertEqual(events[1]["completion_tokens"], 3)
        self.assertNotIn("estimated_cost_usd", events[1])
        self.assertEqual(events[3]["completion_tokens"], 3)

    async def test_incomplete_response_records_reported_usage(self) -> None:
        class IncompleteClient:
            async def complete(self, prompt, *, max_output_tokens):
                raise ModelResponseError(
                    "model response status was 'incomplete'",
                    reply=ModelReply(
                        text="", model="fake-model", input_tokens=30, output_tokens=5
                    ),
                )

        with tempfile.TemporaryDirectory() as directory:
            tracer = RunTracer("incomplete-output", log_dir=Path(directory), console=False)
            try:
                with self.assertRaises(ModelResponseError):
                    await LLMScoutQueryPlanner(
                        IncompleteClient(), max_output_tokens=100, tracer=tracer
                    ).plan(self.request, self.search)
            finally:
                tracer.close()
            events = [json.loads(line) for line in tracer.trace_path.read_text().splitlines()]

        self.assertEqual([event["event"] for event in events], ["start", "usage", "error"])
        self.assertEqual(events[1]["prompt_tokens"], 30)
        self.assertEqual(events[1]["completion_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
