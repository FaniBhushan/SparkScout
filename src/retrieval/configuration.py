"""Validated limits and retention for the local retrieval index."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import NonNegativeInt, PositiveInt, model_validator

from src.models.common import ContractModel


DEFAULT_INDEX_CONFIG = Path(__file__).resolve().parents[2] / "config" / "retrieval.json"


class RetrievalIndexConfiguration(ContractModel):
    """Operator ceilings for an ephemeral, reproducible local index."""

    schema_version: Literal["1.0"] = "1.0"
    backend: Literal["hybrid_tfidf_in_memory"] = "hybrid_tfidf_in_memory"
    backend_version: Literal["1"] = "1"
    embedding_model: Literal["local_tfidf"] = "local_tfidf"
    embedding_version: Literal["1"] = "1"
    chunk_size_chars: PositiveInt
    chunk_overlap_chars: NonNegativeInt
    max_corpus_chars: PositiveInt
    max_chunks: PositiveInt
    max_index_bytes: PositiveInt
    retention: Literal["run_only"] = "run_only"

    @model_validator(mode="after")
    def validate_chunk_window(self) -> "RetrievalIndexConfiguration":
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")
        return self


def load_retrieval_index_configuration(
    path: Path = DEFAULT_INDEX_CONFIG,
) -> RetrievalIndexConfiguration:
    """Load the operator-owned retrieval settings before indexing evidence."""

    return RetrievalIndexConfiguration.model_validate_json(path.read_text(encoding="utf-8"))
