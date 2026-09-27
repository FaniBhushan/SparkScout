"""Stage caching adapters keep persistence out of worker business logic."""


class CheckpointWorker:
    def __init__(self, worker, store, stage, result_type):
        self.worker, self.store, self.stage, self.result_type = worker, store, stage, result_type

    def with_retriever(self, retriever):
        return CheckpointWorker(self.worker.with_retriever(retriever), self.store,
                                self.stage, self.result_type)

    async def run(self, *args):
        def serialized(value):
            if isinstance(value, list):
                return [serialized(item) for item in value]
            return value.model_dump(mode="json")
        inputs = [serialized(arg) for arg in args]
        return await self.store.run_stage(self.stage, inputs, self.result_type,
                                         lambda: self.worker.run(*args))


class CheckpointWriter:
    """Keep completed finalist drafts when a later proposal fails."""

    def __init__(self, writer, store):
        self.writer, self.store = writer, store

    async def draft(self, request, candidate, evaluation, sources, chunks):
        from src.models import ProposalDraft
        inputs = {"request": request.model_dump(mode="json"),
                  "candidate": candidate.model_dump(mode="json"),
                  "evaluation": evaluation.model_dump(mode="json"),
                  "sources": sources, "chunks": chunks}
        return await self.store.run_stage(
            f"proposal:{candidate.candidate_id}", inputs, ProposalDraft,
            lambda: self.writer.draft(request, candidate, evaluation, sources, chunks),
        )
