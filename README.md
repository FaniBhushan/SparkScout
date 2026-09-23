# ScoutSpark

ScoutSpark helps students find and assess capstone project ideas for a chosen
domain, deadline, and set of resources. Scout discovers candidate ideas while
Library independently gathers evidence. Critic evaluates each candidate against
a configurable rubric, and a deterministic coordinator selects finalists that
pass the hard gates.

## Current status

The data contracts, source adapters, worker logic, prompts, scoring, and
sequential/parallel coordinator are in place. This is a development foundation,
not yet an end-to-end application: the prompts are not connected to an LLM,
the Streamlit UI is not built, and selected candidates are not yet expanded into
complete `FinalProposal` records. See [TASKS.md](TASKS.md) for the MVP checklist.

## Repository layout

- `src/models/` — validated request, source, candidate, evaluation, and proposal contracts.
- `src/workers/`, `src/orchestration/`, `src/prompts/` — research workers, coordinator,
  and versioned model prompts.
- `src/adapters/`, `src/retrieval/` — frozen-fixture, Tavily, and GitHub source
  adapters plus a basic in-memory retriever.
- `config/` — source registry, search presets, and candidate scoring weights.
- `evals/` — development and held-out cases, synthetic frozen sources, and a
  human-review rubric.
- `docs/` — configuration, scoring, tracing, and orchestration notes.

## Development checks

Use Python 3.10 or newer with Pydantic 2 installed. From the repository root:

```sh
python -m unittest discover -s tests -v
python evals/validate.py
```

The first command runs the current focused worker tests. The second checks the
evaluation dataset and fixture references. Neither command runs live research.
There is no package manifest or app start command yet.

## Configuration and sources

Edit [`config/sources.json`](config/sources.json) for approved providers and source
types, [`config/search_defaults.json`](config/search_defaults.json) for search
limits, and [`config/rubric.json`](config/rubric.json) for scoring criteria and
presets. Criterion weights must total 100; hard gates still apply when a weight
is zero.

Frozen fixtures are synthetic and require no credentials. Tavily web search
requires `TAVILY_API_KEY`; GitHub public repository search can use an optional
`GITHUB_TOKEN`. Do not commit credentials or present fixture records as real-world
evidence. Provider routes, full budget enforcement, and live run assembly remain
on the MVP checklist.

The full product requirements are in
[cross-domain-multi-agent-capstone-orchestrator.md](cross-domain-multi-agent-capstone-orchestrator.md).
