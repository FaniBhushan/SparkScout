# End-to-end quality review — 27 September 2026

## Scope and result

The blind `gpt-4o-mini` judge reviewed the three proposals in the saved
`2026-09-27-final-sequential` run. The request, proposal, and captured evidence
were shown to the judge; prior Critic scores, ranks, verifier decisions, and
scheduling mode were withheld. Proposal prompt hashes, source-report hashes,
rubric hash, model usage, and estimated cost are retained in the ignored JSON
reports under `evals/reports/`.

| Dimension | Mean (1–5) | Proposals |
| --- | ---: | ---: |
| Usefulness | 5.00 | 3 |
| Specificity | 4.33 | 3 |
| Evidence sufficiency | 3.67 | 3 |
| Feasibility | 3.33 | 3 |
| Actionability | 4.67 | 3 |

The overall run returned 3 of 9 requested proposals across the three cases; the
robotics case returned none. These judge scores describe only the three returned
proposals and do not turn missing output into a quality pass. The fixtures are
synthetic, the sample is very small, and an LLM judge is not ground truth. Human
ratings and model-human agreement are still pending.

Pipeline metrics for the same run: required source-type coverage 100%; citation
integrity passed in two cases and was not evaluable in the zero-proposal case;
55 hard-gate checks passed and 15 failed; sequential runtime was 262.826 seconds;
reported pipeline usage was 144,116 tokens and an estimated $0.03618345. The judge
used 8,442 tokens and an estimated $0.00171135 across the initial review and one
resumed review. These are application estimates, not provider billing records.
The report has no comparable live parallel run using the same final code and
limits, so no sequential-versus-parallel quality or latency claim is made.

## Human review

Fill `evals/reports/2026-09-27-final-sequential/human_scores.csv` independently.
Score each proposal from 1 to 5 using its adjacent `human_rubric.json`; add a
reviewer ID and notes. Do not copy the model's scores. Once completed, compare:

```sh
.venv/bin/python -m evals.analysis.metrics \
  --report evals/reports/2026-09-27-final-sequential/results.json \
  --quality-report evals/reports/2026-09-27-quality-final-sequential-network.json \
  --quality-report evals/reports/2026-09-27-quality-final-sequential-complete.json \
  --quality-report evals/reports/2026-09-27-quality-final-sequential-hashed.json \
  --human-scores evals/reports/2026-09-27-final-sequential/human_scores.csv \
  --output evals/reports/NEW_METRICS_DIRECTORY
```

The analysis reports exact agreement, mean absolute difference, and each
disagreement by dimension. Use a new output directory for each report.

## Reproduction

The completed judge output can be reproduced from the saved end-to-end report
without repeating research. The example makes paid judge calls and uses a $0.05
application estimate cap:

```sh
.venv/bin/python -m evals.analysis.quality \
  --report evals/reports/2026-09-27-final-sequential/results.json \
  --output evals/reports/NEW_QUALITY_REPORT.json \
  --model gpt-4o-mini --max-cost-usd 0.05 \
  --input-rate 0.15 --output-rate 0.60
```

If a review is interrupted, pass `--resume-from PRIOR_QUALITY_REPORT.json` and
choose a new `--output`; valid prior reviews are reused and only missing or
invalid entries need another call. The cap applies to each invocation.
