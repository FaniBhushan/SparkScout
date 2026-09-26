"""Prompt interpretation is a review step, not an implicit research run."""

import asyncio
import json
import unittest

from pydantic import ValidationError

from src.interpretation import confirm_interpretation
from src.guardrails import GuardrailWarning
from src.llm.client import ModelReply
from src.llm.request_interpreter import LLMRequestInterpreter
from src.models import InterpretationReview
from src.preflight import prepare_run


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete(self, prompt, *, max_output_tokens):
        self.calls.append((prompt, max_output_tokens))
        return ModelReply(text=json.dumps(self.payload), model="offline-fake")


class NoSearchAdapter:
    async def search(self, query):
        raise AssertionError("drafting and preflight must not search")


class InterpretationTests(unittest.TestCase):
    def setUp(self):
        self.adapters = {"github": NoSearchAdapter(), "tavily": NoSearchAdapter()}

    def draft(self, payload, prompt="AI engineering capstone in 30 days"):
        client = FakeLLM(payload)
        interpreter = LLMRequestInterpreter(client)
        result = asyncio.run(interpreter.draft(prompt, self.adapters))
        return result, client

    def test_explicit_draft_action_makes_one_bounded_call(self):
        client = FakeLLM({"request": {"domain": "AI engineering", "time_limit_days": 30}})
        interpreter = LLMRequestInterpreter(client)
        self.assertEqual(client.calls, [])

        draft = asyncio.run(interpreter.draft("AI engineering in 30 days", self.adapters))

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1], 1800)
        self.assertEqual(draft.original_prompt, "AI engineering in 30 days")
        with self.assertWarnsRegex(GuardrailWarning, "cost and delay"):
            large_draft = asyncio.run(interpreter.draft("x" * 4001, self.adapters))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(large_draft.original_prompt, "x" * 4001)
        self.assertIn("x" * 4001, client.calls[-1][0])
        self.assertTrue(large_draft.warnings)

    def test_missing_required_fields_are_not_guessed(self):
        draft, _ = self.draft({"request": {"interests": ["education"]}})
        with self.assertRaises(ValidationError):
            confirm_interpretation(
                draft, InterpretationReview(accepted_paths={"request.interests"})
            )

    def test_explicit_correction_wins_and_provenance_survives_preflight(self):
        draft, _ = self.draft({
            "request": {"domain": "AI engineering", "time_limit_days": 30},
            "search": {"preset": "build-oriented"},
        })
        submitted = confirm_interpretation(draft, InterpretationReview(
            accepted_paths={"request.domain", "request.time_limit_days", "search.preset"},
            overrides={"request.time_limit_days": 45},
        ))
        prepared = prepare_run(submitted, self.adapters)

        self.assertEqual(prepared.request.time_limit_days, 45)
        self.assertEqual(prepared.submitted.original_prompt, draft.original_prompt)
        self.assertEqual(prepared.field_origins["request.domain"], "deduced")
        self.assertEqual(prepared.field_origins["request.time_limit_days"], "explicit")
        self.assertEqual(prepared.submitted.search.preset, "build-oriented")

    def test_unsupported_choices_are_reported_and_cannot_be_accepted(self):
        draft, _ = self.draft({
            "request": {"domain": "AI engineering", "time_limit_days": 30},
            "search": {"provider_ids": ["arxiv"], "content_types": ["full_text"]},
        })
        self.assertEqual({issue.kind for issue in draft.issues}, {"unsupported"})
        self.assertEqual(
            {issue.path for issue in draft.issues},
            {"search.provider_ids", "search.content_types"},
        )
        with self.assertRaisesRegex(ValueError, "review or acknowledge"):
            confirm_interpretation(draft, InterpretationReview(
                accepted_paths={"request.domain", "request.time_limit_days"},
            ))
        with self.assertRaisesRegex(ValueError, "unsupported suggestion"):
            confirm_interpretation(draft, InterpretationReview(
                accepted_paths={"request.domain", "request.time_limit_days", "search.provider_ids"},
                acknowledged_issues={0, 1},
            ))
        submitted = confirm_interpretation(draft, InterpretationReview(
            accepted_paths={"request.domain", "request.time_limit_days"},
            acknowledged_issues={0, 1},
        ))
        self.assertEqual(submitted.search.provider_ids, [])

    def test_uncertain_and_other_domain_suggestions_need_explicit_choice(self):
        draft, _ = self.draft({
            "request": {"domain": "Urban ecology", "time_limit_days": 30},
            "search": {"allow_other_domain": True},
            "uncertain_paths": ["request.domain"],
        })
        with self.assertRaisesRegex(ValueError, "Other-domain access"):
            confirm_interpretation(draft, InterpretationReview(
                accepted_paths={"request.domain", "request.time_limit_days", "search.allow_other_domain"},
                acknowledged_issues={0},
            ))
        submitted = confirm_interpretation(draft, InterpretationReview(
            accepted_paths={"request.domain", "request.time_limit_days"},
            overrides={"request.domain": "Urban ecology", "search.allow_other_domain": True},
            acknowledged_issues={0},
        ))
        self.assertEqual(prepare_run(submitted, self.adapters).search.domain, "Urban ecology")

    def test_malformed_model_json_is_rejected(self):
        client = FakeLLM({"request": {"time_limit_days": "soon"}})
        with self.assertRaises(ValidationError):
            asyncio.run(LLMRequestInterpreter(client).draft("Capstone soon", self.adapters))


if __name__ == "__main__":
    unittest.main()
