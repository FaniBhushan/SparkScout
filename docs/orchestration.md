# Orchestration and worker prompts

`Orchestrator` in `src/orchestration/coordinator.py` owns the run flow. It
validates request/search domain agreement, runs Scout and Library sequentially
or concurrently, validates their join, then calls Critic. Finalists are
gate-passing candidates ordered by weighted score descending and candidate ID
ascending for ties. If too few pass,
the result is marked `insufficient_coverage`; gates are never relaxed.

At the join, the coordinator checks candidate ID uniqueness and count, candidate
citations against Scout sources, Library chunk/source integrity, and source-record
conflicts. It flags near-copies only when target users and both problem/outcome
wording are highly similar; this lexical guard cannot catch paraphrased semantic
duplicates. The Library must meet `minimum_source_count` and any source types
required by the request or domain route before Critic runs. `ResolvedSearchConfiguration` defaults
that minimum to one for direct construction; the search presets define three. The
preset is resolved in `src/application.py`. Runs below the active threshold
return `insufficient_coverage` without spending tokens on Critic.

After a valid join, the coordinator builds a fresh `HybridInMemoryRetriever` for
that run. It combines deterministic local TF-IDF cosine and lexical overlap;
this is vector-based but not semantic sentence embedding. `config/retrieval.json`
sets the chunk window, overlap, corpus, chunk-count, and estimated index-size
ceilings. `OrchestrationResult.retrieval_index` records settings, size, local
vectorizer/version, and the `run_only` retention policy. The index is never
persisted. Source receipts and chunks remain in the result for audit; exported
chunks from user uploads have their text redacted, so they cannot rebuild the
index. No index is built when coverage fails.

The application drafts a `FinalProposal` for each selected finalist. Code fixes
identity, rank, and scores from the coordinator; the proposal model supplies
narrative fields and must cite only source receipts and chunks already cited in
discovery or evaluation. Citation IDs are checked before output. A finalist
with no cited Library chunk yields `insufficient_coverage` rather than an
unsupported proposal.

The five research and proposal prompt templates live beside their loader in
`src/prompts/`:

- `scout_query_planner.md` plans bounded discovery searches.
- `scout_candidate_generator.md` proposes distinct ideas from the request and
  Scout source records.
- `library_query_planner.md` creates a broad, independent research plan.
- `critic_candidate_judge.md` returns criterion and hard-gate judgments using
  retrieved evidence only.
- `final_proposal.md` drafts complete finalist narrative and citations.

`request_interpreter.md` separately drafts request and configuration fields
from user text; it is reviewed before research starts.

`render_prompt(name, ...)` inserts JSON input and the output JSON Schema generated
from the corresponding Pydantic contract. `parse_model_output(name, response)`
validates raw JSON or Python output against the same contract. Worker interfaces
remain injected; `src/application.py` wires them to an injected LLM client, while
`src/cli.py` uses the existing OpenAI client for frozen-fixture runs. Durable
checkpoints/resume remain future work. `src/application.py` applies the reviewed
time/token budgets and shared provider-call limits around both branches and final
proposal writing. Cost limits require configured rates and are off by default.
