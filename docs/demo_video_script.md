# ScoutSpark demo video script

Target: 3 minutes 30 seconds. Hard stop: 4 minutes.

## Before recording

- Select **Offline demo** and keep the synthetic-data notice visible.
- Pre-run the demo. Do not include a research wait or another run in the recording.
- Follow the screen path below; do not explore extra controls or expand every card.
- Keep the evaluation figures in the design document; do not narrate them.
- Keep each screen on display only long enough to make the named detail legible.
- Hide terminals, `.env` files, notifications, email, and unrelated tabs.

## 0:00–0:35 — Introduction and motivation

**Screen:** Show the ScoutSpark title, then move to the request form.

**Narration:**

"Hi everyone, I'm Fani Bhushan. I had several capstone ideas but wasn't
convinced, and little time to research them. I built a single-agent research
assistant; its early runs looked promising. I realized other students face the
same bottleneck. That led me to ScoutSpark: helping students find evidence-based
project ideas that fit real constraints."

## 0:35–1:25 — Configuration

**Screen:** Show the request fields, then the resolved preview. Point to sources,
content types, scoring priority or weights, and run limits. Avoid opening every
advanced control.

**Narration:**

"Configuration is one of ScoutSpark's founding pillars. Before research, the
student reviews the request, sources, content types, rubric, and budget. Simple
settings are approachable; advanced settings add control. Preview resolves and
validates the plan before external calls. Code enforces budgets, weights, and
hard gates. This is the synthetic offline demo, not live research."

## 1:25–1:55 — How it works

**Screen:** Show the architecture diagram. Trace the Scout and Library branches
briefly, then the Critic and finalization.

**Narration:**

"Scout proposes ideas; Library independently gathers evidence. The coordinator
joins their work, and a temporary index supplies passages to Critic. Code applies
the rubric and hard gates. A writer and verifier produce cited proposals when
the evidence supports them."

## 1:55–2:40 — Results

**Screen:** Show the two expanded scorecards, one failed gate, one citation, and
the remaining compact cards. Do not read every criterion aloud.

**Narration:**

"The top two scorecards expand while the other ideas remain visible. Inspect the
criteria, evidence, citations, and gate reasons. A high rank does not override a
failed gate; a detailed proposal may be withheld. This helps students compare
ideas while seeing uncertainty."

## 2:40–2:55 — Evaluation

**Screen:** Show the evaluation heading and link in the design document; do not
walk through its tables.

**Narration:**

"The design document contains the full evaluation and caveats. Independent
human review is still pending."

## 2:55–3:15 — Close

**Screen:** Return to the results, then finish on the ScoutSpark title.

**Narration:**

"Verified-proposal quality remains an open challenge. ScoutSpark makes the
configuration, evidence, and failure reasons easy to inspect. Thanks for
watching."

## Recording guardrails

Keep the interface path to the prepared preview, architecture diagram, two
scorecards, one gate, one citation, and the evaluation-document heading. Do not
start a live run or explain every setting. If the recording reaches 3:30, go
directly to the closing screen. Do not remove the synthetic-data disclosure or
imply that the pending human review is complete.
