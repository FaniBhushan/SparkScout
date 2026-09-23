# Run traces

Create one `RunTracer` when a run starts. It prints readable logs to the
terminal and writes structured events to `runs/<run_id>/trace.jsonl`. The
`runs/` directory is ignored by Git. No run logs appear until a worker or the
coordinator is actually started with a tracer.

```python
from src.observability import RunTracer
from src.workers.scout import ScoutWorker

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

Trace events contain identifiers, counts, timing, and usage. Do not add prompts,
retrieved text, API keys, or user-provided secrets to trace events. The
coordinator remains responsible for enforcing budgets; the tracer records what
was used.
