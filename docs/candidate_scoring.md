# Candidate scoring

`config/rubric.json` defines the initial ten candidate criteria, five hard gates,
four weight presets, and retrieval limits. These are starting defaults, not course
requirements. Edit the criterion definitions and every preset together when adding
or removing a criterion. Preset weights must total 100. A criterion may have weight
zero; hard gates still apply.

`real_world_pain_point` asks whether identifiable people actually face a recurring,
costly difficulty today. `problem_value` asks how valuable solving that problem
would be. A plausible benefit alone is not proof of a real pain point.

Simple configuration selects a preset with
`load_evaluation_configuration("feasibility-first")`. Advanced configuration passes
all criterion weights as `weights={...}`; partial maps and totals other than 100
are rejected. The scoring formula is `score / 5 * weight`, summed to a 0–100 total.
`delivery_risk` uses a high score for *low* risk. A failed hard gate disqualifies a
candidate even if its numeric score is high; final ranking belongs to the
orchestrator.

Library searches independently from Scout. Live GitHub/Tavily results provide
metadata and short snippets; confirmed user uploads can provide extracted text.
The run-scoped hybrid index splits available text under configured limits.
Critic retrieves per criterion, bounds the combined context, asks an injected
judge for 0–5 judgments, and computes weighted totals deterministically. It
rejects citations outside the retrieved context. The local TF-IDF vectors are
deterministic and cost no embedding API tokens, but do not provide semantic
sentence-embedding retrieval.

`evals/rubrics/proposal_quality.json` is separate: it guides evaluation of the
*final proposal*, not candidate ranking. Run focused checks with
`python -m unittest discover -s tests -v`.
