# Evaluation Dataset

This directory contains repeatable inputs for measuring ScoutSpark. Evaluation
cases describe what to run and what must be true; frozen fixtures provide the
same evidence to every system variant.

## Layout

- `manifest.json` versions the dataset and lists every case.
- `cases/development/` contains visible cases used while building the system.
- `cases/held_out/` contains cases reserved for final regression checks.
- `guardrails/claim_support.json` is the synthetic Critic development set;
  `guardrails/claim_support_held_out.json` checks the same distinction on
  separate examples.
- `frozen_sources/<fixture_set>/` contains normalized sources and chunks for a
  case. These records are synthetic and must not be reported as real evidence.
- `rubrics/proposal_quality.json` defines the fixed human-review scale.
- `human_scores/template.csv` is copied and completed by reviewers.
- `reports/` is for generated results and is ignored by Git.

## Current use and next evaluation step

`validate.py` checks dataset structure, paths, references, and synthetic labels;
it does not run research or score proposals. The CLI can run one case with its
frozen fixture and `expected_request`:

```sh
python -m src.ui.cli --case evals/cases/development/ai_engineering_capstone_01.json --offline-demo
```

This deterministic demo can report `partial` because the case asks
for more candidates than the demo model creates. It does not test prompt
interpretation or real-world proposal quality. With `--model`, the same case
uses an LLM and may incur API charges. The batch runner below compares outputs
with structural expectations and exports proposals for human quality review.
Prompt-to-request extraction needs its own
comparison with `expected_request`. Human reviewers can score proposals with
`rubrics/proposal_quality.json` and `human_scores/template.csv`.

Exact proposal text is intentionally not part of the gold data. Many proposals
can be correct; deterministic checks test structural requirements, while
the rubric measures quality. Do not tune prompts against `cases/held_out/`.

The offline adapter is `src.adapters.FrozenFixtureAdapter`. Create it with a case's
`fixture_set` value, then register it under the `frozen_fixture` provider ID. It
filters records by requested source type and applies the result limit; it does not
simulate keyword relevance or make network calls. Fixture results remain synthetic
and are useful for repeatable pipeline checks, not real-world evidence claims.

The adapter loads prepared passages from `chunks.json`, validates their source
links and unique IDs, and carries them to Library as in-memory `evidence_chunks`.
These passages are omitted from Scout's serialized source prompt. Library keeps
their IDs and also retains each distinct source summary; the normal index and
Critic retrieval limits select the passages sent to the model. Metadata-only
queries do not release passage text. A source-only fixture can still use its
summary when no `chunks.json` file is present.

## End-to-end runner

```sh
python -m evals.end_to_end --offline-demo
```

The default suite runs robotics, accessibility, and medicine through the actual
application, starting with each case's `expected_request`. It does not evaluate
prompt interpretation. Source records and prepared passages are frozen; Library
combines the captured chunks with source summaries before normal indexing.
Case fingerprints and checkpoint identities cover both JSON files, so changing
passage text invalidates reuse of an older run.
Requested proposal counts are targets. The current demo returns one candidate,
so it can pass structural checks with a `partial` result. Reports show requested
and returned counts separately, including whether the target was reached. Zero
usable proposals still fail success cases. This checks the reporting path; it
does not establish real-model quality. Internal synthetic exploration is excluded
from exported candidates and never used to pad the proposal count.

Modules under `end_to_end/` have separate responsibilities:

- `cases.py`: select development cases and hash case/source/passage inputs.
- `runner.py`: execute the application and capture errors and durations.
- `checks.py`: check outcome, count, source types, citation references, scores, and ranking.
- `reports.py`: write JSON, a readable summary, and an unscored human-review CSV.
- `__main__.py`: command arguments, model setup, suite budget, and report metadata.

Use repeated `--case CASE_ID` options to select cases, `--mode parallel` to run
Scout and Library concurrently, and `--output NEW_DIRECTORY` to choose a report
directory. The default is an ignored directory under `evals/reports/`.
Exit code 1 means at least one case failed, errored, or was skipped. Errors stop
the remaining suite. Checks without relevant outputs are marked not evaluated.

Paid execution is explicit, with one budget shared across every case:

```sh
python -m evals.end_to_end --model gpt-4o-mini --max-cost-usd 1 --input-rate 0.15 --output-rate 0.60
```

This incurs new charges. SDK retries are disabled. Suite limits are 300,000 model
tokens and 900 seconds, alongside the application's per-run limits. Token-price
estimates depend on the supplied rates; each new invocation starts a new budget.
Reports include prompt hashes, input hashes, resolved run configurations, actual
outputs, usage, and failures. Demo token counts are synthetic. Different live
model runs can produce different answers, even with frozen sources.

`human_scores.csv` has a row per generated proposal and blank quality scores;
`human_rubric.json` copies the review rubric. Read `human_review` constraints in
`results.json` as well. Feasibility, relevance, excluded topics, and whether a
citation truly supports a claim require human assessment. This runner does not
automatically score those properties or establish sequential/parallel equivalence.

Validate paths, JSON, fixture references, and synthetic labels with:

```sh
python3 evals/validate.py
```

## Starter coverage

The cases cover normal requests, AI Engineering, public-data restrictions,
medical safety, privacy, limited hardware, short deadlines, excluded topics,
missing required input, and insufficient source coverage.

## Claim-support component evaluation

`guardrails/claim_support.json` adds nine synthetic, reviewable claim/evidence
pairs. Three labels distinguish **supported**, **unsupported** (not established),
and **contradictory** (explicitly refuted). Two cases contain injected instructions.
These are starter development cases, not an independent held-out benchmark.

```sh
python -m evals.claim_support --validate-only
python -m evals.claim_support --predictions predictions.json
```

Saved predictions are a JSON list of `{"id": "support_count", "label": "supported"}`
records, one per case. Missing, duplicate, or unknown IDs are rejected. The report
includes accuracy, a confusion matrix, and the false-support rate: the fraction
of unsupported/contradictory cases incorrectly called supported. Invalid model
outputs count as wrong rather than being dropped.

To measure the existing Critic against the cases, explicitly choose a model:

```sh
python -m evals.claim_support --model gpt-4o-mini --max-cost-usd 1 --input-rate 0.15 --output-rate 0.60
```

This loads the root `.env` without overriding existing environment variables.
It requires `OPENAI_API_KEY` and makes at most nine model calls (up to 1,000 output
tokens each, with SDK retries disabled), which may incur charges. It performs
no source searches and adds no calls to normal research runs. Gold labels are
not sent to the model. The test uses a focused claim-support rubric and reads
the Critic's evidence stance; it does not measure the entire proposal pipeline.
Review the labels and record actual model results before deciding whether an
extra runtime verifier is necessary. No live-model quality result is claimed
by the offline tests.

Paid runs require a positive spending cap and both USD-per-million token rates.
The example rates come from the [official model page](https://developers.openai.com/api/docs/models/gpt-4o-mini),
checked September 26, 2026; verify rates before using another model.
The budget reserves conservative input plus maximum output before each call,
enforces 100,000 model tokens and a 300-second deadline, and reports usage.
The cap is per invocation, based on supplied rates—not an account-wide billing
limit. Failures stop the run without automatic reruns. Repeating the command
starts a new allowance; unknown usage from a failed call must not be assumed free.

This focused classification approach follows the
[official evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
including task-specific cases and human review of labels.
