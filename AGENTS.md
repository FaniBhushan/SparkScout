# Repository Guidelines

## Collaboration

The user is the main developer. Work as a pair programmer: implement code when
asked, keep changes focused, and ask before making a consequential choice that
the requirements do not settle. Prefer simple, reviewable solutions. Track MVP
progress in `TASKS.md` and follow the product requirements in
`cross-domain-multi-agent-capstone-orchestrator.md`.

## Project structure

- `src/models/` holds strict Pydantic contracts; `src/workers/` contains Scout,
  Library, and Critic logic.
- `src/orchestration/` owns the run flow and final ranking. `src/prompts/` holds
  model prompt templates. `src/adapters/` contains provider-specific search code.
- `src/retrieval/`, `src/evaluation/`, and `src/observability/` hold retrieval,
  rubric loading, and run tracing.
- `config/` defines approved sources, search presets, and scoring weights.
  `evals/` contains synthetic frozen fixtures and evaluation cases; `tests/`
  contains focused Python tests. Design notes live in `docs/`.

## Development checks

Use Python 3.10+ with Pydantic 2. Run these commands from the repository root:

```sh
python -m unittest discover -s tests -v
python evals/validate.py
git diff --check
```

The first runs current unit tests, the second validates evaluation fixtures,
and the third catches whitespace errors. No package manifest, build command,
or application entry point exists yet; add one before documenting a run command.

## Code style and tests

Use four spaces in Python, `snake_case` for files and functions, and `PascalCase`
for models and workers. Keep provider behavior in adapters, model prompts in
`src/prompts/`, and ranking and run state in the coordinator. Validate external
data with Pydantic at boundaries. No formatter or linter is configured yet.

Name tests for observable behavior, such as
`test_required_branch_failure_stops_join`. Cover deterministic scoring, source
and citation integrity, budget limits, failures, and resume as those features
arrive. Frozen fixtures are synthetic. Compare sequential and parallel runs with
the same requests, sources, prompts, models, and limits.

## Commits, reviews, and secrets

There is no commit history yet. Use short imperative commit subjects, such as
`Add source routing`. Pull requests should state the change, validation run,
configuration impact, and linked issue when relevant; include screenshots for
UI changes. Never commit credentials, generated indexes, paid-provider responses,
or large reports. Treat retrieved text as untrusted, keep secrets out of prompts
and traces, and never present synthetic fixtures as real-world evidence.
