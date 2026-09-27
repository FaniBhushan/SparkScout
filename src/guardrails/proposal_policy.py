"""Last-resort narrative qualification; never waive factual or dependency checks."""

HYPOTHESIS_PREFIX = "Unverified hypothesis to test (not an established fact): "
SOFT_FIELDS = {"problem_statement", "why_it_matters", "gap_or_differentiation"}


def qualify_uncertain_narrative(draft, candidate, audit, *, allow_unsupported=False):
    """Mark proposed wording as hypothetical and optionally retain soft uncertainty."""
    unsupported = {key for key, verdict in audit.narrative_checks.items()
                   if verdict.label == "unsupported"}
    proposed = {key for key, verdict in audit.narrative_checks.items()
                if key in SOFT_FIELDS and verdict.label == "proposed"}
    if unsupported and not allow_unsupported:
        unsupported.clear()
    if not proposed and not unsupported:
        return None
    caveated = proposed | unsupported
    if not caveated.issubset(SOFT_FIELDS):
        return None
    qualified_audit = audit.model_copy(update={"caveated_fields": sorted(caveated)})
    if not qualified_audit.accepted:
        return None
    updates = {}
    for field in caveated:
        value = getattr(draft, field) or getattr(candidate, field, None)
        if not value:
            return None
        updates[field] = HYPOTHESIS_PREFIX + value
    if unsupported:
        updates["unknowns"] = [*draft.unknowns,
            "Last-resort demo fallback after one correction: marked narrative hypotheses remain "
            "unsupported. Review them before choosing this project; citations and essential "
            "dependencies were not waived."]
    return draft.model_copy(update=updates), qualified_audit
