# MVP Task Tracker

This checklist tracks the MVP in `cross-domain-multi-agent-capstone-orchestrator.md`.
`[x]` means code or fixtures exist; it does **not** mean the full pipeline has been
verified. Update this file when a task is completed, and record evidence in the
relevant PR or evaluation report.

## Foundations in place

- [x] Define Pydantic contracts for requests, sources, candidates, scoring, and proposals.
- [x] Add source catalog, search presets, rubric presets, and configurable weights.
- [x] Add frozen-fixture, Tavily web, and GitHub repository adapters.
- [x] Implement Scout, Library, and Critic worker logic with injectable dependencies.
- [x] Add four worker prompt templates and structured-output parsing helper.
- [x] Add sequential/parallel coordinator, join checks, coverage checks, and ranking.
- [x] Add basic run tracing, frozen evaluation cases, and focused Library/Critic tests.

## Make one complete run work — next

- [ ] Connect an LLM client to Scout query planning, candidate generation, Library
      query planning, and Critic assessment; validate every raw response with the
      matching Pydantic contract and record token/cost usage.
- [ ] Resolve source registry, domain route, preset, user source policy, and hard
      limits into one `ResolvedSearchConfiguration`; select only available adapters.
- [ ] Build a run-scoped retrieval index from Library chunks and give each run its
      own Critic retriever. Record index settings and retention behavior.
- [ ] Produce complete, cited `FinalProposal` records for selected candidates.
- [ ] Add a runnable frozen-fixture entry point that accepts a structured request
      and returns proposals or an explicit coverage failure.

## User configuration and interface

- [ ] Extract `InputRequest` from a prompt; show uncertain or conflicting fields
      for correction before research starts.
- [ ] Build Streamlit Simple mode with visible search and evaluation presets.
- [ ] Build Advanced mode for providers, source/content types, budgets, and exact
      criterion weights; validate against operator limits.
- [ ] Show run progress, selected sources, budgets, scores, and citations in the UI.

## Reliability and evaluation

- [ ] Enforce provider request, run time, token, and cost limits; handle timeouts,
      rate limits, branch failures, malformed model output, and empty retrieval.
- [ ] Add versioned run manifests, atomic checkpoints/resume, and safe caching.
- [ ] Verify source/citation integrity, hard gates, deterministic ranking, and
      equivalent results in sequential and parallel modes on frozen inputs.
- [ ] Complete runs in three domain families; compare quality, latency, and cost
      with the same frozen cases and limits.
- [ ] Add human review results, failure analysis, reproduction commands, known
      limitations, and a short demo to the project documentation.
