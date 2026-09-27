# Three-domain evaluation — September 26, 2026

This file preserves the earlier September 26 diagnostic history. The latest
controlled sequential/parallel comparison, blind LLM-judge results, and live
`web_article` demo attempt are recorded in
[the September 27 evaluation](controlled_evaluation_2026-09-27.md).

See the [consolidated issue report](issues-2026-09-26.md) for defect status,
follow-up actions, and the related Critic baseline findings.

## Follow-up status

The tables below preserve the initial twelve attempts. Later recovery attempts
reached Critic but still produced no final proposals. In the latest robotics
attempt, four sources were collected and three candidates were scored; all
three failed evidence sufficiency, and another candidate was skipped for an
invalid citation. Those runs indexed source summaries while omitting prepared
fixture passages.

The frozen adapter now passes `chunks.json` evidence to Library alongside source
summaries. Offline tests verify that the dataset permission passage reaches the
actual Critic prompt in both modes, with unchanged call count and context limits.
Both fixture files are now fingerprinted. All 158 tests and fixture validation
pass. A paid robotics rerun is recorded below; successful proposal quality is
still unverified.

The saved end-to-end reports total $0.11489220; recorded Critic component runs
add $0.01219290. Including $0.00406305 reserved for unknown canceled-call usage,
the estimate before the rerun was **$0.13114815 of $1**. This is local accounting, not a
reconciled provider bill. The earlier spending section is the historical baseline.

### Robotics rerun after evidence loading was fixed

`gpt-4o-mini`, sequential, unchanged case request and prompts, $0.05 invocation
cap. The first attempt failed to connect in the restricted environment; the
subsequent approved connection completed in 31.125 seconds.

- Four sources and eight chunks were indexed, including the prepared passages.
  Critic cited `rbt-community-001-c1`, confirming captured fixture evidence was
  used in a live judgment. Source coverage, scoring, and ranking checks passed.
- Scout returned two of twelve requested candidates. Even if both passed, they
  could not satisfy the requested three final proposals.
- Both candidates were assessed without schema or citation errors. Scores were
  76.0 and 77.2, but both failed the `evidence_sufficiency` hard gate. All other
  gates passed; zero proposals were produced.
- Rejection rationales refer to anecdotal evidence and missing quantitative
  feasibility/outcome evidence. Candidate descriptions also include benefits
  beyond the supplied evidence. The next review must distinguish an essential
  feasibility dependency from a proposed outcome that the capstone will test;
  do not assume either rejection is wrong merely because source loading works.
- Estimated run cost: **$0.00393180**, 15,211 reported tokens. The failed connection
  reported zero usage and retained **$0.00135810** as unknown-usage allowance.
  Updated accounted total: **$0.13643805 of $1**, including all reserved allowance.

Reports: `evals/reports/2026-09-26-evidence-flow-robotics-connected/` and the
earlier failed connection in `evals/reports/2026-09-26-evidence-flow-robotics/`.
No further paid domain or parallel reruns were started after this result.

The subsequent gate-policy change defines evidence sufficiency around essential
MVP dependencies and time scope around supported deadline conflicts. Evidence-only
failures can now be kept by a user with recorded caveats, without becoming automatic
finalists. Timing caveats are retained in proposal unknowns. All 166 offline tests
pass, including review interactions; these prompt changes have not had a paid
rerun and do not change the historical results above.

Model: `gpt-4o-mini`. Sources: existing synthetic frozen development fixtures.
Each case was attempted once per scheduling mode, before and after the
duplicate-source fix. Requests, source snapshots, prompts, and per-run limits
were unchanged within each comparison. Model answers were generated independently.

## Findings after the duplicate-source fix

### Updated gate-policy run (before candidate batching)

The sequential gate-policy suite cost $0.02144565 (82,617 reported tokens).
Robotics generated twelve candidates and one proposal; two candidate judgments
were skipped for invalid citations. Accessibility stopped on an incomplete
candidate-generation response; medicine was skipped by the suite after that error.
Report: `evals/reports/2026-09-26-gate-policy-sequential/`.

The robotics proposal passed structural reference checks, but assistant inspection
found unsupported content: it required historical yield data absent from the
fixtures and cited a generic crop-image dataset description as support for demand
for yield forecasting. This is a semantic support failure, not successful quality
validation. Human scoring remains pending. A valid source/chunk ID alone does not
establish that the cited passage supports a claim.

Candidate generation was subsequently bounded to small responses, preserving
earlier validated batches when a later output is malformed. All 171 offline tests
pass. A follow-up sequential run is in progress. The requested proposal count is
under review as a target: available valid proposals should remain usable even
when fewer than requested, without synthetic padding in user-facing results.

| Case | Mode | Seconds | Estimated USD | Result |
| --- | --- | ---: | ---: | --- |
| Robotics | Sequential | 28.722 | 0.00258420 | Invalid candidate field name |
| Robotics | Parallel | 8.518 | 0.00109680 | Planned query exceeded result limit |
| Accessibility | Sequential | 19.999 | 0.00196350 | Insufficient coverage: 2 sources, minimum 3 |
| Accessibility | Parallel | 24.420 | 0.00312210 | Insufficient coverage: 2 sources, minimum 3 |
| Medicine | Sequential | 39.830 | 0.00305040 | Insufficient coverage: 2 sources, minimum 3 |
| Medicine | Parallel | 21.616 | 0.00237660 | Insufficient coverage: 2 sources, minimum 3 |

No final proposals were produced, so usefulness, feasibility, and other human
quality scores remain unmeasured. Failed runs end at different points; these
times do not establish a speed advantage for either mode. The deterministic
mode-equivalence tests use identical model responses; this live comparison does
not control model randomness. Candidate counts also varied across modes.

## Defects found and fixed

The initial six attempts failed because Scout/Library compared entire source
receipts. Repeated searches return a different query ID for the same content.
Both workers now ignore query/capture metadata when comparing repeat records,
while checking content and full text. A regression test verifies deduplication
and rejection of genuinely changed content in both workers.

The second comparison exposed floating-point dust in reserved-cost accounting
after parallel settlements. Counters now clamp negative remainders to zero and
clear reserved cost when no tokens remain reserved. This was verified offline;
the original reports retain the measured values.

## Spending and reproduction

Each invocation had a $0.15 estimated cost cap, a 100,000-token application
limit, and a 300-second application deadline. SDK and application retries were
disabled. Pricing: $0.15 input / $0.60 output per million tokens.

- Twelve end-to-end attempts: $0.01768440 reported cost.
- Earlier nine-case Critic baseline: $0.00450315 reported cost.
- Combined reported cost: **$0.02218755**.
- Unresolved usage reserved for canceled baseline calls: **$0.00406305**.
- Reported plus reserved allowance: **$0.02625060**, within the approved $1.

Local detailed reports are under `evals/reports/2026-09-26-baseline-*` and
`evals/reports/2026-09-26-dedup-fixed-*`. They contain input/prompt fingerprints,
outputs, checks, failures, and usage. These generated reports are ignored by Git.

Example invocation (incurs additional charges):

```sh
python -m evals.end_to_end --case robotics-agriculture-01 --mode sequential --model gpt-4o-mini --max-cost-usd 0.15 --input-rate 0.15 --output-rate 0.60
```

## Remaining work

1. Clarify essential feasibility evidence versus benefits proposed for testing;
   inspect exact candidate claims and retrieved passages before changing gates.
2. Address the candidate shortfall using bounded recovery and evidence-backed
   scope changes; do not fill the requested count with unsupported duplicates.
3. Repeat both modes on the same revised fixtures and limits, then review the
   generated proposals using the human rubric. Keep this failure baseline.
# Current status — 27 September 2026

The latest sequential run finished all three frozen cases but produced a proposal
only for robotics (one caveated proposal); accessibility and medicine returned
none. It used gpt-4o-mini, 146,047 model tokens, an estimated $0.038156, and
303.18 seconds for the suite. This does not meet the three-domain quality-review
goal. The final statement verifier and narrative-caveat policy were changed after
this run. Earlier parallel reports used different code and cannot be compared as
a controlled scheduling comparison. See [the reliability report](reliability-2026-09-27.md).
