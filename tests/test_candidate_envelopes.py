"""Safe response-shape repair must not invent or silently discard candidate fields."""

import json
import unittest

from pydantic import ValidationError

from src.prompts import parse_model_output, repair_known_candidate_field


class CandidateEnvelopeTests(unittest.TestCase):
    def test_singleton_and_exact_wrapper_preserve_candidate_content(self):
        candidate = {"candidate_id": "c1", "title": "Inspect image files",
                     "problem_statement": "File problems are difficult to inspect.",
                     "target_users": ["Students"], "proposed_outcome": "An inspection report",
                     "why_it_matters": "May reduce manual checking."}
        for value in (candidate, {"candidates": [candidate]}):
            repaired = repair_known_candidate_field(json.dumps(value))
            self.assertEqual(json.loads(repaired), [candidate])
            self.assertEqual(len(parse_model_output("scout_candidate_generator", repaired)), 1)
        malformed = {**candidate, "invented_field": "must not be dropped"}
        with self.assertRaises(ValidationError):
            parse_model_output("scout_candidate_generator", repair_known_candidate_field(json.dumps(malformed)))
        self.assertIsNone(repair_known_candidate_field('{"candidates": [], "other": "ambiguous"}'))
