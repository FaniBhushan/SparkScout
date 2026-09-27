"""Verify isolated statements against captured passages, not other proposal text."""

from typing import cast
from collections import Counter

from src.guardrails.evidence import factual_evidence_view
from src.llm.prompt_call import call_prompt
from src.models.proposal_audit import ClaimVerdict, NarrativeVerdict, ProposalAudit, StatementAudit


class LLMProposalVerifier:
    def __init__(self, client, *, max_output_tokens=2000, tracer=None):
        self.client = client
        self.max_output_tokens = max_output_tokens
        self.tracer = tracer

    async def verify(self, request, narrative, claims, chunks, *, task_id=None) -> ProposalAudit:
        """Build exact evidence scopes and reconstruct a complete typed audit."""
        passages = [{**chunk, "text": factual_evidence_view(chunk["text"])} for chunk in chunks]
        by_id = {chunk["chunk_id"]: chunk for chunk in passages}
        removed = sum(before["text"] != after["text"] for before, after in zip(chunks, passages))
        if removed and self.tracer:
            self.tracer.event("proposal_verifier", "evidence_instruction_omitted", count=removed)
        checks = []
        for index, claim in enumerate(claims):
            identifiers = []
            for reference in claim.references:
                chunk = by_id.get(reference.chunk_id)
                if chunk is None or chunk["source_id"] != reference.source_id:
                    raise ValueError("every proposal claim requires an exact supplied chunk citation")
                identifiers.append(reference.chunk_id)
            if not identifiers:
                raise ValueError("proposal claim has no cited passages")
            checks.append({"check_id": f"claim:{index}", "kind": "fact", "statement": claim.claim,
                           "passage_ids": identifiers})

        candidate = narrative.get("candidate", {})
        proposal = narrative.get("proposal", {})
        dependencies = list(dict.fromkeys([
            *candidate.get("required_data", []), *proposal.get("required_data", []),
        ]))
        for index, dependency in enumerate(dependencies):
            checks.append({"check_id": f"dependency:{index}", "kind": "required_data",
                           "statement": dependency, "passage_ids": list(by_id)})
            checks.append({"check_id": f"access:{index}", "kind": "data_access",
                           "statement": dependency, "passage_ids": list(by_id)})
        statements = {field: proposal.get(field) or candidate.get(field)
                      for field in ("problem_statement", "why_it_matters", "gap_or_differentiation")
                      if proposal.get(field) or candidate.get(field)}
        implementation = [*proposal.get("scoped_mvp", []), *proposal.get("access_assumptions", [])]
        if proposal.get("technical_approach"):
            implementation.append(proposal["technical_approach"])
        if implementation:
            statements["implementation"] = " ".join(implementation)
        if dependencies and (candidate.get("proposed_outcome") or implementation):
            # A generic dataset can exist and be accessible yet lack the labels
            # needed by this particular task. Check that separately from access.
            checks.append({"check_id": "narrative:data_task_fit", "kind": "task_data_fit",
                           "statement": {
                               "proposed_artifact": candidate.get("proposed_outcome", ""),
                               "essential_implementation": implementation,
                               "required_data": dependencies,
                           }, "passage_ids": list(by_id)})
        for field, statement in statements.items():
            checks.append({"check_id": f"narrative:{field}", "kind": "proposal_statement",
                           "statement": statement, "passage_ids": list(by_id)})

        request_data = request.model_dump(mode="json") if hasattr(request, "model_dump") else request
        resources = request_data.get("available_resources", [])
        response = cast(StatementAudit, await call_prompt(
            self.client, "proposal_verifier", {"CHECKS_JSON": {
                "candidate_id": task_id, "checks": checks, "passages": passages,
                "user_resources": resources,
            }}, max_output_tokens=self.max_output_tokens, tracer=self.tracer,
            task_id=task_id, validation_retry_limit=1,
        ))
        scopes = {item["check_id"]: item for item in checks}
        counts = Counter(item.check_id for item in response.checks)
        # A model can confuse a proposed implementation with factual availability.
        # Repair only these invalid labels once; do not rewrite a valid proposal.
        invalid_ids = {key for key in scopes if counts[key] != 1}
        invalid_ids.update(item.check_id for item in response.checks
                           if item.check_id in scopes and item.label == "proposed"
                           and scopes[item.check_id]["kind"] != "proposal_statement")
        # Unrequested checks cannot establish anything about the proposal.
        # Ignore them; missing/duplicate expected checks must still be repaired.
        retained = {item.check_id: item for item in response.checks
                    if item.check_id in scopes and item.check_id not in invalid_ids}
        if invalid_ids:
            repair_checks = [{**scopes[key], "allowed_labels": (
                ["supported", "unsupported", "contradictory", "proposed"]
                if scopes[key]["kind"] == "proposal_statement" else ["supported", "unsupported", "contradictory"])}
                             for key in sorted(invalid_ids)]
            repair = cast(StatementAudit, await call_prompt(
                self.client, "proposal_verifier", {"CHECKS_JSON": {
                    "candidate_id": task_id, "checks": repair_checks,
                    "passages": passages, "user_resources": resources,
                }}, max_output_tokens=self.max_output_tokens, tracer=self.tracer,
                task_id=task_id, validation_retry_limit=0))
            if sorted(item.check_id for item in repair.checks) != sorted(invalid_ids):
                raise ValueError("verifier label repair must cover exactly the invalid checks")
            retained.update({item.check_id: item for item in repair.checks})
        response = StatementAudit(checks=[retained[key] for key in scopes])
        audit = ProposalAudit(claims=[])
        access_verdicts = {}
        for verdict in response.checks:
            scope = scopes[verdict.check_id]
            texts = [by_id[key]["text"] for key in scope["passage_ids"]]
            if scope["kind"] in ("required_data", "data_access", "task_data_fit"):
                texts.extend(resources)
            # Keep invalid grounding as a specific, actionable rejection, not a
            # generic schema error that causes an unhelpful rewrite of the draft.
            if verdict.label == "supported" and (
                not verdict.evidence_quotes or any(
                    not any(quote in text for text in texts) for quote in verdict.evidence_quotes
                )
            ):
                verdict = verdict.model_copy(update={"label": "unsupported", "evidence_quotes": [],
                    "rationale": "No exact evidence passage supports this assertion. Qualify or remove it."})
            if verdict.label == "proposed" and scope["kind"] != "proposal_statement":
                verdict = verdict.model_copy(update={"label": "unsupported",
                    "rationale": "A proposed fact or data dependency is not established evidence."})
            if verdict.label == "proposed":
                verdict = verdict.model_copy(update={"evidence_quotes": []})
            section, key = verdict.check_id.split(":", 1)
            fields = verdict.model_dump(exclude={"check_id"})
            if section == "narrative":
                audit.narrative_checks[key] = NarrativeVerdict.model_validate(fields)
            elif section == "access":
                access_verdicts[int(key)] = ClaimVerdict(claim_index=int(key), **fields)
            else:
                item = ClaimVerdict(claim_index=int(key), **fields)
                (audit.claims if section == "claim" else audit.dependencies).append(item)
        # Availability and task suitability must both hold. Keep the public
        # audit one verdict per dependency, retaining the specific access failure.
        for index, dependency in enumerate(audit.dependencies):
            access = access_verdicts[dependency.claim_index]
            if dependency.label == "supported" and access.label != "supported":
                audit.dependencies[index] = access.model_copy(update={
                    "rationale": "Access not established: " + access.rationale})
            elif dependency.label == "supported":
                audit.dependencies[index] = dependency.model_copy(update={
                    "rationale": dependency.rationale + " Access: " + access.rationale,
                    "evidence_quotes": list(dict.fromkeys([
                        *dependency.evidence_quotes, *access.evidence_quotes]))})
        return audit
