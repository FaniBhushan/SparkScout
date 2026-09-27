# Issue and design decision log

Updated 27 September 2026. This is the concise index of issues and decisions
recorded during MVP development. The linked evaluation reports retain the full
run data, dates, and caveats. Frozen evaluation sources are synthetic.

## Observed issues and decisions

### Deadline finalist presentation — 27 September

The user chose two displayed finalists by default, configurable counts, and
compact scorecards for every other assessed idea. Score ranking now ignores gate
outcome; failed gates remain prominent on the selected scorecard. A full proposal
can still be withheld by gates or evidence verification. This keeps useful paid
assessments visible while preserving their actual readiness status. Recovery
retains earlier candidate details for the same comparison view.

The deadline validation uses offline tests, deterministic demo runs, and a replay
of saved real-model assessments. Existing quantitative and blind-judge results
are reported as historical evidence, not as a new live evaluation of the display
change. Human ratings remain pending. See
[`evals/demo_submission_2026-09-27.md`](../evals/demo_submission_2026-09-27.md).

User-feedback refinement is deferred: an explicit user action may authorize one
additional pass using feedback and the remaining budget, retaining the original
ideas and scores. This requires iteration/checkpoint handling before activation.

### Final demo-readiness task: independent human review — 27 September

The remaining evaluation action is for the project owner to score the three
saved controlled proposals using the human rubric: one medicine proposal and two
robotics proposals. Enter five separate 1–5 ratings per proposal and add a short
reason for any 1 or 5. Do not copy or consult the LLM-judge scores while rating.
Then run `evals.analysis.metrics` with both completed score sheets to record exact
agreement, mean absolute difference, and disagreements by dimension. The review
CSV files are still blank, so human scores and model-human agreement are pending;
they must not be estimated or labeled as completed. Current values, score-sheet
paths, and the analysis command are in
[`evals/demo_submission_2026-09-27.md`](../evals/demo_submission_2026-09-27.md).

The short demo recording is also pending. Follow
[`docs/demo_recording_guide.md`](demo_recording_guide.md), label frozen inputs as
synthetic, and show the low proposal yield alongside the three-proposal judge
sample. This keeps the demo claim aligned with the measured evidence.

| Finding | Decision and rationale | Status |
| --- | --- | --- |
| Scout and Library found the same source under different query IDs and capture times. | Compare source content rather than volatile receipt fields. Keep the first matching receipt, but still reject conflicting content. | Fixed; regression coverage is in `evals/issues-2026-09-26.md`. |
| Parallel usage settlement left tiny floating-point residue in reserved cost. | Clamp the remainder to zero and clear it when no reservations remain; counters should reflect meaningful budget state. | Fixed and tested offline. |
| Some success fixtures had fewer sources than the minimum coverage policy. | Expand the success fixtures; preserve insufficient-coverage cases as explicit failure tests. Do not lower the coverage gate to make an evaluation pass. | Fixture follow-up recorded in the issue report; latest three-domain quality result remains incomplete. |
| Candidate output occasionally had a known misspelled field; other malformed output is unsafe to accept. | Repair only the explicitly recognized, unambiguous typo. Keep schema validation and bounded recovery for other output defects. | Fixed for the known typo; arbitrary repairs remain disallowed. |
| Query planners could exceed configured query/result limits. | Clamp result counts and drop excess planned queries before contacting providers. Hard limits remain authoritative. | Planner side is fixed. A separate gap remains: Scout and Library currently abort if an adapter returns more records than requested; safe surplus truncation is in the deferred recovery plan. |
| Critic confused absent evidence with explicit contradiction. | Clarify the labels and instructions, retain supported/unsupported/contradictory as distinct outcomes, and measure the verifier separately. | Improved, not solved: small component sets still show false rejection and some contradiction mislabels. See `evals/reliability-2026-09-27.md`. |
| Frozen `chunks.json` passages were not reaching Critic; short summaries lost important details. | Preserve source receipts for provenance and chunks for claim-level evidence. Pass prepared passages into Library, then retrieve only a bounded subset for Critic to control prompt cost. | Fixed and verified offline and in a paid robotics run. |
| Valid citation IDs did not guarantee that a claim was supported; proposal drafts could add unsupported claims or dependencies. | Add finalist-only statement verification against supplied passages, allow one correction, withhold a failing draft, and preserve other successful proposals. Keep rank and score deterministic. | Implemented; the verifier is imperfect and needs end-to-end and human review. |
| Strict verification rejected some useful hypothetical problem/benefit statements. | As a last-resort demo policy, allow only narrowly scoped soft narrative to be explicitly labeled an unverified hypothesis after one correction. Never use this to waive citations, data/tool dependencies, implementation support, contradictions, hard gates, or budgets. | Implemented behind `allow_provisional_narrative`; revisit after evaluation. |
| Planned source types did not always match usable search receipts. | Check actual usable sources and allow one bounded recovery query per approved provider before returning insufficient coverage. Do not treat a planned type as evidence or lower the minimum. | Implemented; provider failures and adapter over-returns still need broader recovery behavior. |
| Synthetic idea padding could make requested counts look successful despite weak evidence. | Treat requested counts as targets, preserve valid partial results, and keep synthetic exploration internal. | Implemented and tested offline. |
| Parallel cancellation or provider failures can leave uncertain billed usage. | Reserve allowance before calls, settle only reported usage, retain unknown-usage reservations, disable SDK retries, and make any application retry bounded and budgeted. | Implemented and covered by focused offline tests. |
| Upload text has stricter retention needs than ordinary source metadata. | Keep upload-derived stage outputs in memory; require the user to re-upload to resume after process restart. | Implemented; UI checkpoint/resume is not exposed. |
| Embedded instructions in source text could influence model judgments. | Separate trusted task instructions from supplied data and apply a narrow evidence-view filter. Do not claim this is general prompt-injection protection. | Partial mitigation; broader adversarial testing remains necessary. |
| The live robotics fixture requires `community_signal`, while current live Tavily results are `web_article`. | Keep the types distinct; do not relabel general web results as community evidence. Use a live request requiring supported types or build a suitable community-signal source later. | Current configuration mismatch for that frozen case in live mode. |

## Design choices and rationale

- **Typed contracts and injected worker dependencies:** Pydantic models validate
  boundaries, while the orchestrator controls sequencing and shared budgets. This
  makes workers independently testable and prevents hidden provider/model calls.
- **Frozen sources for repeatable evaluations:** These isolate pipeline and model
  behavior from changing web results. They are synthetic and cannot establish
  real-world evidence quality; live-source testing is a separate step.
- **Source records and chunks serve different jobs:** Source records preserve
  identity, links, dates, and provider metadata. Chunks provide bounded text for
  retrieval and evidence checks. Keeping both avoids copying all metadata into
  every model prompt.
- **Local lexical/TF-IDF retrieval is the baseline:** It avoids an embedding
  provider, another model charge, and added index dependencies. Semantic
  embeddings remain an evaluation-driven option if held-out retrieval results
  show that paraphrases are missed.
- **Static Critic criteria for the deadline:** The existing rubric and presets
  remain stable for the demo and comparisons. User-selected weights are supported.
  Dynamic criteria need a reviewable schema, explicit confirmation, run-level
  versioning, and consistency evaluations before use; see the deferred plan in
  `TASKS.md`.
- **Hard gates stay separate from weighted scores:** Mandatory constraints,
  permitted data/resources, and supported unavoidable deadline conflicts cannot
  be offset by a high score. A limited evidence-only user review is recorded
  without rewriting the Critic result or promoting a candidate automatically.
- **Recovery is bounded by correctness and budget:** Prefer deterministic
  adjustment, preserve validated work, and return partial/insufficient outcomes
  when safe recovery is unavailable. Never silently relax evidence, privacy,
  coverage, or spending requirements.

## Duplicate live sources — 27 September 2026

**Observed issue:** Tavily returned the same webpage with query-dependent titles
and snippets. Content-based duplicate checks treated these as conflicting records:
the first live attempt stopped in Scout, and the retry stopped at the
Scout/Library join before final proposals were produced.

**Initial mitigation:** Tavily identity used provider, source type, and canonical
URL, retaining the first record. This avoided snippet-based identity conflicts
but discarded useful evidence from later searches.

**Implemented improvement:** Separate source identity from evidence
excerpts. Keep one source record with multiple distinct excerpts, each carrying
its source ID, text hash, retrieval time, and provenance. Deduplicate identical
excerpts while preserving different passages. Normalize URLs conservatively:
remove fragments and known tracking parameters, but preserve content-identifying
parameters; use stable repository IDs for GitHub where available.

Use a shared, deterministic merge policy in workers and orchestration so
sequential and parallel execution preserve the same evidence. Isolate genuine
identity conflicts, trace them, and continue with valid records when coverage
permits. Retrieve only relevant excerpts for Critic: retaining evidence in memory
does not itself add model tokens.

The shared implementation is `src/sources/merge.py`. Public search excerpts and
their receipts survive source checkpoint serialization; upload text retains its
existing memory-only treatment. At the join, Scout excerpts augment only sources
also retrieved by Library. Existing Library chunk IDs remain available, and
identical text is not indexed again. Live identity collisions are quarantined;
affected candidates are withheld at the join and coverage is checked again.

**Rationale and verification:** Different snippets are additional evidence, not
proof of inconsistent source identity. Offline tests cover identical and differing excerpts,
meaningful URL parameters, conflicting IDs, preserved citation links, and
equivalent merges in both scheduling modes. A subsequent live run completed;
see the [recovery evaluation](../evals/recovery_review_2026-09-27.md).
See the [live-run findings](../evals/controlled_evaluation_2026-09-27.md).

## Proposal backfilling and bounded recovery — 27 September 2026

**Issue:** Finalization previously withheld a failed finalist without trying
lower-ranked candidates that had already passed Critic. A completely rejected
pool also had no second research attempt, wasting reusable evidence and scores.

**Implemented decision:** Finalization now tries eligible candidates in rank
order, retaining verified proposals and skipping recorded failures. If no
proposal survives, one recovery round reuses Library evidence, uses at most two
remaining search calls, and generates up to three distinct alternatives using
the recorded rejection reasons. Replacements pass the unchanged Critic and
proposal verifier. Existing time, token, provider, and cost limits apply to all
attempts. Separate checkpoints reuse successful recovery work on resume.

**Rationale:** Try already-paid-for candidates first. Bound new research rather
than repeatedly generating similar ideas on unchanged evidence. Record earlier
assessments in `recovery_history`, and include their gate failures in evaluation
metrics. Empty or budget-exhausted results remain visible failures of the product
goal; an arbitrary request cannot be guaranteed a valid proposal.

**Verification:** Offline tests cover backfilling, replacement evaluation in both
scheduling modes, unchanged-idea rejection, privacy blocking, and checkpoint
reuse without additional model calls. The live test completed with one proposal
using the existing narrative-caveat policy; broader results are recorded in the
recovery evaluation report. Human quality review remains necessary.

## Remaining evaluation/design risks

### 27 September follow-up: four reliability issues

Use exact input counts only when conservative reservations do not fit; reserve
within the existing token cap for finalization and release more allowance to
bounded recovery. Preserve partial results and explicitly account for unscored
candidates. This avoids both premature rejection and hiding spent work.

Pass whole dependency evidence into drafting and run an input-suitability check
before paying to write a narrative. Data existence, access, and task-specific
labels are separate questions. A crop-image dataset is not proof of disease
labels. Repair unambiguous candidate envelopes and incomplete verifier check
sets within bounded attempts; never infer missing candidate content or support.

Implementation and measured limitations are in the
[four-issue review](../evals/four_issue_review_2026-09-27.md). That review supersedes
the historical counts below. The every-domain-valid-proposal requirement remains
open; stronger rejection is not evidence of improved proposal yield.

- The latest matched three-domain runs returned 3/9 proposals sequentially and
  0/9 in parallel. Budget reservations and verifier rejections remain blockers.
  Blind model reviews exist; independent human review is pending. See the
  [recovery evaluation](../evals/recovery_review_2026-09-27.md).
- A live verifier accepted query-log availability based on a general description
  of retrieval metrics. That is weak support for actual data access; model
  acceptance alone must not be treated as independently established feasibility.
- Current verifier measurements show no observed false support in small synthetic
  sets, but also show false rejection and misclassification. Model verification
  is a safeguard, not proof.
- The recovery-first policy is not consistent across all entry points and stages.
  Optional provider failures, adapter over-returns, UI resume, and comprehensive
  fault-injection coverage are still open.
- No current live search adapter emits `community_signal`; the robotics frozen
  case expects that type. Do not interpret a frozen-fixture success as a live
  search result.

## Detailed evidence

- [26 September evaluation issues](../evals/issues-2026-09-26.md)
- [Three-domain measurements](../evals/three_domain_review.md)
- [27 September reliability and verifier evaluation](../evals/reliability-2026-09-27.md)
- [Checkpoint and recovery behavior](checkpoints.md)
- [Orchestration, evidence flow, and gates](orchestration.md)
