# Input and output guardrails

The shared checks in `src/guardrails.py` are deterministic and add no model
calls. They supplement the existing contracts, preflight policy checks,
budgets, citation-ID validation, and code-calculated scoring.

## Warn versus block

| Input or output | Behavior |
| --- | --- |
| Prompt over 4,000 characters | Warn about increased model cost and delay; preserve and accept the full prompt. |
| Combined submitted text over 12,000 characters | Same advisory; not a new hard request-size limit. |
| Domain or one interest over 200 characters | Reject with a field validation error. |
| Resource, exclusion, or constraint entry over 1,000 characters | Reject; keep structured fields concise. |
| More than 20 entries in a request list | Reject. |
| Recognizable credential/private key | Block before model calls or result display/export; do not show the detected value. |
| Possible email address or international phone number | Warn; do not block or silently alter the content. |

Warnings appear before drafting in Streamlit, in the reviewed preview, and on
stderr for CLI/model callers. JSON stdout stays machine-readable. Draft and run
records retain advisories. A size warning does not override configured time,
token, or cost budgets, nor a provider's context limit. Prompt drafting remains
a separate bounded-output call outside the research run's token budget.

## Privacy boundaries

Uploaded text is scanned after extraction, including text beyond the preview
snippet. Model inputs and decoded JSON outputs are scanned at `call_prompt`.
The application checks the complete exportable result, and the result view
checks again before displaying or offering a download. Rejected input values
are omitted from UI/CLI validation errors. Trace events retain metadata/usage,
not matched text.

Upload source snippets and chunk text are still redacted in exported results.
Generated summaries can contain private information: warnings are not a privacy
guarantee. Patterns cover common token prefixes, private-key headers, long
credential assignments, email addresses, and international phone numbers. They
can miss obfuscated secrets, names, addresses, medical details, and confidential
business text, or flag harmless examples. Remove sensitive content yourself;
there is no bypass for a detected credential in this MVP.

## Prompt injection and evidence

Every rendered prompt now includes a trust-boundary instruction and delimited
JSON inputs. The OpenAI client sends only that fixed, code-owned rule block
through the higher-priority `instructions` parameter; user and source content
remain in `input`. Its text is already included in the run's token reservation.
This uses the API's documented
[instruction hierarchy](https://developers.openai.com/api/docs/guides/text#message-roles-and-instruction-following).
Angle brackets in input values are escaped so source text cannot
close a data block. Provider permissions, budgets, weights, and final ranking
remain controlled by code. Tests simulate invalid provider choices, score
overrides, delimiter attacks, and secret outputs. They verify code boundaries,
not that a real model always resists malicious text or scores accurately.

Critic and proposal prompts require uncertainty or omission for unsupported
claims. Citation-ID checks do not independently verify meaning. The nine
synthetic cases in `evals/guardrails/claim_support.json` cover supported,
unsupported, and contradictory claims, including malicious evidence. Run:

```sh
python -m evals.claim_support --validate-only
python -m unittest tests.test_guardrails tests.test_claim_support_eval -v
```

See [the evaluation guide](../evals/README.md#claim-support-component-evaluation)
for scoring saved judgments or explicitly running paid Critic calls. Review
the starter labels and run real-model evaluations before claiming model safety
or adopting an extra runtime verifier.
