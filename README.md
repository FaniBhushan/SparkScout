# ScoutSpark

ScoutSpark helps students find and assess capstone project ideas for a chosen
domain, deadline, and set of resources. Scout discovers candidate ideas while
Library independently gathers evidence. Critic evaluates each candidate against
a configurable rubric, and a deterministic coordinator selects finalists that
pass the hard gates.

## Current status

The first end-to-end path is implemented: Scout, Library, Critic, and final
proposal writing run from a reviewed configuration, with citation checks and
run-scoped budgets. The CLI and Streamlit UI support synthetic offline runs;
both can also select ready live sources. The UI has Simple and Advanced
configuration, prompt drafting, a preview-before-run step, and optional local
documents. This is an MVP, not a validated production service: broader quality
evaluation, failure handling, and resume remain open. See [TASKS.md](TASKS.md).

## Repository layout

- `src/models/` — validated request, source, candidate, evaluation, and proposal contracts.
- `src/workers/`, `src/orchestration/`, `src/prompts/` — research workers, coordinator,
  and versioned model prompts.
- `src/application.py`, `src/preflight.py`, `src/cli.py` — reviewed run assembly,
  validation, and command-line entry point.
- `src/ui/`, `streamlit_app.py` — Streamlit modules and thin launch file.
- `src/adapters/`, `src/retrieval/` — frozen-fixture, Tavily, GitHub, and optional
  upload adapters plus a run-scoped local hybrid index.
- `config/` — source registry, search and retrieval limits, and scoring weights.
- `evals/` — development and held-out cases, synthetic frozen sources, and a
  human-review rubric; no batch evaluation runner yet.
- `docs/` — configuration, scoring, tracing, and orchestration notes.

## Development checks

Use Python 3.10 or newer with Pydantic 2 installed. From the repository root:

```sh
python -m unittest discover -s tests -v
python evals/validate.py
```

The first command runs focused tests, and the second checks evaluation fixtures.
Neither command makes model or provider API calls.

For a no-key, no-network CLI smoke check, use:

```sh
python -m src.cli --case evals/cases/development/ai_engineering_capstone_01.json --offline-demo
```

The case asks for more candidates than the deterministic demo model creates,
so this command currently reports `insufficient_coverage`. To see a complete
synthetic run with a final proposal, use the Offline demo in Streamlit. Neither
path measures live research quality.

## Local interface

```sh
python -m streamlit run streamlit_app.py
```

Choose **Offline demo** to preview and run against synthetic frozen records
without an API key or network research. For live GitHub/Tavily research, choose
**Live sources**, set `OPENAI_API_KEY`, and enter a model ID. Tavily also needs
`TAVILY_API_KEY`. Prompt interpretation is a separate model call: review its
suggestions and issues, preview the resolved configuration, then click **Start
research**. Editing controls invalidates the preview. The UI can download the
reviewed configuration as JSON for `--config` in the CLI. Reusing a config with
uploads also requires the same files via `--upload` and
`--confirm-upload-rights`; the JSON contains receipts, not file bytes.
`streamlit_app.py` is the launch file; UI code lives in `src/ui/`.

Documents are optional. In Live mode, a user may add up to five `.txt`, `.md`,
or text-based `.pdf` files after agreeing to the displayed upload terms. No
license document is requested. The user declares the document language; the app
does not verify it. Extracted text may be sent to the selected model. Downloaded
run JSON retains source IDs, hashes, and citations but redacts stored upload
snippets and chunk text; generated summaries may still reflect uploaded content.
Keep run results private when their source material is private.

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
ranking, complete final proposals where supported, and explicit coverage status.
The shared `run_research()` function in `src/application.py` remains available.
The [official OpenAI quickstart](https://developers.openai.com/api/docs/quickstart)
explains API-key setup.

For all supported settings, use
`python -m src.cli --config scoutspark-config.json --fixture-set ai_engineering_capstone_01 --model YOUR_MODEL_ID`.
Use `--live` instead of `--fixture-set` for ready live adapters. To review a
natural-language request at the CLI, first use `--prompt-file request.txt` and
save its JSON draft, then run with `--draft-file draft.json --review-file review.json`.
The saved draft is not reinterpreted during the reviewed run. A requested USD
cap also needs trusted `--input-rate` and `--output-rate` values.
For optional local documents, repeat `--upload PATH` and add
`--confirm-upload-rights`; the CLI never copies those files into the repository.

## Configuration and sources

Edit [`config/sources.json`](config/sources.json) for approved providers and source
types, [`config/search_defaults.json`](config/search_defaults.json) for search
limits, [`config/retrieval.json`](config/retrieval.json) for index limits, and
[`config/rubric.json`](config/rubric.json) for scoring criteria and presets.
Criterion weights must total 100; hard gates still apply when a weight is zero.

Frozen fixtures are synthetic and require no credentials. Tavily web search
requires `TAVILY_API_KEY`; GitHub public repository search can use an optional
`GITHUB_TOKEN`. Do not commit credentials or present fixture records as real-world
evidence. The adapter builder and CLI support opt-in live GitHub/Tavily registration;
run-wide time and reported-token
limits are defined in `config/budgets.json`; a cost cap is optional and requires
trusted per-model input/output rates. The result includes budget usage. The
source-byte cap counts normalized records and extracted upload text returned
across both research branches; raw upload bytes are checked before research;
each live HTTP response also has a separate 2 MB safety cap.
Advanced controls currently cover ready providers, source/content types, dates,
evidence tiers, record caps, run budgets (including normalized source bytes),
fallback behavior, retrieval top-k, and exact rubric weights. Confirmed uploads
also enable user-declared language, user-supplied full text, and an aggregate PDF
page cap. GitHub/Tavily expose metadata and snippets only; remote full-page
fetching is disabled. Never check real third-party full text into `evals/` or
other repository files; frozen fixtures must stay synthetic.

The full product requirements are in
[cross-domain-multi-agent-capstone-orchestrator.md](cross-domain-multi-agent-capstone-orchestrator.md).
