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
- [x] Clarify evidence sufficiency around essential MVP dependencies and time
      scope around supported deadline conflicts. Show uncertainty in results;
      let users keep or decline evidence-only failures after acknowledging caveats.
      Preserve the original assessment and record decisions in session/downloaded
      JSON without model calls or automatic finalist promotion. Known time/data
      conflicts remain blocking. Offline backend and UI tests pass; updated model
      judgment quality still needs evaluation.
- [x] Expose the same supported configuration through the existing CLI and add
      offline tests for defaults, deductions, conflicts, weights, mode switching,
      and pre-run validation. Do not display controls for unenforced limits as
      though they are active.

## Reliability and evaluation
- [x] Treat requested proposal counts as targets: return valid partial results
      without filling the user output with synthetic ideas. Allow explicitly
      labeled synthetic ideas only for internal exploration and filter them
      before Scout results, Critic selection, display, and downloads.
- [x] Bound candidate generation to small responses; preserve earlier valid
      batches after malformed/truncated output. Stop on no progress; shared
      budgets remain authoritative. Record target attainment separately from
      structural evaluation success.
- [x] Connect frozen `chunks.json` passages to Library and Critic; preserve source
      links and citation IDs alongside distinct summaries. Include passages in
      byte accounting and frozen-input fingerprints. Offline tests verify the
      actual Critic prompt in both modes. A live robotics rerun cited prepared
      evidence; proposal generation still failed the separate feasibility gate.
- [x] Add a modular development-case end-to-end runner with frozen sources,
      structural checks, failure/usage reports, and per-proposal human review
      sheets. Offline default suite exercises three domains and reports expected
      demo limitations; paid end-to-end quality evaluation remains pending.
- [x] Clarify missing versus contradictory evidence in the Critic prompt following
      the first component baseline. The updated prompt still needs live evaluation.
- [x] Add MVP input/output guardrails: warn (do not truncate or reject) on long
      prompts, bound structured fields/lists, block recognizable credentials,
      warn about contact details, and scan model inputs/outputs and exports.
- [x] Separate instructions from input JSON and add deterministic injection,
      privacy, CLI, and UI regression tests. These do not prove model resistance.
- [x] Add nine synthetic claim-support cases and a component evaluator using the
      existing Critic, with offline scoring and explicit opt-in model calls.
- [ ] Review the claim-support labels and run real-model/adversarial evaluations;
      use measured false-support failures to decide on a runtime verifier.
      Assistant label review is recorded in `evals/guardrails/label_review.md`;
      First real-model baseline: 6/9 correct, zero false-support predictions;
      all three unsupported cases were mislabeled contradictory. Broader
      adversarial/held-out testing and the verifier decision remain open.
      Approved: gpt-4o-mini, $1 maximum. Root .env loading and explicit per-run
      evaluation cost/rate arguments are implemented. Baseline cost: $0.00450315.
- [x] Enforce provider request, run time, token, and cost limits; handle timeouts,
      rate limits, branch failures, malformed model output, and empty retrieval.
      Required parallel failures now cancel/drain siblings; budget exceptions
      propagate consistently. Unknown model usage retains reserved allowance.
      SDK retries are disabled; optional one-retry policy reserves each attempt.
      Typed provider/model failures and Retry-After handling are tested offline.
- [x] Add versioned run manifests, atomic checkpoints/resume, and safe caching.
      CLI/application opt-in, atomic state plus budget, 24-hour stage-cache reuse,
      frozen replay, exclusive writer, and input/code fingerprints are implemented.
      Upload-derived stage outputs remain memory-only; re-upload/recompute uses
      the remaining budget. See docs/checkpoints.md for retention and limitations.
- [x] Verify source/citation integrity, hard gates, deterministic ranking, and
      equivalent results in sequential and parallel modes on frozen inputs.
      Deterministic end-to-end comparison includes tied scores and a high-scoring
      candidate rejected by a hard gate; live model equivalence is not claimed.
- [ ] Complete runs in three domain families; compare quality, latency, and cost
      with the same frozen cases and limits.
      The original live baseline exposed fixture coverage and model-output
      errors. After gate-policy and bounded-generation changes, all three cases
      finished without execution errors; accessibility returned one proposal,
      robotics and medicine returned none. See evals/three_domain_review.md.
      The latest accounted spend is approximately $0.2115 of $1, including
      reserved unknown usage. A prior robotics proposal had unsupported claims
      despite valid citation IDs. Semantic support and human review remain open.
      Partial-result and internal-only synthetic handling are tested offline;
      they were added after the latest paid run started.
      Three-domain live quality and successful-run latency comparison remain open.
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
- [ ] Explain evaluation criteria in the UI so users can choose weights confidently.
      Place an info (ⓘ) or question-mark (?) icon beside each criterion; hovering
      or clicking should show a tooltip with a plain-language definition, a short
      example, and what a high/low score means. Make help accessible through
      keyboard focus and touch as well. Explicitly explain
      that a high delivery-risk score means low risk, and distinguish problem value
      from evidence of a real-world pain point. Make the same help available in the
      results view and Simple mode; Advanced mode should explain weight effects,
      the 100% total, zero weights, and the difference between scores and hard gates.
      Add a short description of each preset. Keep user-facing descriptions in one
      shared catalog, separate from internal retrieval instructions.
- [ ] Make the code readable and good quality with best practices.
- [ ] Add good comment documentation throughout.

## Deferred improvement — after current tasks are complete

- [ ] Apply a recovery-first policy throughout the system: request interpretation,
      planning, adapters, Scout, Library, retrieval, Critic, proposal generation,
      orchestration, and entry points. Prefer safely completing the remaining
      steps over making users restart and pay again for completed work.
      - Preserve validated intermediate results and resume only missing or failed
        work, respecting memory-only upload retention and existing checkpoints.
      - Prefer deterministic adjustments before another model call. For E05,
        clamp planned result counts before search and discard any surplus
        provider results instead of aborting the run.
      - Repair only unambiguous output defects; otherwise use bounded retries
        for the failed step within the remaining shared budget. Skip optional
        failures only when downstream requirements still hold.
      - Never bypass privacy, source/citation integrity, coverage requirements,
        or time/token/cost limits. When safe completion is impossible, return an
        explicit partial outcome with preserved progress and recovery options;
        do not present incomplete work as a successful proposal.
      - Trace adjustments, retries, skipped work, and extra usage; show concise
        user warnings without silently lowering quality or changing intent.
      - Add fault-injection tests across stages and both scheduling modes to
        verify recovery, no unnecessary repeat calls, and unchanged hard gates.
