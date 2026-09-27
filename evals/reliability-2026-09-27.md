# Reliability evaluation — 27 September 2026

Scope: complete the Reliability and evaluation section of TASKS.md except the
last human-review/documentation/demo task. All research fixtures remain synthetic.

## Label review before evaluation

Coding-assistant review, not independent human review. Existing development and
held-out labels are unchanged. Held-out targets, small samples, and surveys do
not establish achieved accuracy, universal demand, or causality. Explicit GPU,
license, and participant-count conflicts are contradictions.

The new adversarial set has four supported, four unsupported, and four
contradictory cases. Supported cases repeat or cautiously paraphrase an explicit
fact. Missing yield fields, unspecified image labels, an absent tool comparison,
and an untested result remain unsupported. Restricted patient data, a research
prohibition, a different tool's hardware, and a changed license contradict their
claims. Embedded instructions do not alter any label. This is a new challenge
set, not an independently curated benchmark. The existing held-out set remains
unchanged and is reported separately.

## Runtime verifier decision

The saved end-to-end robotics proposal asserted yield-forecasting support from
generic crop images. An accessibility proposal asserted an unestablished gap in
existing tools. Citation-ID validation did not detect either semantic problem.
These observed failures justify a separate verification call for finalists only.
One bounded correction and recheck is allowed; failed drafts are withheld while
other completed proposals survive. All calls use the existing run budget.

The initial end-to-end comparisons are retained as diagnostic history below;
the latest measurements follow after the verifier redesign.

The verifier is retained, but is not treated as an oracle. A subsequent narrative
review caught circular rationales ("the proposal says so") even after the simple
claim sets passed. Supported narrative/dependency verdicts now require exact
quotes from captured evidence, or an explicit user-provided resource for a data
dependency. A quoted sentence still requires semantic judgment; its mere presence
cannot prove the model's inference. Audit excerpts are redacted from exports for
runs containing uploads, preserving memory-only upload retention.

## Defects addressed

- Independent retrieval queries now cover dependencies and permission terms.
  Repeating the entire problem statement for every criterion previously pushed
  available dataset passages out of the top results. Reciprocal rank fusion and
  source diversity retain useful context within the existing limits.
- Scout is directed to use documented fields and offline evaluation methods,
  avoiding invented label types and assumed access to participants.
- Final drafts receive a separate claim and narrative audit. All claim references
  must resolve to exact supplied chunks. One corrected draft is rechecked; other
  successful proposals are retained if one draft fails. Failed candidate IDs and
  reasons are recorded without altering their original Critic scores.
- Checkpoints retain verification results for the exact draft and evidence.
  Component evaluation failures now save usage receipts rather than losing cost
  accounting when an exception interrupts a suite.
- Coverage recovery uses actual usable source receipts, not the number of source
  types in a plan. One remaining approved query per provider can fill missing
  coverage without another planner call or a relaxed minimum.
- The model receives task instructions separately from untrusted JSON. A narrow
  evidence-view filter removes standalone commands to manipulate judgment labels;
  original captures remain intact. This is not general prompt-injection protection.
- Compact JSON and removal of duplicated scoring tables reduce prompt overhead.
  Candidate generation receives one small captured source excerpt for data/access
  facts rather than the complete source collection.

## Initial claim measurements

| Frozen set | Critic correct | Verifier correct | False support, both |
| --- | ---: | ---: | ---: |
| Development, 9 | 8/9 | 9/9 | 0/6 |
| Held-out, 6 | 5/6 | 6/6 | 0/6 |
| Adversarial, 12 | 10/12 | 11/12 | 0/8 |

These are single runs. The Critic still confused one absent result with a
contradiction; its adversarial set also contained an inconsistent stance/gate.
Both judges rejected a supported repository fact when its passage included an
instruction to answer contradictory. That false rejection is retained as an
observed injection weakness, even though neither accepted unsupported claims.
The next revision targeted that distinction before the final comparison.

## Final component measurements

| Frozen set | Critic correct | Final verifier correct | False support |
| --- | ---: | ---: | ---: |
| Development | 8/9 | 9/9 | 0/6 each |
| Held-out | 6/6 | 6/6 | 0/6 each |
| Adversarial | 11/12 | 9/12 | 0/8 |
| Narrative/dependency regressions | Not run | 4/6 | 0/3 |

Critic results are the `*-filtered-critic.json` runs. Latest verifier results are
`*-statements-verifier.json`. It rejected three explicit contradictions as
unsupported and missed one unsupported case; both labels still block a draft.
On the narrative set it caught invented tool gaps and an invented data dependency,
but rejected valid proposed/comparison statements. No gold labels or source
fixtures were changed to improve these scores.

The verifier scored 28/33 across these small component sets, with no false
support among 23 negative cases. This is a high rejection rate and the last
statement-format redesign has only component testing; its runtime effect is not
measured. The `allow_provisional_narrative` demo flag qualifies clearly
hypothetical or unsupported soft narrative after one correction. It does not
waive citations, dependencies, or implementation checks. This setting and the
statement-based verifier have not yet had a paid end-to-end run. The narrative
set was created from observed failures, so it is a development regression set.

## Latest paid end-to-end status

`2026-09-27-release-sequential` finished all three cases in sequential mode:
robotics 1 proposal, accessibility 0, medicine 0; suite usage was 146,047 model
tokens, $0.038156 estimated cost, and 303.18 seconds. The proposals were not
independently human-scored, so this is not a successful three-domain quality
comparison. Older sequential/parallel runs used different verifier versions
and do not constitute a controlled comparison. The final source-format verifier
and narrative qualification changed after this run. This report therefore leaves
the three-domain task open.
Future withheld proposals now include the failed check IDs and labels in the
run result, without copying source text into diagnostic warnings. The current
paid report predates this diagnostic improvement and the provisional-narrative
policy.

Across saved paid component and end-to-end reports, local accounting is about
$0.4925 including $0.0054 reserved for unknown usage, against the user's $2
authorization. This is not provider-billing reconciliation; it is unrelated to
Codex's own five-hour agent rate limit.

Detailed predictions, confusion matrices, usage, and prompt hashes are in the
ignored `evals/reports/2026-09-27-claims-*.json` files. Independent human review is
still the separately excluded final task.
