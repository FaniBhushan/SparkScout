# Controlled evaluation — 27 September 2026

For the deadline implementation, selection replay, and consolidated submission
metrics, see [the demo submission report](demo_submission_2026-09-27.md).

This is the earlier baseline. See [the recovery evaluation](recovery_review_2026-09-27.md)
for subsequent live, controlled, and blind-quality results.

## Setup

Both runs used the same three frozen cases, identical input fingerprints and
prepared-configuration checksums, `gpt-4o-mini`, $0.15/$0.60 per-million input
and output rates, and a $0.20 suite estimate cap. Only the scheduling mode
changed. Frozen fixture evidence is synthetic. Reports, source details, proposals,
and traces are retained locally under ignored `evals/reports/` and `runs/` paths.

## Pipeline comparison

| Measure | Sequential | Parallel |
| --- | ---: | ---: |
| Cases with structural checks passed | 1/3 | 1/3 |
| Proposals returned / requested | 1/9 | 2/9 |
| Cases meeting proposal target | 0/3 | 0/3 |
| Required source-type coverage | 3/3 cases | 3/3 cases |
| Citation integrity | 1 passed; 2 not evaluated | 1 passed; 2 not evaluated |
| Hard-gate checks | 79 pass / 26 fail | 82 pass / 8 fail |
| Suite elapsed time | 376.0 s | 353.6 s |
| Model tokens | 181,291 | 172,152 |
| Estimated model cost | $0.046652 | $0.044859 |

The parallel run returned two proposals, both from robotics; sequential returned
one medicine proposal. Accessibility produced none in either run. The three
proposal reviews therefore are not the same output set. Raw hard-gate counts also
reflect different candidate volumes and must not be read as a mode-quality win.
Citation integrity was checked only where proposals existed; two unevaluated cases
are not passes. These are single stochastic runs, so the small time/cost
differences do not establish that either mode is generally faster, cheaper, or
better.

## Blind LLM judge

`gpt-4o-mini` reviewed the three saved proposals, blind to mode and prior Critic
judgments. It rated the sequential medicine proposal and two parallel robotics
proposals separately. Mean scores were usefulness 3.00, specificity 3.00,
evidence sufficiency 2.00, feasibility 3.33, and actionability 3.00 (n=3). By
mode, the sequential proposal scored 3/3/2/2/3 and the parallel proposals averaged
3/3/2/4/3 on those dimensions. This is only descriptive because each mode yielded
different proposals and sample sizes are one versus two. The judge flagged weak
or unverified supporting evidence across all three. These model scores are not
human ratings or ground truth.

Human ratings are pending. Fill both per-proposal sheets independently using
their adjacent `human_rubric.json` files:

- `evals/reports/2026-09-27-controlled-sequential/human_scores.csv`
- `evals/reports/2026-09-27-controlled-parallel/human_scores.csv`

Then calculate agreement and disagreements with:

```sh
.venv/bin/python -m evals.analysis.metrics \
  --report evals/reports/2026-09-27-controlled-sequential/results.json \
  --report evals/reports/2026-09-27-controlled-parallel/results.json \
  --quality-report evals/reports/2026-09-27-controlled-quality-resumed.json \
  --human-scores evals/reports/2026-09-27-controlled-sequential/human_scores.csv \
  --human-scores evals/reports/2026-09-27-controlled-parallel/human_scores.csv \
  --output evals/reports/NEW_METRICS_DIRECTORY
```

## Live `web_article` attempt

The credentials were present and preflight resolved Tavily plus GitHub, requiring
`web_article`. A separate Tavily smoke query returned three live web-article
records. The full live run then failed before proposal generation: repeated
results for one canonical URL had different query-dependent snippets. The first
fix handled Scout/Library deduplication, but the single allowed end-to-end retry
then exposed a conflicting record at the Scout/Library join for the same
Tavily-backed source. The join now uses provider, source type, and canonical URL
as Tavily identity; offline regression tests cover varying titles/snippets. There
was no further paid live retry, so the full live path remains unverified.

Traces for the failed attempts:

- `runs/fb011b716d154c65a3ff4699adbfb144/trace.jsonl` — Scout duplicate conflict.
- `runs/380a1a12678a4b3d8b9ffac481d232c2/trace.jsonl` — join conflict after
  retrieval and candidate generation; no completed proposal report was produced.

Together, the two live attempts reported about $0.002982 in OpenAI model usage;
provider search charges are not included in that estimate. Because the live case
did not complete, it has no live proposals or citations to present. Follow the
honest demo contingency in `evals/deadline_demo_fallback.md`: show reproducible
frozen evaluation results, label fixture evidence synthetic, and document any
domain with no proposals.

## Reproduction

```sh
.venv/bin/python -m evals.end_to_end --model gpt-4o-mini --mode sequential --output evals/reports/NEW_SEQ --max-cost-usd 0.2 --input-rate 0.15 --output-rate 0.60
.venv/bin/python -m evals.end_to_end --model gpt-4o-mini --mode parallel --output evals/reports/NEW_PAR --max-cost-usd 0.2 --input-rate 0.15 --output-rate 0.60
.venv/bin/python -m evals.analysis.quality --report evals/reports/NEW_SEQ/results.json --report evals/reports/NEW_PAR/results.json --output evals/reports/NEW_QUALITY.json --model gpt-4o-mini --max-cost-usd 0.05 --input-rate 0.15 --output-rate 0.60
```

Each output path must be new. These commands make paid model calls; frozen
fixtures avoid Tavily/GitHub search calls.
