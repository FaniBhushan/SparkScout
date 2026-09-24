# Orchestration and worker prompts

`src/orchestration/Orchestrator` owns the run flow. It validates request/search
domain agreement, runs Scout and Library sequentially or concurrently, validates
their join, then calls Critic. Finalists are gate-passing candidates ordered by
weighted score descending and candidate ID ascending for ties. If too few pass,
the result is marked `insufficient_coverage`; gates are never relaxed.

At the join, the coordinator checks candidate ID uniqueness and count, candidate
citations against Scout sources, Library chunk/source integrity, and source-record
conflicts. It flags near-copies only when target users and both problem/outcome
wording are highly similar; this lexical guard cannot catch paraphrased semantic
duplicates. The Library must meet `minimum_source_count` and any source types
required by the request before Critic runs. `ResolvedSearchConfiguration` defaults
that minimum to one for direct construction; the search presets define three. The
preset-to-resolved-config wiring is still pending. Runs below the active threshold
return `insufficient_coverage` without spending tokens on Critic.

After a valid join, the coordinator snapshots Library chunks into a fresh
`InMemoryRetriever` for that run and gives it to a run-specific Critic worker.
No index is built when coverage fails. The index is lexical (case-folded word
overlap, score by unique query-term overlap, then chunk ID for stable ties),
with `retrieval_top_k` and context limits taken from the active rubric.
`OrchestrationResult.retrieval_index` records the backend/version, indexed
chunk count, retrieval/context limits, and `run_only` retention policy. The
index is held only in process during evaluation and is not persisted; the
returned Library chunks and source manifest remain available for audit and
rebuilding. Trace events mark index creation and the end of its use. A vector
or hybrid backend, configured corpus/index-size limits, and explicit durable
retention remain to be implemented for FR-06.

The four prompt templates live beside their loader in `src/prompts/`:

- `scout_query_planner.md` plans bounded discovery searches.
- `scout_candidate_generator.md` proposes distinct ideas from the request and
  Scout source records.
- `library_query_planner.md` creates a broad, independent research plan.
- `critic_candidate_judge.md` returns criterion and hard-gate judgments using
  retrieved evidence only.

`render_prompt(name, ...)` inserts JSON input and the output JSON Schema generated
from the corresponding Pydantic contract. `parse_model_output(name, response)`
validates raw JSON or Python output against the same contract. Worker interfaces
remain injected; `src/application.py` wires them to an injected LLM client, while
`src/cli.py` uses the existing OpenAI client for frozen-fixture runs. Durable
checkpoints/resume and run-wide cost/time enforcement are future coordinator work.
