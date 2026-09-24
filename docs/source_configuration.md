# Source configuration

`config/sources.json` is the operator-owned registry: source types describe the
kind and evidence tier of a record; providers describe adapters, their supported
types, capabilities, domains, credentials, timeouts, and request limits. The
implemented GitHub and Tavily adapters and the frozen fixture adapter are enabled;
OpenAlex, arXiv, and PubMed stay disabled until their adapters are implemented.
Routes can map a domain to approved providers and source types.

For a local run, construct the adapters and register them by provider ID:

```python
adapters = {
    "tavily": TavilyAdapter(),
    "github": GitHubAdapter(),
}
```

Set `TAVILY_API_KEY` for Tavily. GitHub public repository search works without a
token; setting `GITHUB_TOKEN` is optional and gives authenticated requests a higher
rate limit. GitHub captures repository metadata and its short description, not the
README contents. Tavily returns the title and URL, plus a short snippet only when
`page_snippet` is requested. Both adapters use per-request timeouts and avoid raw
page contents.

`config/search_defaults.json` contains the starter `balanced`, `academic`, and
`build-oriented` search presets. They cap query count, results per query, and total
records. These limits prevent broad requests from generating unbounded provider
calls, latency, or downstream model context. Hard limits are ceilings: a user can
choose a smaller budget, but cannot raise it past the configured maximum.

The Critic has a separate context-token ceiling in `config/rubric.json`. It limits
how much retrieved evidence is sent to the evaluation model. Provider request and
timeout limits live with each provider in `sources.json`. The coordinator will
eventually enforce a total wall-clock and cost budget across the whole run; those
limits are not implemented yet. Provider `max_requests_per_run` is cataloged but
the runtime coordinator does not yet enforce it. The worker source/query caps and
Critic context cap are enforced. Search preset wiring will be completed with the
coordinator/UI.

The catalog describes available choices; it does not install adapters or enable
network access by itself. Synthetic fixtures remain test data and should not be
presented as real evidence.

Use `resolve_search_configuration(request, ready_adapters, preset_name="balanced")`
from `src.configuration` before starting either research worker. Pass a mapping
of initialized, usable adapters keyed by provider ID. The resolver keeps only
enabled providers for the request's domain, applies the route and source policy,
and rejects unavailable required source types. `requested_limits=SearchLimits(...)`
can override preset counts within the operator's hard limits.

The resolver does not yet enforce `max_records_by_type`, so it rejects requests
that set those caps. Preset `recency_days` is not yet applied by the query and
adapter layers. `src/application.py` now calls the resolver before constructing
the workers; `src/cli.py` supplies only a frozen adapter. A future UI can call
the same application function with its chosen ready adapters.
