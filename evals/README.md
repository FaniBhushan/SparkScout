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

## How a case is used

1. Load a case JSON file.
2. Pass `prompt` to the request extractor.
3. Compare the normalized request with `expected_request`.
4. If `fixture_set` is present, load its `sources.json` and `chunks.json` through
   the fixture adapter.
5. Run the sequential or parallel pipeline.
6. Check `expected` rules, including outcome, citations, source types, and
   forbidden results.
7. Save machine metrics to `reports/`. Human reviewers separately score the
   output using the rubric and CSV template.

Exact proposal text is intentionally not part of the gold data. Many proposals
can be correct; deterministic rules check correctness, while the rubric measures
quality. Do not tune prompts against `cases/held_out/`.

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
