"""Deterministic merging for independently generated candidate batches."""

import re
from difflib import SequenceMatcher

from src.models import CandidateIdea


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def merge_candidates(
    existing: list[CandidateIdea], additions: list[CandidateIdea], sources: list[dict],
) -> list[CandidateIdea]:
    """Merge distinct ideas, retaining unsupported exploration as synthetic.

    Unknown source references are discarded. Similarity is lexical and intentionally
    conservative; these checks cannot prove that a cited source supports a claim.
    """

    allowed_sources = {source["source_id"] for source in sources}
    kept = list(existing)
    for candidate in additions:
        if any(ref.source_id not in allowed_sources for ref in candidate.evidence):
            continue
        if not candidate.evidence:
            candidate = candidate.model_copy(update={"origin": "synthetic"})
        duplicate = any(
            _normalized(candidate.title) == _normalized(old.title)
            or (SequenceMatcher(None, _normalized(candidate.problem_statement),
                                _normalized(old.problem_statement)).ratio() >= 0.9
                and SequenceMatcher(None, _normalized(candidate.proposed_outcome),
                                    _normalized(old.proposed_outcome)).ratio() >= 0.9)
            for old in kept
        )
        if duplicate:
            continue
        kept.append(candidate.model_copy(update={"candidate_id": f"candidate-{len(kept) + 1:02d}"}))
    return kept
