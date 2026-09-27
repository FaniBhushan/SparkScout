# Recovery implementation and evaluation — 27 September 2026

## Outcome

The live AI-engineering run completed with one proposal. The sequential frozen
suite returned one proposal in each of three domains; the parallel suite returned
none. Ranked backfilling and one bounded replacement round are implemented, but
the requirement to always return a valid proposal is **not met**. No rubric or
hard gate was relaxed for these runs. The existing narrative-hypothesis demo
policy remained enabled, so accepted proposals can contain explicitly marked
caveats and still require review.

## Implemented changes

- Use the aligned 600-second limit in the live request, preserving its configured
  100,000-token and $1 estimated model-cost limits.
- Try remaining gate-passing candidates in rank order when a draft fails. Keep
  successful proposals and recorded failures.
- For an empty result, reuse evidence and attempt one recovery round: at most
  two searches from remaining allowance and three distinct replacement ideas.
  Replacements pass Critic and proposal verification normally.
- Preserve prior judgments in `recovery_history` and checkpoint recovery stages
  separately. Resume tests confirm no repeated model calls for completed work.
- Preserve requested counts in failed/skipped evaluation rows. Include earlier
  recovery judgments in gate metrics, without double-counting retained judgments.

## Live result

Request: AI engineering, RAG evaluation, two intermediate developers, 30 days,
six candidate ideas requested, one proposal requested, mandatory `web_article`.

The run returned **Improving RAG Context Relevance Through User Queries** in
83.11 seconds. It retained 15 source records, used 47,894 model tokens and four
Tavily plus four GitHub calls. Estimated model cost: **$0.0112944**. Source joining
completed successfully; one draft correction was needed. Problem, benefit, and
differentiation statements carry explicit caveats.

Citation IDs point to captured excerpts from Evidently AI and Confident AI RAG
evaluation articles. Structural citation integrity does not establish factual
sufficiency: manual inspection found weak reasoning for the availability of query
logs. The verifier inferred availability from a description of evaluation metrics.
This remains a quality risk; the live result is not independently validated.

A preceding sandboxed attempt failed to connect before discovery. Its report and
unknown-usage reservation were preserved. The completed network-enabled run is
separate; no claim is made that unknown provider usage was zero.

## Controlled comparison

Same three frozen cases, input fingerprints, configuration checksums, prompt
hashes, `gpt-4o-mini`, and $0.15/$0.60 per-million input/output accounting rates.
Evidence is **synthetic**. Per-run limits were 600 seconds and 100,000 tokens;
each suite allowed 900 execution seconds, 300,000 tokens, and $0.20 model cost.

| Measure | Sequential | Parallel |
| --- | ---: | ---: |
| Robotics proposals / requested | 1 / 3 | 0 / 3 |
| Accessibility proposals / requested | 1 / 3 | 0 / 3 |
| Medicine proposals / requested | 1 / 3 | 0 / 3 |
| Structural case checks passed | 3 / 3 | 0 / 3 |
| Citation integrity | 3 passed | 3 not evaluated |
| Case execution time, summed | 426.49 s | 509.46 s |
| Reported model tokens | 210,527 | 262,306 |
| Estimated model cost | $0.054263 | $0.067532 |

Neither mode met the full nine-proposal target. The earlier baseline returned
1/9 sequential and 2/9 parallel; these are single stochastic runs with different
outputs, not an ablation proving a causal quality or speed improvement.

Parallel robotics exhausted its initial pool and three replacements: verification
rejected unsupported citations, data dependencies, or implementation claims.
Accessibility stopped at 86,084 reported tokens when the next conservative
reservation would exceed 100,000. The suite then skipped medicine. Medicine was
executed separately under the remaining suite allowance and stopped similarly
at 88,496 reported tokens. The combined report replaces only the skipped row,
retains the original failures, and links both unchanged execution reports. Its
combined usage remains below all original suite limits. Scheduling mode alone
cannot explain the differences because model outputs and attempted work differed.

Parallel source-coverage and gate totals in the generated metrics cover only the
returned robotics result. Accessibility and medicine aborted before exporting a
result; their intermediate judgments remain in checkpoints. Their absent final
metrics must not be interpreted as evidence that source collection failed or as
passed checks. Citation checks are not evaluated for all three empty outputs.

The token reservation uses UTF-8 byte counts plus the full output allowance.
Budget allocation between assessment, drafting, and recovery remains an open
improvement. Larger dollar/time caps alone would not resolve this token limit.

## Blind LLM judge

Saved proposals were graded with rank, Critic scores, and mode hidden. No research
was rerun for judging. Frozen and live reviews were executed and reported separately.

| Dimension, 1–5 | Frozen sequential mean, n=3 | Live, n=1 |
| --- | ---: | ---: |
| Usefulness | 3.33 | 3 |
| Specificity | 3.00 | 2 |
| Evidence sufficiency | 3.00 | 3 |
| Feasibility | 3.33 | 4 |
| Actionability | 3.33 | 3 |

Parallel has no proposals to score. The judge flagged unverified assumptions,
weak differentiation, missing resources, and insufficiently actionable risk
mitigation. These model scores are not human ratings or ground truth. Human
ratings and model/human agreement remain pending.

Judging cost $0.00134385 for frozen proposals and $0.0005886 for the live proposal.
Total reported model cost for completed executions and reviews in this round:
**$0.1350216**. Search-provider charges and unknown usage from the connection
failure are excluded; these are application estimates, not provider invoices.

## Artifacts and reproduction

Final offline validation: 208 tests passed, the evaluation dataset is structurally
valid, and `git diff --check` passed. No paid calls are made by these checks.

Local ignored artifacts:

- `evals/reports/2026-09-27-recovery-live-network/results.json`
- `evals/reports/2026-09-27-recovery-sequential/results.json`
- `evals/reports/2026-09-27-recovery-parallel-final/results.json`
- `evals/reports/2026-09-27-recovery-metrics/summary.md`
- `evals/reports/2026-09-27-recovery-quality.json`
- `evals/reports/2026-09-27-recovery-live-quality.json`
- `runs/236c2e10f93c4c7bac74e3f30fa4a404/trace.jsonl`

Each controlled report directory includes a blank human-review sheet. The
parallel sheet has no proposal rows. Use a new output directory for another run:

```sh
python -m evals.live.live_demo --config evals/live_requests/ai_engineering_web_article.json --output evals/reports/NEW_LIVE --model gpt-4o-mini --input-rate 0.15 --output-rate 0.60
python -m evals.end_to_end --model gpt-4o-mini --mode sequential --max-cost-usd 0.20 --input-rate 0.15 --output-rate 0.60 --output evals/reports/NEW_SEQUENTIAL
python -m evals.end_to_end --model gpt-4o-mini --mode parallel --max-cost-usd 0.20 --input-rate 0.15 --output-rate 0.60 --output evals/reports/NEW_PARALLEL
```

For the demo, the saved live example and the sequential domain examples are
available. Label synthetic fixtures, disclose caveats, and show the parallel
failures alongside the successful outputs. Human review remains required.
