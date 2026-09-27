# Orchestration and worker prompts

`Orchestrator` in `src/orchestration/coordinator.py` owns the run flow. It
validates request/search domain agreement, runs Scout and Library sequentially
or concurrently, validates their join, then calls Critic. Detailed-proposal selections are
gate-passing candidates ordered by weighted score descending and candidate ID
ascending for ties. If fewer than requested pass but at least one can proceed,
the result is marked `partial` and available finalists are still drafted. If none
pass, or minimum source coverage fails, the status is `insufficient_coverage`.
Requested proposal counts are targets; gates are never relaxed to fill them.
Evidence-only failures remain visible for explicit user review after the run.
User choices are recorded separately and do not alter automatic ranking,
finalists, or completion status; see [candidate review](candidate_scoring.md).

For the deadline UI, `score_ranking` orders every retained assessment by score,
including archived recovery assessments. `score_finalist_candidate_ids` selects
the requested top count regardless of gate outcome. These ideas remain visible
with their gate reasons even without a completed draft. The existing
`finalist_candidate_ids` and `final_proposals` represent completed detailed
outputs after finalization; they are not the scorecard display selection.
`requested_finalist_count` retains the target when no prepared configuration is
attached. Defaults are five ideas and two displayed finalists. Fewer assessed
ideas produce an explicit shortfall; no missing score is invented.

Scout generation uses small batches sized to the output-token cap. Already
validated ideas survive a later malformed batch; the run's token/cost/time caps
still apply. Compact prior-idea summaries prevent repeating the same work.
Speculative ideas with `origin=synthetic` may guide internal exploration but are
removed before Scout results, Critic selection, UI display, and downloads. They
never count as supported finalists. Frozen test sources remain separately labeled
synthetic fixtures; source-backed ideas in those tests are simulations, not real
research evidence.

At the join, the coordinator checks candidate ID uniqueness and count, candidate
citations against Scout sources, Library chunk/source integrity, and source-record
conflicts. It flags near-copies only when target users and both problem/outcome
wording are highly similar; this lexical guard cannot catch paraphrased semantic
duplicates. The Library must meet `minimum_source_count` and any source types
required by the request or domain route before Critic runs. `ResolvedSearchConfiguration` defaults
that minimum to one for direct construction; the search presets define three. The
preset is resolved in `src/application/service.py`. Runs below the active threshold
return `insufficient_coverage` without spending tokens on Critic.

Scout and Library check actual usable receipts after the planned searches. If
coverage is short, each approved provider may receive one recovery query using
remaining query/record allowance. This deterministic recovery does not make an
extra planning-model call or lower the minimum coverage requirement.

Library uses `src/workers/evidence.py` to combine available source text with
adapter-supplied passages. The frozen adapter reads these passages from
`chunks.json`; their source/chunk IDs remain available for citations. Distinct
source summaries are retained as separate chunks. Transport passages are excluded
from Scout's bulk source JSON and counted in provider byte usage. Scout receives
at most one short captured excerpt per source to ground fields and permissions.
Passages become normal
Library chunks subject to corpus, chunk-count, and Critic context limits. This
does not add embedding or model calls. Source metadata is not automatically
copied into every passage.

Critic retrieval searches criteria, data dependencies, and permission terms
independently; reciprocal-rank fusion and source diversity select context within
the existing chunk/token caps. Repeating the candidate problem in every query
previously displaced relevant dataset and permission passages.

After a valid join, the coordinator builds a fresh `HybridInMemoryRetriever` for
that run. It combines deterministic local TF-IDF cosine and lexical overlap;
this is vector-based but not semantic sentence embedding. `config/retrieval.json`
sets the chunk window, overlap, corpus, chunk-count, and estimated index-size
ceilings. `OrchestrationResult.retrieval_index` records settings, size, local
vectorizer/version, and the `run_only` retention policy. The index is never
persisted. Source receipts and chunks remain in the result for audit; exported
chunks from user uploads have their text redacted, so they cannot rebuild the
index. No index is built when coverage fails.

The application drafts a `FinalProposal` for each selected finalist. Code fixes
identity, rank, and scores from the coordinator; the proposal model supplies
narrative fields and must cite only source receipts and chunks already cited in
discovery or evaluation. Unavailable discovery excerpts are omitted with a
warning; evaluated citations must still be valid. A separate budgeted verifier
checks claim support, essential data dependencies, and narrative assertions.
One draft correction and recheck is allowed. A failed finalist is recorded in
`proposal_failures`, while other verified proposals survive as partial results.
No valid proposals yields `insufficient_coverage`. Verification is a model
judgment, not a guarantee; raw scores and ranking are never rewritten.

The temporary demo policy `allow_provisional_narrative` in `config/rubric.json`
is enabled by explicit project-owner approval. Only after one correction, a
remaining unsupported problem/benefit/differentiation statement may be prefixed
"Unverified hypothesis to test (not an established fact)". Original negative
verdicts remain in the audit's `narrative_checks`; `caveated_fields` records this
last-resort decision. `passed` means all checks passed; `accepted` also permits
this narrow, explicit qualification. Fact citations, data dependencies,
implementation requirements, contradictions, and budgets are never waived.
Set the flag to `false` to restore strict withholding. This is not a substitute
for the deferred human review or a general production policy.

Finalization tries gate-passing candidates in rank order until the requested
proposal count is reached or the eligible pool is exhausted. A failed draft or
verification advances to the next candidate; completed proposals are retained.
If none survives, `src/application/recovery.py` attempts one recovery round using the same
request, rubric, and budget. It reuses Library evidence, makes at most two targeted
searches from remaining query/provider allowance, and generates up to three
distinct alternatives informed by rejection reasons. Every replacement is scored
and verified normally. No additional round runs when a valid partial result exists.
Before writing, an essential-input check rejects unavailable or task-inappropriate
data dependencies. Proposal context can include four additional whole Library
passages (6,000 characters total) to avoid losing dependency evidence between
Critic and writer. Full draft verification still runs afterwards. Missing or
duplicate verifier checks receive one bounded repair; extra, unrequested checks
cannot establish support and are discarded. Narrative caveats never waive the
task-data check.

Discovery/scoring protect up to 30,000 tokens (one-third of the cap); recovery
protects up to 12,000 (one-sixth). Neither adds to the user cap. Near the limit,
exact provider input counting can replace the conservative byte estimate, with
an atomic reservation recheck. If drafting cannot continue, the result retains
sources, assessments, and any proposals with `budget_exhausted=true` rather than
throwing away completed work. No new recovery round starts after that stop.

Prior evaluations and failures remain in `recovery_history`; exhausted recovery
is explicitly reported and does not count as success. Separate recovery stage
checkpoints prevent repeated calls on resume.

The research and proposal prompt templates live beside their loader in
`src/prompts/`:

- `scout_query_planner.md` plans bounded discovery searches.
- `scout_candidate_generator.md` proposes distinct ideas from the request and
  Scout source records.
- `library_query_planner.md` creates a broad, independent research plan.
- `critic_candidate_judge.md` returns criterion and hard-gate judgments using
  retrieved evidence only.
- `final_proposal.md` drafts complete finalist narrative and citations.
- `proposal_statement_verifier.md` checks isolated draft statements against cited passages.

`request_interpreter.md` separately drafts request and configuration fields
from user text; it is reviewed before research starts.

`render_prompt(name, ...)` inserts JSON input and the output JSON Schema generated
from the corresponding Pydantic contract. `parse_model_output(name, response)`
validates raw JSON or Python output against the same contract. Worker interfaces
remain injected; `src/application/service.py` wires them to an injected LLM client, while
`src/ui/cli.py` uses the existing OpenAI client for frozen-fixture runs. Optional
[checkpoints and resume](checkpoints.md) preserve validated stage outputs and budgets.
`src/application/service.py` applies the reviewed
time/token budgets and shared provider-call limits around both branches and final
proposal writing. Cost limits require configured rates and are off by default.
