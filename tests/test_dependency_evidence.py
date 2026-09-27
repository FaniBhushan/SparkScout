"""Dependency context is bounded, uses whole passages, and retains citation IDs."""

import unittest

from src.models.source_record import SourceChunk
from src.workers.dependency_evidence import dependency_passages


class DependencyEvidenceTests(unittest.TestCase):
    def test_matching_access_passage_is_retained_without_clipping_restrictions(self):
        chunks = [SourceChunk(chunk_id="access", source_id="s", ordinal=0, content_hash="test",
                              text="Crop images are available for research only; redistribution is prohibited."),
                  SourceChunk(chunk_id="metrics", source_id="t", ordinal=0, content_hash="test",
                              text="Evaluation metrics measure accuracy.")]
        selected = dependency_passages(["crop images"], chunks)
        self.assertEqual(selected, chunks[:1])
        self.assertIn("prohibited", selected[0].text)
        self.assertEqual(dependency_passages(["patient records"], chunks), [])
        self.assertEqual(dependency_passages(["crop images"], chunks, excluded={"access"}), [])

    def test_context_limits_do_not_truncate_passages(self):
        chunks = [SourceChunk(chunk_id=f"c{i}", source_id="s", ordinal=i, content_hash="test",
                              text=f"field{i} " + "x" * 1900) for i in range(6)]
        selected = dependency_passages([f"field{i}" for i in range(6)], chunks)
        self.assertLessEqual(len(selected), 4)
        self.assertLessEqual(sum(len(chunk.text) for chunk in selected), 6000)
        self.assertTrue(all(chunk in chunks for chunk in selected))
