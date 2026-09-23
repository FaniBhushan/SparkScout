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
remain injected, so a model client can use these helpers without coupling
orchestration to a provider. Prompt templates are not yet connected to a concrete
model client. Durable
checkpoints/resume and run-wide cost/time enforcement are also future coordinator
work.
