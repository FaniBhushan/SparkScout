# ScoutSpark

ScoutSpark helps students find and assess capstone project ideas for a chosen
domain, deadline, and set of resources. Scout discovers candidate ideas while
Library independently gathers evidence. Critic evaluates each candidate against
a configurable rubric, and a deterministic coordinator selects finalists that
pass the hard gates.

## Current status

The data contracts, source adapters, worker logic, LLM-backed prompts, scoring,
and sequential/parallel coordinator are in place. `src/application.py` now wires
one structured request into a run, and `src/cli.py` runs it against synthetic
frozen sources. This is not yet the complete application: the Streamlit UI and
fully cited `FinalProposal` records remain open. See [TASKS.md](TASKS.md).

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

The first command runs focused tests, and the second checks evaluation fixtures.
Neither command makes model or provider API calls.

## Frozen-fixture run

Install `requirements.txt`, set `OPENAI_API_KEY`, and choose a model available to
your account. From the repository root:

```sh
python -m src.cli --case evals/cases/development/ai_engineering_capstone_01.json --model YOUR_MODEL_ID
```

This uses only synthetic source records, but it **does make OpenAI model calls**
and may incur API charges. It defaults to sequential mode; add `--mode parallel`
to compare orchestration. For your own structured `InputRequest` JSON, use
`--request request.json --fixture-set ai_engineering_capstone_01` instead of
`--case`. Output is a JSON `OrchestrationResult` with candidates, evaluations,
ranking, and coverage status—not complete final proposals. The shared
`run_research()` function in `src/application.py` is also available for a future
UI. The [official OpenAI quickstart](https://developers.openai.com/api/docs/quickstart)
explains API-key setup.

## Configuration and sources

Edit [`config/sources.json`](config/sources.json) for approved providers and source
types, [`config/search_defaults.json`](config/search_defaults.json) for search
limits, and [`config/rubric.json`](config/rubric.json) for scoring criteria and
presets. Criterion weights must total 100; hard gates still apply when a weight
is zero.

Frozen fixtures are synthetic and require no credentials. Tavily web search
requires `TAVILY_API_KEY`; GitHub public repository search can use an optional
`GITHUB_TOKEN`. Do not commit credentials or present fixture records as real-world
evidence. Provider routes, per-type caps, full budget enforcement, and live run
assembly remain on the MVP checklist.

The full product requirements are in
[cross-domain-multi-agent-capstone-orchestrator.md](cross-domain-multi-agent-capstone-orchestrator.md).
