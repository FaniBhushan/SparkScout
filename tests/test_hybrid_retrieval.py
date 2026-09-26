"""Local hybrid index respects corpus, chunk, and size settings."""

import unittest

from src.models import SourceChunk
from src.retrieval import HybridInMemoryRetriever, RetrievalIndexConfiguration


def settings(**overrides):
    values = {
        "chunk_size_chars": 20,
        "chunk_overlap_chars": 4,
        "max_corpus_chars": 100,
        "max_chunks": 10,
        "max_index_bytes": 10000,
    }
    values.update(overrides)
    return RetrievalIndexConfiguration(**values)


def chunk(text, source_id="source-1"):
    return SourceChunk(
        chunk_id=f"{source_id}-c0",
        source_id=source_id,
        ordinal=0,
        text=text,
        content_hash="original-hash",
    )


class HybridRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_chunks_keep_source_ids_and_deterministic_top_k(self):
        index = HybridInMemoryRetriever(
            [chunk("retrieval evidence supports an evaluation plan")], settings()
        )

        self.assertGreater(len(index.chunks), 1)
        self.assertEqual({item.source_id for item in index.chunks}, {"source-1"})
        self.assertEqual(len({item.chunk_id for item in index.chunks}), len(index.chunks))
        first = await index.search("retrieval evidence", 2)
        second = await index.search("retrieval evidence", 2)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 2)

    def test_corpus_chunk_and_index_size_limits_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "max_corpus_chars"):
            HybridInMemoryRetriever([chunk("long enough")], settings(max_corpus_chars=3))
        with self.assertRaisesRegex(ValueError, "max_chunks"):
            HybridInMemoryRetriever([chunk("a " * 20)],
                                    settings(chunk_size_chars=10, chunk_overlap_chars=0,
                                             max_chunks=1))
        with self.assertRaisesRegex(ValueError, "max_index_bytes"):
            HybridInMemoryRetriever([chunk("retrieval evidence")],
                                    settings(max_index_bytes=1))

    def test_overlap_must_be_smaller_than_window(self):
        with self.assertRaisesRegex(ValueError, "chunk_overlap_chars"):
            settings(chunk_size_chars=10, chunk_overlap_chars=10)


if __name__ == "__main__":
    unittest.main()
