# Evaluation Dataset

This directory contains repeatable inputs for measuring ScoutSpark. Evaluation
cases describe what to run and what must be true; frozen fixtures provide the
same evidence to every system variant.

## Layout

- `manifest.json` versions the dataset and lists every case.
- `cases/development/` contains visible cases used while building the system.
- `cases/held_out/` contains cases reserved for final regression checks.
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
python -m src.cli --case evals/cases/development/ai_engineering_capstone_01.json --offline-demo
```

This deterministic demo reports `insufficient_coverage` because the case asks
for more candidates than the demo model creates. It does not test prompt
interpretation or real-world proposal quality. With `--model`, the same case
uses an LLM and may incur API charges. A batch evaluation runner is still
needed to compare each output with the case's `expected` rules, measure quality,
latency, and cost, and save reports. Prompt-to-request extraction needs its own
comparison with `expected_request`. Human reviewers can score proposals with
`rubrics/proposal_quality.json` and `human_scores/template.csv`.

Exact proposal text is intentionally not part of the gold data. Many proposals
can be correct; the planned deterministic checks will test constraints, while
the rubric measures quality. Do not tune prompts against `cases/held_out/`.

The offline adapter is `src.adapters.FrozenFixtureAdapter`. Create it with a case's
`fixture_set` value, then register it under the `frozen_fixture` provider ID. It
filters records by requested source type and applies the result limit; it does not
simulate keyword relevance or make network calls. Fixture results remain synthetic
and are useful for repeatable pipeline checks, not real-world evidence claims.

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
python -m evals.claim_support --model YOUR_MODEL_ID
```

This requires `OPENAI_API_KEY` and makes nine model calls (up to 1,000 output
tokens each, with normal client retries), which may incur charges. It performs
no source searches and adds no calls to normal research runs. Gold labels are
not sent to the model. The test uses a focused claim-support rubric and reads
the Critic's evidence stance; it does not measure the entire proposal pipeline.
Review the labels and record actual model results before deciding whether an
extra runtime verifier is necessary. No live-model quality result is claimed
by the offline tests.

This focused classification approach follows the
[official evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
including task-specific cases and human review of labels.
