"""Select bounded Critic context across needs, dependencies, and permissions."""

from src.models import CandidateIdea, EvaluationConfiguration, LibraryResult, RetrievedChunk
from src.retrieval import Retriever


async def retrieve_candidate_evidence(
    retriever: Retriever, candidate: CandidateIdea, library: LibraryResult,
    rubric: EvaluationConfiguration,
) -> list[RetrievedChunk]:
    """Fuse independent searches so repeated problem words cannot hide access facts.

    Scores from different queries are not directly comparable. Reciprocal rank
    fusion rewards passages useful across searches; source diversity prevents
    near-duplicate summaries from consuming the entire context window.
    """
    queries = [f"{candidate.title} {candidate.problem_statement}"]
    queries.extend(definition.retrieval_focus for definition in rubric.criteria.values())
    queries.extend(candidate.required_data)
    queries.extend(candidate.required_tools)
    queries.extend([
        "public data availability permission license permitted research access",
        "required resources hardware duration dependencies limitations",
    ])
    allowed = {chunk.chunk_id: chunk for chunk in library.chunks}
    hits: dict[str, RetrievedChunk] = {}
    ranks: dict[str, float] = {}
    for query in dict.fromkeys(queries):
        results = await retriever.search(query, rubric.retrieval_top_k)
        # Ignore excess hits, retaining the configured limit without another search.
        for rank, hit in enumerate(results[:rubric.retrieval_top_k], 1):
            chunk_id = hit.chunk.chunk_id
            if allowed.get(chunk_id) != hit.chunk:
                raise ValueError("retriever returned a chunk outside the Library result")
            hits[chunk_id] = hit
            ranks[chunk_id] = ranks.get(chunk_id, 0) + 1 / (60 + rank)

    ranked = sorted(hits.values(), key=lambda hit: (-ranks[hit.chunk.chunk_id], hit.chunk.chunk_id))
    first_per_source, remaining = [], []
    seen_sources = set()
    for hit in ranked:
        if hit.chunk.source_id in seen_sources:
            remaining.append(hit)
        else:
            first_per_source.append(hit)
            seen_sources.add(hit.chunk.source_id)
    selected = []
    tokens = 0
    for hit in [*first_per_source, *remaining]:
        count = max(hit.chunk.token_count or 0, max(1, len(hit.chunk.text) // 4))
        if len(selected) >= rubric.max_context_chunks:
            break
        if tokens + count <= rubric.max_context_tokens:
            selected.append(hit)
            tokens += count
    return selected
