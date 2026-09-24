# Run traces

Create one `RunTracer` when a run starts. It prints readable logs to the
terminal and writes structured events to `runs/<run_id>/trace.jsonl`. The
`runs/` directory is ignored by Git. No run logs appear until a worker or the
coordinator is actually started with a tracer.

```python
from src.observability import RunTracer
from src.workers.scout_worker import ScoutWorker

tracer = RunTracer(run_id="run-001")
try:
    scout = ScoutWorker(adapters, query_planner, candidate_generator, tracer=tracer)
    result = await scout.run(request, resolved_search)
finally:
    tracer.close()
```

The example belongs inside the future async coordinator, where `adapters`,
`query_planner`, `candidate_generator`, `request`, and `resolved_search` are
created. Pass the same tracer to other workers as they are implemented. Each
span records start, end or error, elapsed milliseconds, and a span ID. Budget
events record used, limit, remaining, and
whether the limit was exceeded. When model usage is available, call
`tracer.usage(stage, usage_record)` and record its token and cost budgets with
`tracer.budget(stage, metric, used, limit)`. Set `console=False` to write only
the JSONL file.

Pass the same tracer to `LLMScoutQueryPlanner`, `LLMCandidateGenerator`,
`LLMLibraryQueryPlanner`, and `LLMCandidateJudge`. Each model call records its
model name and reported token counts, including responses that fail JSON
validation. Supply `ModelPricing(input_per_million=..., output_per_million=...)`
to `OpenAITextClient` to estimate USD cost. Without configured rates, cost is
omitted from the JSON trace. `token_usage_available=false` means the provider
did not report token counts; zero values in that event are placeholders.

Trace events contain identifiers, counts, timing, and usage. Do not add prompts,
retrieved text, API keys, or user-provided secrets to trace events. The
coordinator remains responsible for enforcing budgets; the tracer records what
was used.
