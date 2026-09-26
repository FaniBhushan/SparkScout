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
- [x] Add worker and final-proposal prompt templates with structured-output
      parsing; request interpretation has its own reviewed prompt.
- [x] Add sequential/parallel coordinator, join checks, coverage checks, and ranking.
- [x] Add basic run tracing, frozen evaluation cases, and focused Library/Critic tests.

## Make one complete run work — next

- [x] Connect an LLM client to Scout query planning, candidate generation, Library
      query planning, and Critic assessment; validate every raw response with the
      matching Pydantic contract and record token/cost usage.
- [x] Resolve source registry, domain route, preset, user source policy, and hard
      limits into one `ResolvedSearchConfiguration`; select only available adapters.
      Runtime applies per-branch type/age caps; the adapter registry skips
      unavailable implementations and credentials.
- [x] Build a run-scoped retrieval index from Library chunks and give each run its
      own Critic retriever. Record index settings and retention behavior.
      The local TF-IDF/lexical hybrid enforces configured chunk, corpus, and
      estimated index-size limits with run-only retention.
- [x] Produce complete, cited `FinalProposal` records for selected candidates.
- [x] Add a runnable frozen-fixture entry point that accepts a structured request
      and returns proposals or an explicit coverage failure.
      The CLI returns full `OrchestrationResult` JSON including proposals.

## User configuration and interface

- [x] Add submitted search/evaluation contracts and a reviewed preflight snapshot;
      the application, CLI, and UI now use the same preflight path.
- [x] Add a bounded prompt-interpretation draft and explicit confirmation merge;
      uncertain/unsupported choices remain visible and cannot start research.
- [x] Enforce run-scoped time, reported model-token, and shared provider-call caps;
      an optional estimated-cost cap requires configured model pricing.
- [x] Define one validated per-run search configuration shared by the UI and
      entry points. Record explicit values, deduced values, applied defaults,
      resolved values, version, and checksum; keep operator policy authoritative.
      Optional uploads are hash-bound to the review; declared language and
      full text are limited to that adapter. Raw upload bytes and PDF pages have
      preflight caps; remote page fetching remains disabled.
- [x] Extract `InputRequest` from a prompt; show uncertain or conflicting fields
      for correction before research starts. Deduce optional search and scoring
      preferences from free text, but require confirmation for ambiguous values.
- [x] Build Streamlit Simple mode from the configured catalog: domain, interests,
      search preset, optional source types, recency, rubric preset, and instructions.
- [x] Build Advanced mode over the same state: ready providers, source/content
      types, dates, language, evidence tiers, caps, budgets, fallback behavior,
      retrieval settings, and exact criterion weights totaling 100. Preserve
      compatible values when switching modes and reject unsupported selections.
      Language and full-text controls appear only for confirmed user uploads;
      an aggregate PDF-page cap is enforced. The UI remains in `src/ui/` with a
      thin `streamlit_app.py` launch file.
- [x] Show an editable resolved-request and configuration preview before a
      deliberate start action; never start network research during form edits.
- [x] Show run progress, selected sources, enforced budgets, scores, warnings,
      citations, and the configuration behind each result in the UI.
- [x] Expose the same supported configuration through the existing CLI and add
      offline tests for defaults, deductions, conflicts, weights, mode switching,
      and pre-run validation. Do not display controls for unenforced limits as
      though they are active.

## Reliability and evaluation
- [x] Add MVP input/output guardrails: warn (do not truncate or reject) on long
      prompts, bound structured fields/lists, block recognizable credentials,
      warn about contact details, and scan model inputs/outputs and exports.
- [x] Separate instructions from input JSON and add deterministic injection,
      privacy, CLI, and UI regression tests. These do not prove model resistance.
- [x] Add nine synthetic claim-support cases and a component evaluator using the
      existing Critic, with offline scoring and explicit opt-in model calls.
- [ ] Review the claim-support labels and run real-model/adversarial evaluations;
      use measured false-support failures to decide on a runtime verifier.
- [ ] Enforce provider request, run time, token, and cost limits; handle timeouts,
      rate limits, branch failures, malformed model output, and empty retrieval.
- [ ] Add versioned run manifests, atomic checkpoints/resume, and safe caching.
- [ ] Verify source/citation integrity, hard gates, deterministic ranking, and
      equivalent results in sequential and parallel modes on frozen inputs.
- [ ] Complete runs in three domain families; compare quality, latency, and cost
      with the same frozen cases and limits.
- [ ] Add human review results, failure analysis, reproduction commands, known
      limitations, and a short demo to the project documentation.

## Post-evaluation retrieval options

- [ ] If retrieval evals show that the TF-IDF/lexical baseline misses relevant
      evidence (especially paraphrases), compare it with semantic embeddings on
      the same held-out cases. Start with a run-scoped in-memory vector matrix
      and chunk-ID mapping; measure evidence recall, proposal quality, latency,
      and embedding plus Critic token/cost usage before adopting it. Consider
      FAISS only if corpus size or search latency warrants a dedicated index.

## Submission readiness
- [ ] Improve the UI:
      - curently everything is one column. Make simple and advanced configurations collapsable.
      - All the configurations are vertically placed in one column even though the text does not require the full width of the screen. Make multiple columns .
      - overall, make better use of the screen.
      - Output shall be displayed on next page and there shall be back button to review the input.
      - option to start new search.
- [ ] Make the code readable and good quality with best practices.
- [ ] Add good comment documentation throughout.
