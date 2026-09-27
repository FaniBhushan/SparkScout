# ScoutSpark

Local credentials can be set in the repository-root `.env` using
`OPENAI_API_KEY`, `TAVILY_API_KEY`, and optional `GITHUB_TOKEN`. CLI, Streamlit
launcher, and paid claim-support evaluations load it automatically; existing
environment variables take precedence. Never commit this ignored file.
Set `PYTHON_DOTENV_DISABLED=1` in CI/offline tests to skip local loading.

ScoutSpark helps students find and assess capstone project ideas for a chosen
domain, deadline, and set of resources. Scout discovers candidate ideas while
Library independently gathers evidence. Critic evaluates each candidate against
a configurable rubric. The UI displays the highest weighted-score ideas as
finalists, including failed-gate reasons. Defaults are five ideas and two
displayed finalists; counts and criterion weights are configurable.

## Current status

The first end-to-end path is implemented: Scout, Library, Critic, and final
proposal writing run from a reviewed configuration, with citation checks and
run-scoped budgets. The CLI and Streamlit UI support synthetic offline runs;
both can also select ready live sources. The UI has Simple and Advanced
configuration, prompt drafting, a preview-before-run step, and optional local
documents. This is an MVP, not a validated production service: broader quality
evaluation remains open. Failure handling and opt-in CLI checkpoints/resume are
implemented; see [checkpoint behavior](docs/checkpoints.md), the
[issue and design decision log](docs/decision_log.md), and [TASKS.md](TASKS.md).

## How ScoutSpark works

ScoutSpark uses role-specialized LLM workers coordinated by the orchestrator:

1. **Scout** plans discovery queries and proposes candidate ideas.
2. **Library** independently researches sources and prepares evidence chunks.
3. The orchestrator joins results and builds a **run-scoped in-memory TF-IDF /
   keyword index**. Critic retrieves relevant passages for each candidate, gets
   rubric assessments from the LLM, then applies configured weights and hard
   gates in code.
4. The proposal writer drafts from cited evidence; the verifier checks claim
   support. Finalization ranks candidates and can try the next one or run one
   bounded recovery round if no draft survives.

This is a retrieval-augmented workflow, not a semantic-vector database or an
open-ended agent loop. Tavily and GitHub adapters return source records and
snippets; optional user documents can add evidence. Frozen fixtures are
synthetic and intended for offline tests. See the [design document](docs/design_doc_submission.md)
for the component diagram and evaluation limits.

Detailed proposals require passed gates and a separate evidence audit, with at most one correction. The
temporary demo policy may retain explicitly marked narrative hypotheses after
that correction; it does not waive factual citations, essential data/access, or
budget checks. See [verification and demo policy](docs/orchestration.md).

When a draft fails, the system tries the next gate-passing candidate. If no
proposal survives, it makes one bounded recovery attempt using retained evidence,
remaining search allowance, and up to three distinct replacement ideas. Recovery
uses the same budget and preserves earlier rejection reasons; a valid proposal
is not guaranteed when evidence or allowance is insufficient.

Scorecards remain available when a detailed draft is withheld. Other ideas show
their rank, criterion scores, weights, and reason for falling below the display
cutoff. Submission measurements and their limits are collected in
[the demo evaluation report](evals/demo_submission_2026-09-27.md).

## Repository layout

- `src/models/` — validated request, source, candidate, evaluation, and proposal contracts.
- `src/workers/`, `src/orchestration/`, `src/prompts/` — research workers, coordinator,
  and versioned model prompts.
- `src/application/` — run assembly, preflight validation, interpretation,
  finalization, and recovery.
- `src/runtime/`, `src/configuration/`, `src/sources/` — budgets and provider
  failure handling, configuration loading, and shared source normalization.
- `src/testing/` — offline demo helpers used by tests and evaluation runs.
- `src/ui/` — CLI (`cli.py`) and Streamlit modules; `streamlit_app.py` is the
  thin Streamlit launch file.
- `src/guardrails/` — input/privacy checks, evidence filtering, and bounded draft correction.
- `src/adapters/`, `src/retrieval/` — frozen-fixture, Tavily, GitHub, and optional
  upload adapters plus a run-scoped local hybrid index.
- `config/` — source registry, search and retrieval limits, and scoring weights.
- `evals/` — cases and frozen sources, `end_to_end/` and `live/` runners,
  `analysis/` reports, `guardrails/` checks, and `validation/` tools.
- `docs/` — configuration, scoring, tracing, and orchestration notes.

## Development checks

Use Python 3.10 or newer with Pydantic 2 installed. From the repository root:

```sh
python -m unittest discover -s tests -v
python -m evals.validation.validate
```

The first command runs focused tests, and the second checks evaluation fixtures.
Neither command makes model or provider API calls.

For a no-key, no-network CLI smoke check, use:

```sh
python -m src.ui.cli --case evals/cases/development/ai_engineering_capstone_01.json --offline-demo
```

The case asks for more candidates than the deterministic demo model creates,
so this command currently reports `insufficient_coverage`. To see a complete
synthetic run with a final proposal, use the Offline demo in Streamlit. Neither
path measures live research quality.

## Local interface

```sh
python -m streamlit run streamlit_app.py
```

### Using the app

1. Start the app with the command above.
2. Choose **Offline demo** to explore the UI using synthetic records, without
   credentials or live network searches. Choose **Live sources** for Tavily and
   GitHub research; provide `OPENAI_API_KEY`, a model ID, and (for Tavily) a
   `TAVILY_API_KEY`.
3. Describe the project you want to explore, or enter the structured request.
   If using prompt interpretation, review its suggestions and issues: this is a
   separate model call and its output is editable.
4. Choose Simple or Advanced settings, adjust source types, limits, or rubric
   weights as needed, then select **Preview configuration**. Preview shows the
   resolved search settings, selected adapters, budgets, and request issues
   before research starts.
5. Start research. Review the ranked scorecards, gate caveats, evidence, and
   any verified detailed proposals. A top-two score finalist is not necessarily
   a gate-passing proposal; read its caveats. Download the run result or
   reviewed configuration if needed.

Editing settings invalidates the preview, so preview again before starting.
The UI can download the reviewed configuration as JSON for `--config` in the
CLI. Reusing a config with uploads also requires the same files via `--upload`
and `--confirm-upload-rights`; the JSON contains receipts, not file bytes.
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
python -m src.ui.cli --case evals/cases/development/ai_engineering_capstone_01.json --model YOUR_MODEL_ID
```

This uses only synthetic source records, but it **does make OpenAI model calls**
and may incur API charges. It defaults to sequential mode; add `--mode parallel`
to compare orchestration. For your own structured `InputRequest` JSON, use
`--request request.json --fixture-set ai_engineering_capstone_01` instead of
`--case`. Output is a JSON `OrchestrationResult` with candidates, evaluations,
ranking, complete final proposals where supported, and explicit coverage status.
`partial` means fewer proposals were available than requested; users still receive
those proposals. Synthetic exploration stays internal and is excluded from results.
The shared `run_research()` function in `src/application/service.py` remains available.
The [official OpenAI quickstart](https://developers.openai.com/api/docs/quickstart)
explains API-key setup.

For all supported settings, use
`python -m src.ui.cli --config scoutspark-config.json --fixture-set ai_engineering_capstone_01 --model YOUR_MODEL_ID`.
Use `--live` instead of `--fixture-set` for ready live adapters. To review a
natural-language request at the CLI, first use `--prompt-file request.txt` and
save its JSON draft, then run with `--draft-file draft.json --review-file review.json`.
The saved draft is not reinterpreted during the reviewed run. A requested USD
cap also needs trusted `--input-rate` and `--output-rate` values.
For optional local documents, repeat `--upload PATH` and add
`--confirm-upload-rights`; the CLI never copies those files into the repository.

## Configuration and sources

Long prompts now produce a cost/delay warning instead of a length-based
rejection. Structured fields remain concise; obvious credentials are blocked
and possible contact details produce a warning. These lightweight checks add
no model calls and do not guarantee privacy or factual correctness. See
[guardrails and their limits](docs/guardrails.md).

Edit [`config/sources.json`](config/sources.json) for approved providers and source
types, [`config/search_defaults.json`](config/search_defaults.json) for search
limits, [`config/retrieval.json`](config/retrieval.json) for index limits, and
[`config/rubric.json`](config/rubric.json) for scoring criteria and presets.
Criterion weights must total 100; hard gates still apply when a weight is zero.

The results UI shows failed candidates with their caveats. If only evidence
sufficiency fails, users can explicitly keep an idea despite that uncertainty;
the decision is included in the downloaded run JSON without changing the failed
assessment or generating a proposal. Known deadline conflicts remain blocking,
while uncertain timing is shown as a caveat. See [candidate scoring and review](docs/candidate_scoring.md).

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
