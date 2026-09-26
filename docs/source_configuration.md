# Source configuration

`config/sources.json` is the operator-owned registry: source types describe the
kind and evidence tier of a record; providers describe adapters, their supported
types, capabilities, domains, credentials, timeouts, and request limits. The
implemented GitHub, Tavily, optional user-upload, and frozen-fixture adapters are enabled;
OpenAlex, arXiv, and PubMed stay disabled until their adapters are implemented.
Routes can map a domain to approved providers and source types.

For a local run, use the registry builder or supply your own ready adapters:

```python
from src.adapters import build_available_adapters

adapters = build_available_adapters(include_live=True)
```

Set `TAVILY_API_KEY` for Tavily. GitHub public repository search works without a
token; setting `GITHUB_TOKEN` is optional and gives authenticated requests a higher
rate limit. GitHub captures repository metadata and its short description, not the
README contents. Tavily returns the title and URL, plus a short snippet only when
`page_snippet` is requested. Both adapters use per-request timeouts and avoid raw
page contents.

User uploads are a separate, opt-in provider. The UI accepts up to five UTF-8
text/Markdown or text-based PDF files only after an explicit rights confirmation;
the CLI requires `--upload` and `--confirm-upload-rights`. The confirmation is
an attestation, not independent license verification. The parser limits each
file to 2 MB and 20,000 extracted characters; the hard PDF limit is 20 pages.
Preflight checks the reviewed filenames, SHA-256 hashes, declared language, raw
byte total, and aggregate PDF page limit before model calls. Image-only PDFs
need OCR elsewhere and are rejected. No upload bytes are copied into the repo.
The run uses extracted text in memory for retrieval and model context. Returned
and downloadable result JSON retains upload receipts and citation IDs, but
redacts stored upload snippets and chunk text. Generated proposal text may still
summarize or quote an upload, so keep results private when needed. The app does
not verify that an attested upload is licensed for this use.

`config/search_defaults.json` contains the starter `balanced`, `academic`, and
`build-oriented` search presets. They cap query count, results per query, and total
records. These limits prevent broad requests from generating unbounded provider
calls, latency, or downstream model context. Hard limits are ceilings: a user can
choose a smaller budget, but cannot raise it past the configured maximum.

The Critic has a separate context-token ceiling in `config/rubric.json`. It limits
how much retrieved evidence is sent to the evaluation model. Provider request and
timeout limits live with each provider in `sources.json`. `config/budgets.json`
sets run-wide time/token/normalized-source-byte/PDF-page defaults and operator ceilings;
provider `max_requests_per_run` is shared by both workers. An optional estimated-cost
cap requires trusted model rates. The worker source/query caps,
per-type record caps, source-age limits, and Critic context cap are enforced.
Record caps currently apply independently to Scout and Library, not to the
merged manifest. The shared application function resolves the preset before
either worker runs.

For a reviewed configuration, construct `SubmittedRunConfiguration` and call
`prepare_run(submitted, adapters)` before research. Its `PreparedRun` contains
the effective request, approved providers and content types, rubric, field
origins, and an effective-configuration checksum. Pass that snapshot to
`run_prepared_research()` so the reviewed settings are not resolved a second
time. The original `run_research()` entry point remains available and now uses
the same preflight path. Provider/content selections can only narrow ready,
approved capabilities. An unlisted domain requires the explicit
`allow_other_domain` choice and uses wildcard-domain providers. Free-text
configuration instructions require an explicit interpretation draft and review;
they are never silently ignored. The submitted record preserves the original
text, proposed deductions, confirmed field origins, and effective checksum.
Explicit date ranges reject undated records; an explicit recency choice overrides
preset age defaults. Evidence-tier choices narrow to ready source types.
Retrieval top-k cannot exceed the configured context chunk ceiling.

The catalog describes available choices; it does not install adapters or enable
network access by itself. Synthetic fixtures remain test data and should not be
presented as real evidence.

Use `resolve_search_configuration(request, ready_adapters, preset_name="balanced")`
from `src.configuration` before starting either research worker. Pass a mapping
of initialized, usable adapters keyed by provider ID. The resolver keeps only
enabled providers for the request's domain, applies the route and source policy,
and rejects unavailable required source types. `requested_limits=SearchLimits(...)`
can override preset counts within the operator's hard limits.

The resolver combines each selected source type's default record cap with any
request override, bounded by `max_sources`. It also combines the preset's
`recency_days` with type-specific age defaults. Scout and Library skip dated
records older than the resulting cap; undated records remain usable because
their age cannot be verified. The resolved `as_of_date` records the reference
date. Required types from both the request and domain route are checked again
against Library's usable sources at the join. `src/application.py` calls the
resolver before workers start; the CLI can choose frozen fixtures or ready live
adapters.
