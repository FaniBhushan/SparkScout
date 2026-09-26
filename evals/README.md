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
