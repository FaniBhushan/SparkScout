"""Apply only reviewed prompt deductions to a submitted run configuration."""

from __future__ import annotations

from src.models import (
    EvaluationSelection,
    InputRequest,
    InterpretationReview,
    PromptInterpretationDraft,
    SearchConfiguration,
    SubmittedRunConfiguration,
    ValueOrigin,
)


_REVIEWABLE_FIELDS = {
    "request": set(InputRequest.model_fields) - {"schema_version", "source_policy"},
    "search": set(SearchConfiguration.model_fields) - {"schema_version", "custom_instructions"},
    "evaluation": set(EvaluationSelection.model_fields) - {"schema_version", "custom_instructions"},
}


def confirm_interpretation(
    draft: PromptInterpretationDraft,
    review: InterpretationReview,
) -> SubmittedRunConfiguration:
    """Explicit corrections win; unaccepted model text never changes a run."""

    proposal = {
        section: getattr(draft.suggestions, section).model_dump(
            exclude_unset=True, exclude_none=True
        )
        for section in _REVIEWABLE_FIELDS
    }
    offered = {
        f"{section}.{field}"
        for section, fields in proposal.items()
        for field in fields
    }
    unknown_acceptances = review.accepted_paths - offered
    if unknown_acceptances:
        raise ValueError(f"cannot accept fields the draft did not offer: {sorted(unknown_acceptances)}")
    for path in review.overrides:
        section, separator, field = path.partition(".")
        if not separator or field not in _REVIEWABLE_FIELDS.get(section, set()):
            raise ValueError(f"unknown or non-reviewable field: {path!r}")
    if "search.allow_other_domain" in review.accepted_paths and "search.allow_other_domain" not in review.overrides:
        raise ValueError("Other-domain access requires an explicit user choice")
    unreviewed_issues = set(range(len(draft.issues))) - review.acknowledged_issues
    if unreviewed_issues:
        raise ValueError(f"review or acknowledge interpretation issues: {sorted(unreviewed_issues)}")
    if review.acknowledged_issues - set(range(len(draft.issues))):
        raise ValueError("acknowledged_issues contains an unknown issue index")
    for issue in draft.issues:
        if (
            issue.kind == "unsupported"
            and issue.path in review.accepted_paths
            and issue.path not in review.overrides
        ):
            raise ValueError(f"unsupported suggestion must be corrected: {issue.path}")
    uncertain = set(draft.suggestions.uncertain_paths)
    if (review.accepted_paths & uncertain) - review.overrides.keys():
        raise ValueError("uncertain suggestions require an explicit correction")

    values: dict[str, dict[str, object]] = {section: {} for section in _REVIEWABLE_FIELDS}
    origins: dict[str, ValueOrigin] = {}
    for path in review.accepted_paths:
        section, _, field = path.partition(".")
        values[section][field] = proposal[section][field]
        origins[path] = "deduced"
    for path, value in review.overrides.items():
        section, _, field = path.partition(".")
        values[section][field] = value
        origins[path] = "explicit"
    return SubmittedRunConfiguration(
        request=InputRequest.model_validate(values["request"]),
        search=SearchConfiguration.model_validate(values["search"]),
        evaluation=EvaluationSelection.model_validate(values["evaluation"]),
        original_prompt=draft.original_prompt,
        interpretation_draft=draft,
        field_origins=origins,
    )
