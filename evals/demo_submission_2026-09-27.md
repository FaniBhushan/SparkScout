# Demo submission evaluation — 27 September 2026

## Updated demo behavior

Default: five candidate ideas, two displayed finalists, configurable by the user.
Score selection uses weighted totals and candidate-ID tie breaking. Failed gates
remain visible with reasons. Detailed proposals require passed gates and evidence
verification; a visible finalist scorecard does not establish proposal validity.

223 offline tests pass. The default Streamlit test confirms five scored ideas,
two score finalists, and three remaining scorecards. Tests cover a failed-gate
score leader, configurable finalist count, serialization, and matching scheduling
modes. The deterministic offline pipeline passes 3/3 domain cases and returns
9/9 requested detailed proposals. Its responses and token counts are simulated;
these results measure software behavior, not research quality.

## Saved-assessment replay of the new selection rule

Replayed the six controlled real-model case outputs with a display target of two:

| Measure | Result |
| --- | ---: |
| Cases supplying two score finalists | 6/6 |
| Score finalists displayed | 12/12 |
| Selected ideas with failed gates | 4/12 |
| New model/search calls | 0 |

This reuses historical scores without repeating research or drafting. It does
not imply twelve verified proposals. Source report hashes and selected IDs are
in `reports/2026-09-27-demo-selection.json`.

## Real-model pipeline baseline

These controlled runs predate the display change. Both use the same three frozen
cases and limits, with synthetic source evidence and real `gpt-4o-mini` calls.

| Metric | Sequential | Parallel |
| --- | ---: | ---: |
| Detailed proposals returned / requested | 1/9 (11.1%) | 2/9 (22.2%) |
| Cases meeting requested proposal count | 0/3 | 0/3 |
| Required source-type coverage | 100% | 100% |
| Citation integrity, passed / not evaluated | 1 / 2 cases | 1 / 2 cases |
| Hard-gate checks, passed / failed | 79 / 26 | 82 / 8 |
| Total case latency | 376.018 s | 353.609 s |
| Reported model tokens | 181,291 | 172,152 |
| Estimated model cost | $0.0466521 | $0.0448587 |

Accessibility returned no detailed proposal in either run. Different outputs and
small samples prevent a general speed or quality comparison. Historical later
attempts, including live-search limitations, are retained in
[the recovery review](recovery_review_2026-09-27.md) and
[the four-issue review](four_issue_review_2026-09-27.md).

## Blind LLM judge

The independent evaluation step hid Critic scores, rank, and scheduling mode.
All three available controlled proposals were reviewed; no review errors remain.

| Quality dimension | Mean / 5 | Sample size |
| --- | ---: | ---: |
| Usefulness | 3.00 | 3 |
| Specificity | 3.00 | 3 |
| Evidence sufficiency | 2.00 | 3 |
| Feasibility | 3.33 | 3 |
| Actionability | 3.00 | 3 |

Judge usage across the original and resumed calls: 8,468 tokens; estimated
$0.0017661. Model judgments are imperfect. Missing proposals are excluded from
quality means and explicitly counted in the low pipeline yield above.

Human ratings: **pending**, zero completed controlled proposal rows. No human
agreement metric can be calculated yet. Review sheets are beside each controlled
`results.json`; see [the controlled report](controlled_evaluation_2026-09-27.md).

## Reproduction and artifacts

All commands below are local/offline. Choose new output paths on repeat runs.

```sh
python -m unittest discover -s tests -q
python -m evals.validation.validate
python -m evals.end_to_end --offline-demo --mode sequential --output evals/reports/NEW_OFFLINE
python -m evals.analysis.score_selection --report evals/reports/2026-09-27-controlled-sequential/results.json --report evals/reports/2026-09-27-controlled-parallel/results.json --output evals/reports/NEW_SELECTION.json
python -m evals.analysis.metrics --report evals/reports/2026-09-27-controlled-sequential/results.json --report evals/reports/2026-09-27-controlled-parallel/results.json --quality-report evals/reports/2026-09-27-controlled-quality.json --quality-report evals/reports/2026-09-27-controlled-quality-resumed.json --output evals/reports/NEW_METRICS
```

Current local artifacts: `reports/2026-09-27-demo-offline-sequential/`,
`reports/2026-09-27-demo-selection.json`, and
`reports/2026-09-27-demo-submission-metrics/`. Raw reports are gitignored; this
summary is intended for submission. No paid experiments were added for this slice.
