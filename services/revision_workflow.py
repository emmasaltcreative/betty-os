"""The revision workflow, one function per thing a person can do.

The interface has a button for each of these and does nothing else itself: no
decision lives in session state, and every call here reads the request from disk,
changes it, and writes it back. That is what makes the buttons survive a restart.

Generation is the only step that reaches the model. It moves the request through
`generating` so a page reloaded mid-generation still shows the truth, and it
records a failure reason rather than raising into the interface.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from services import ai_revision_service as ai
from services import revision_store as store
from services import revision_types as rt
from services.revision_classifier import Classification, reclassify_one
from services.revision_context import (
    AssetTarget,
    campaign_objective,
    current_value,
    load_render_config,
    platform_for,
    protected_fields,
    resolve_asset,
    template_constraints,
    uploads_dir,
)
from services.revision_validation import REJECTED, Verdict, validate_option, validate_options
from src.brand import load_brand_brain
from src.common import ROOT, BettyOSError

MAX_GENERATIONS = 6


class RevisionWorkflowError(BettyOSError):
    """A revision action could not be carried out, with a reason worth showing."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _require(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    request = store.get_request(campaign_dir, request_id)
    if request is None:
        raise RevisionWorkflowError(f"Revision request {request_id} is not in this campaign.")
    return request


def _target_for(campaign_dir: Path, request: dict[str, Any]) -> AssetTarget:
    target = resolve_asset(
        campaign_dir,
        affected_asset=str(request.get("affected_asset_name") or ""),
        affected_files=[str(request.get("affected_asset_id") or "")],
    )
    if target is None:
        raise RevisionWorkflowError(
            f"BettyOS can no longer find {request.get('affected_asset_name') or 'that asset'} "
            "in this campaign."
        )
    return target


# --- Opening a request ------------------------------------------------------

def open_request(
    campaign_dir: Path,
    *,
    recommendation: dict[str, Any],
    classification: Classification | None = None,
    instruction: str = "",
) -> dict[str, Any]:
    """Start work on a recommendation, or return the request already open for it."""
    existing = store.open_request_for_recommendation(
        campaign_dir, str(recommendation.get("recommendation_id") or "")
    )
    if existing is not None:
        return existing
    resolved = classification or reclassify_one(
        campaign_dir=campaign_dir, recommendation=recommendation
    )
    return store.new_request(
        campaign_dir=campaign_dir,
        recommendation=recommendation,
        classification=resolved,
        instruction=instruction,
    )


def set_instruction(campaign_dir: Path, request_id: str, instruction: str) -> dict[str, Any]:
    """Save an edited instruction. The original recommendation is left as written."""
    request = _require(campaign_dir, request_id)
    cleaned = instruction.strip()
    if not cleaned:
        raise RevisionWorkflowError("An instruction cannot be empty.")
    if cleaned == str(request.get("instruction") or "").strip():
        return request
    updated = store.update_request(campaign_dir, request_id, instruction=cleaned)
    return updated or request


# --- Generating options -----------------------------------------------------

def _generation_inputs(campaign_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
    field_key = str(request.get("target_field") or "")
    revision_field = rt.field_for(field_key)
    if revision_field is None or not revision_field.is_copy:
        raise RevisionWorkflowError(
            "This revision is a setting change, not a wording change, so there is nothing "
            "to write."
        )
    target = _target_for(campaign_dir, request)
    config = load_render_config(campaign_dir, target)
    original = current_value(campaign_dir, target, field_key, config=config)
    if not original.strip():
        raise RevisionWorkflowError(
            f"{target.asset_name} has no {revision_field.label.lower()} to revise."
        )
    constraints = template_constraints(target, field_key)
    return {
        "target": target,
        "field_key": field_key,
        "original": original,
        "constraints": constraints,
        "platform": platform_for(target, field_key),
        "protected": protected_fields(target, field_key),
        "brand_guide": load_brand_brain(),
    }


def generate(
    campaign_dir: Path,
    request_id: str,
    *,
    count: int = 3,
    similar_to_option_id: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Write options for a request, validate them, and record them.

    `replace` starts over; otherwise new options are added beside the existing
    ones so a person can compare everything they have been offered.
    """
    request = _require(campaign_dir, request_id)
    if str(request.get("status")) == store.APPLIED:
        raise RevisionWorkflowError("This revision has already been applied.")
    if int(request.get("generation_count") or 0) >= MAX_GENERATIONS and not replace:
        raise RevisionWorkflowError(
            f"BettyOS has generated {MAX_GENERATIONS} rounds of options for this revision. "
            "Edit one of them, or start again."
        )

    inputs = _generation_inputs(campaign_dir, request)
    similar_to = None
    if similar_to_option_id:
        option = store.find_option(request, similar_to_option_id)
        if option is None:
            raise RevisionWorkflowError("That option is no longer on this revision.")
        similar_to = str(option.get("text") or "")

    existing_texts = [] if replace else store.option_texts(request)
    store.update_request(campaign_dir, request_id, status=store.GENERATING, failure_reason=None)

    constraints = dict(inputs["constraints"])
    constraints["field_key"] = inputs["field_key"]
    constraints["option_start_index"] = 1 if replace else store.next_option_index(request)

    proposal = ai.generate_options(
        revision_request_id=request_id,
        original_content=inputs["original"],
        recommendation=str(request.get("original_recommendation", {}).get("full_instruction") or ""),
        instruction=str(request.get("instruction") or ""),
        revision_type=str(request.get("revision_type") or ""),
        brand_guide=inputs["brand_guide"],
        campaign_objective=campaign_objective(),
        platform=inputs["platform"],
        template_constraints=constraints,
        protected_fields=inputs["protected"],
        option_count=count,
        avoid=existing_texts,
        similar_to=similar_to,
    )

    if not proposal.ok:
        store.update_request(
            campaign_dir,
            request_id,
            status=store.OPTIONS_READY if existing_texts else store.PROPOSED,
            failure_reason=proposal.failure_reason,
        )
        raise RevisionWorkflowError(proposal.failure_reason)

    # Brand safety runs before anything is shown, and judges each option against
    # the others so a near-duplicate is caught too.
    verdicts = validate_options(
        [option.to_dict() for option in proposal.options],
        original_value=inputs["original"],
        max_words=inputs["constraints"].get("max_words"),
        max_chars=inputs["constraints"].get("max_chars"),
        platform=inputs["platform"],
        brand_guide=inputs["brand_guide"],
    )
    recorded = [
        {
            **option.to_dict(),
            "validation": verdicts[option.option_id].to_dict(),
            "generated_at": _now(),
            "from_option_id": similar_to_option_id,
        }
        for option in proposal.options
    ]

    updated = store.record_options(
        campaign_dir,
        request_id,
        options=recorded,
        constraints_used=proposal.constraints_used,
        replace=replace,
    )
    if updated is None:
        raise RevisionWorkflowError("The generated options could not be saved.")
    if replace:
        updated = store.update_request(
            campaign_dir, request_id, selected_option_id=None, edited_value=None
        ) or updated
    return updated


# --- Choosing and editing ---------------------------------------------------

def validate_text(campaign_dir: Path, request: dict[str, Any], text: str) -> Verdict:
    """Check wording a person typed, using the same rules as generated options."""
    inputs = _generation_inputs(campaign_dir, request)
    return validate_option(
        text,
        option_id=str(request.get("selected_option_id") or "edited"),
        original_value=inputs["original"],
        max_words=inputs["constraints"].get("max_words"),
        max_chars=inputs["constraints"].get("max_chars"),
        platform=inputs["platform"],
        brand_guide=inputs["brand_guide"],
    )


def select(campaign_dir: Path, request_id: str, option_id: str) -> dict[str, Any]:
    """Choose an option. A rejected option cannot be chosen without an edit."""
    request = _require(campaign_dir, request_id)
    option = store.find_option(request, option_id)
    if option is None:
        raise RevisionWorkflowError("That option is no longer on this revision.")
    verdict = Verdict.from_dict(option.get("validation") or {})
    if verdict.verdict == REJECTED:
        reasons = "; ".join(issue.message for issue in verdict.issues)
        raise RevisionWorkflowError(
            f"That option did not pass the brand checks, so it cannot be applied as it "
            f"stands: {reasons}",
            hint="Edit the wording and it will be checked again.",
        )
    updated = store.update_request(
        campaign_dir,
        request_id,
        selected_option_id=option_id,
        edited_value=None,
        status=store.SELECTED,
        failure_reason=None,
    )
    return updated or request


def edit_selection(
    campaign_dir: Path, request_id: str, text: str, *, option_id: str | None = None
) -> dict[str, Any]:
    """Save edited wording, checked before it is accepted.

    This is also the only way a rejected option can be used: naming it here
    adopts it *and* the edit together, and only if the edit passes.
    """
    request = _require(campaign_dir, request_id)
    cleaned = text.strip()
    if not cleaned:
        raise RevisionWorkflowError("Revised wording cannot be empty.")

    target_id = str(option_id or request.get("selected_option_id") or "")
    if not target_id:
        raise RevisionWorkflowError("Choose an option before editing it.")
    if store.find_option(request, target_id) is None:
        raise RevisionWorkflowError("That option is no longer on this revision.")

    verdict = validate_text(campaign_dir, request, cleaned)
    if verdict.verdict == REJECTED:
        reasons = "; ".join(issue.message for issue in verdict.issues)
        raise RevisionWorkflowError(
            f"That wording did not pass the brand checks: {reasons}",
            hint="Adjust it and save again.",
        )

    options = [dict(option) for option in request.get("generated_options") or []]
    for option in options:
        if str(option.get("option_id")) == target_id:
            option["validation"] = verdict.to_dict()
            option["edited"] = True

    updated = store.update_request(
        campaign_dir,
        request_id,
        selected_option_id=target_id,
        edited_value=cleaned,
        generated_options=options,
        status=store.SELECTED,
        failure_reason=None,
    )
    return updated or request


def defer(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    """Keep everything and come back to it. Nothing is discarded."""
    request = _require(campaign_dir, request_id)
    updated = store.update_request(campaign_dir, request_id, deferred_at=_now())
    return updated or request


def resume(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    request = _require(campaign_dir, request_id)
    updated = store.update_request(campaign_dir, request_id, deferred_at=None)
    return updated or request


def cancel_selection(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    """Unchoose, without discarding the options that were generated."""
    request = _require(campaign_dir, request_id)
    status = store.OPTIONS_READY if request.get("generated_options") else store.PROPOSED
    updated = store.update_request(
        campaign_dir,
        request_id,
        selected_option_id=None,
        edited_value=None,
        status=status,
    )
    return updated or request


def dismiss(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    request = _require(campaign_dir, request_id)
    if str(request.get("status")) == store.APPLIED:
        raise RevisionWorkflowError(
            "This revision has already produced a version, so it cannot be dismissed. "
            "Reject the new version under Approvals instead."
        )
    updated = store.update_request(campaign_dir, request_id, status=store.DISMISSED)
    return updated or request


# --- Deterministic changes --------------------------------------------------

def set_change(campaign_dir: Path, request_id: str, change: dict[str, Any]) -> dict[str, Any]:
    """Record the exact setting change for a Ready to Apply revision."""
    request = _require(campaign_dir, request_id)
    if not change:
        raise RevisionWorkflowError("No setting change was given.")
    merged = {**(request.get("proposed_change") or {}), **change}
    updated = store.update_request(
        campaign_dir,
        request_id,
        proposed_change=merged,
        status=store.SELECTED,
        failure_reason=None,
    )
    return updated or request


# --- Human input ------------------------------------------------------------

def attach_asset(
    campaign_dir: Path, request_id: str, *, filename: str, data: bytes
) -> dict[str, Any]:
    """Save a supplied source asset against the revision that was waiting for it."""
    request = _require(campaign_dir, request_id)
    safe = Path(filename).name
    if not safe:
        raise RevisionWorkflowError("That file has no name BettyOS can use.")
    if not data:
        raise RevisionWorkflowError("That file is empty.")

    folder = uploads_dir(campaign_dir) / request_id
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / safe
    if destination.exists():
        raise RevisionWorkflowError(f"{safe} has already been supplied for this revision.")
    destination.write_bytes(data)

    supplied = [dict(entry) for entry in request.get("supplied_assets") or []]
    supplied.append(
        {
            "filename": safe,
            "path": destination.resolve().relative_to(ROOT.resolve()).as_posix()
            if destination.resolve().is_relative_to(ROOT.resolve())
            else str(destination),
            "bytes": len(data),
            "supplied_at": _now(),
        }
    )
    updated = store.update_request(campaign_dir, request_id, supplied_assets=supplied)
    return updated or request


# --- Applying ---------------------------------------------------------------

def approve_to_apply(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    request = _require(campaign_dir, request_id)
    updated = store.update_request(
        campaign_dir, request_id, status=store.APPROVED_TO_APPLY, failure_reason=None
    )
    return updated or request


def retry(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    """Put a failed revision back where it was, ready to try again."""
    request = _require(campaign_dir, request_id)
    if str(request.get("status")) != store.FAILED:
        return request
    has_choice = bool(store.selected_value(request)) or bool(request.get("proposed_change"))
    status = (
        store.SELECTED
        if has_choice
        else (store.OPTIONS_READY if request.get("generated_options") else store.PROPOSED)
    )
    updated = store.update_request(
        campaign_dir, request_id, status=status, failure_reason=None
    )
    return updated or request
