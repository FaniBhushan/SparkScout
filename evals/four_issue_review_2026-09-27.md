# Four reliability fixes — 27 September 2026

## Scope

Address premature token reservations, missing proposal evidence, verifier errors,
and recovery producing no usable proposal. Keep the static rubric and existing
privacy, citation, evidence, time, and spending limits. Never manufacture a
proposal to make a metric pass.

## Implementation

- **Budget:** retain conservative reservations normally; when one does not fit,
  ask the provider for the actual input-token count using the identical request
  payload. Recheck atomically with the full output allowance. If counting fails,
  retain the original rejection. Unknown generation usage remains reserved.
- **Stage allowance:** discovery and Critic retain up to 30,000 tokens (at most
  one-third of the run cap) for drafting/verification. This is part of the existing
  cap, not extra allowance. Preserve completed assessments and explicitly mark
  unassessed candidates when this threshold stops Critic.
- **Evidence:** finalization adds up to four whole, dependency-matching Library
  passages, totaling at most 6,000 characters. Recovery generation receives
  Library passages even after sources have been restored from checkpoints.
- **Verifier:** check data availability separately from relevance. Exact source
  quotations remain required; a metric description cannot establish log access.
- **Task suitability:** verify that data fields and labels support the actual
  proposed artifact, not just that a dataset exists. This check cannot use the
  narrative-hypothesis fallback. Retry an invalid `proposed` factual verdict once
  using only the affected checks; do not regenerate the whole draft for that error.
- **Earlier checks and response repair:** check candidate inputs before drafting;
  reject missing essential dependencies before spending on a narrative. Normalize
  only a singleton candidate object or an exact `candidates` wrapper, retaining
  every candidate field for full schema validation. Missing/duplicate verifier
  checks receive one targeted repair; extra checks are ignored, not used as support.
- **Recovery:** keep sources, judgments, and successful proposals when drafting
  exhausts the budget. Mark `budget_exhausted`; do not start another paid recovery
  round after that stop. Existing ranked backfill and one replacement round remain.
  Recovery now uses a smaller reserve (up to 12,000 tokens, at most one-sixth of
  the run cap), rather than being blocked by the earlier exploration threshold.

The exact-count endpoint was also checked against the configured model. It
returned 15 input tokens for a small test sentence without requesting generation.
Counting and generation share the same input/instructions construction, following
the [official token-counting API guidance](https://developers.openai.com/api/docs/guides/token-counting).

## Validation

221 offline tests passed after adding stage-stop retention and token-reservation
regressions. Fixture validation and whitespace checks passed.

The initial six-case dependency/access model test scored 4/6 with zero false
support in that small set. One response was invalid and one explicit contradiction
was labeled unsupported. This is not evidence that the verifier is generally
accurate. Results: `evals/reports/2026-09-27-four-fixes-dependency-access.json`.

The first parallel rerun is retained under
`evals/reports/2026-09-27-four-fixes-parallel/`. Inspection of its robotics recovery
found a task/data mismatch: generic crop-image labels were accepted for disease
detection. A structurally accepted proposal is not necessarily a valid proposal;
this finding requires a task-specific data-suitability check before success is
claimed. This was a development finding, not an accepted demonstration of safety.

### Latest full parallel suite

`evals/reports/2026-09-27-four-fixes-parallel-v2/results.json` uses the same three
synthetic frozen cases and unchanged 100,000-token per-run limit.

| Case | Returned / requested | Outcome |
| --- | --- | --- |
| Robotics | 0 / 3 | No verified proposal; bounded recovery exhausted |
| Accessibility | 1 / 3 | Partial result retained at the budget limit |
| Medicine | 1 / 3 | Partial result |

Reported tokens: 261,220; model cost: $0.0666051; suite duration: 529.20 seconds.
There were no top-level case errors or skipped cases. This is structural acceptance,
not human quality approval. In particular, the accessibility proposal includes a
user-survey step: participant access and the public-data-only constraint need
review. Do not present it as independently verified feasibility.

### Live search

`evals/reports/2026-09-27-four-fixes-live/results.json` returned no proposal after
recovery, using 76,749 tokens and $0.0187731 in reported model cost. Captured RAG
overview passages did not establish access to the proposed operational metrics,
historical logs, or user feedback. The final draft failed dependency/task-data
verification. Trace: `runs/883d0fc94be14cd1879e33343b3faf97/trace.jsonl`.

### Focused verifier tests

- Dependency/access final test: 5/6 exact labels; all six accept/reject decisions
  matched the expected support boundary. Report: `four-fixes-dependency-access-v3.json`.
- Task/data final test: 5/6 exact labels; all six accept/reject decisions matched.
  Report: `four-fixes-task-data-fit-v3.json`.
- Reports: [dependency/access](reports/2026-09-27-four-fixes-dependency-access-v3.json)
  and [task/data](reports/2026-09-27-four-fixes-task-data-fit-v3.json). Each remaining
  exact-label error classified an explicit contradiction as unsupported; neither
  was accepted.
- Task/data fixture version 1.1 replaces an ambiguous input placeholder with
  declared data requirements. Claims, evidence, and expected labels are unchanged.
  Earlier version-1.0 results remain in the dated reports; this is not a matched
  ablation proving a model improvement. No human ratings are implied.

### Targeted early-check test

`evals/reports/2026-09-27-four-fixes-input-precheck/results.json` returned zero
proposals at 45,968 tokens / $0.01159005. It exposed a malformed recovery candidate
response and a verifier check-set mismatch. The narrow envelope/check-set repairs
were then added and covered by offline tests. A final targeted run is reported below.

### Final targeted run

`evals/reports/2026-09-27-four-fixes-final-robotics/results.json` includes the early
input check and response-shape repairs. It returned **0/3** proposals at 96,579
reported tokens / **$0.02462355**, in 199.82 seconds. There was no top-level error;
the full result was retained with `budget_exhausted=true`.

Prechecks correctly blocked disease-classification ideas without documented
disease labels, but also rejected a benchmark dependency named in source metadata.
A benchmark-tool candidate passed the early check, then failed full-draft checks
after correction. This demonstrates continuing semantic verifier problems, not a
completed fix. No further recovery calls were made after the budget stop.

## Cost and handoff

The completed tests in this follow-up report total **$0.1796328** in estimated model
usage. This excludes Tavily billing, does not describe the account's invoice, and
does not include older project runs. All source/model artifacts remain separate;
no failing result was replaced with a favorable retry. No human scores were added.

Budget counting/retention and bounded repair behavior are implemented and tested.
Evidence availability, semantic verifier accuracy, and reliable proposal yield
remain open. The next decision is whether to evaluate a stronger verifier under
a small explicit cap, or narrow the demo to a reviewed evidence-supported case.
More retries with the unchanged model are not a demonstrated solution.

## Remaining gaps

- A valid proposal for every domain is **not guaranteed or demonstrated**.
- Better context cannot supply absent labels, participant access, or datasets.
  Candidate selection and targeted source acquisition still need improvement.
- The verifier still makes false rejections and semantic mistakes; exact quotes
  and valid IDs do not prove entailment. Component scores do not replace reviewing
  complete proposals.
- Stage reserves are bounded scheduling heuristics, not a guarantee that recovery
  can finish within any chosen cap. Real exhaustion still stops paid work.
- The latest full suite and live run preceded the final early-check/envelope
  repairs; they must not be described as a complete validation of the final code.
