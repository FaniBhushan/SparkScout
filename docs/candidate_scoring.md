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
`delivery_risk` uses a high score for *low* risk. Ranking is descending weighted
score, with candidate ID breaking ties. The UI displays the top requested number
(default two) even when a gate fails, and shows each failed gate's rationale.
A failed gate still prevents a detailed, verified proposal. A score finalist is
a comparison choice; feasibility and evidence may still require review.
Remaining ideas have compact scorecards and an explicit rank-cutoff explanation.

## Evidence and timing gates

`evidence_sufficiency` checks support for essential MVP dependencies: suitable
data, usable methods/tools, and required resources. Expected benefits, such as
better crop yields, may be explicitly unproven hypotheses. Missing proof of a
future benefit alone does not fail this gate. Essential data that is missing or
not permitted must also fail `data_access`.

`time_scope` fails for a supported, unavoidable conflict with the user's deadline,
such as a required six-month experiment in a 30-day project. An uncertain effort
estimate is a caveat and may lower feasibility/delivery-risk scores; it is not
proof of a deadline conflict. These semantic judgments are made by Critic, not
deterministic duration arithmetic. A passing time gate never guarantees delivery.
Critic uncertainty is carried into proposal `unknowns` and shown in the UI.

## User review

When only `evidence_sufficiency` fails and all other configured gates pass, the UI
shows the idea under **Candidates needing review**. The user acknowledges the
caveats and chooses **Keep this idea despite the evidence gap**, or declines it.
Other failures, including a known deadline conflict or unavailable data, cannot
be overridden through this control.

`src/evaluation/review.py` records the decision without model calls. The original
gate result, ranking, automatic finalists, and run status remain intact. Acceptance
selects an idea for the user's consideration; it does not generate a final proposal
or count as a successful automatic recommendation. `review_decisions` retains
decision history, caveats, timestamps, and a fingerprint of the exact candidate
and assessment. The last decision for a candidate is the current choice.

Decisions live in the current UI session and its downloadable run JSON; they are
not written back to research checkpoints. A new run needs a new acknowledgement.
The model contract rejects decisions attached to a different run, changed
assessment, or ineligible candidate. The CLI exports the same assessment data;
interactive acceptance is currently provided by the UI.

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
