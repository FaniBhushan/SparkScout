# ScoutSpark demo recording guide

Target length: 2–3 minutes. Use the saved reports and current UI; do not show
`.env`, API keys, or unrelated terminal output.

1. **What it does (15 s):** explain that ScoutSpark turns a capstone request into
   sourced project proposals and evaluates them with a fixed rubric.
2. **User setup (30 s):** show the AI Engineering request, preview configuration,
   and the required `web_article` source setting. Explain preview as a chance to
   confirm scope, sources, rubric, and budget before paid work starts.
3. **Results (45 s):** run Offline demo and label its sources and model responses
   synthetic. Show the two expanded finalist scorecards and three compact cards,
   criterion weights, reasons for the rank cutoff, and available citations.
   Explain that a failed gate stays visible and may withhold a detailed draft.
4. **Evaluation (30 s):** show the quantitative comparison and blind LLM-judge
   scores. Explain that only three proposals were reviewed and scores are not
   ground truth. If human sheets have not been filled, say human agreement is
   pending; do not imply model scores are human scores.
5. **Limitations and next work (20 s):** the real-model baseline returned 1/9 and
   2/9 detailed proposals. Later live attempts exposed missing task data and
   verifier mistakes. Scorecard visibility does not resolve these quality gaps.
   Dynamic criteria and user-triggered feedback rounds remain future work.

Suggested screen sources:

- UI: request/configuration preview.
- `evals/demo_submission_2026-09-27.md`: current functional checks, saved-score
  replay, quantitative baseline, blind-judge means, and sample limitations.
- `evals/reports/2026-09-27-demo-submission-metrics/summary.md`: generated metrics.
- `runs/380a1a12678a4b3d8b9ffac481d232c2/trace.jsonl`: the failed live run's
  stages and budgets; it contains no proposal result.

Replace the human-review sentence and refresh the metrics after independent human
scores are entered. Do not describe the failed live end-to-end attempt as a
successful live research demo.
