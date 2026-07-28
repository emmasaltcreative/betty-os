"""Persisted revision requests, one file per campaign.

    outputs/<campaign_id>/revisions/revision_requests.json

Everything the revision workflow knows lives in this file: the recommendation it
came from, the capability it was classified as, the original wording, every
option generated for it, which one was selected, what the person edited it to,
and which render version it produced. Nothing is held only in session state, so
closing the app loses nothing.

Every write is atomic and is read back before it is reported as saved.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from services import revision_types as rt
from services.revision_context import revisions_dir
from src.persistence import atomic_write_json, load_json

REQUESTS_FILE = "revision_requests.json"

PROPOSED = "proposed"
GENERATING = "generating"
OPTIONS_READY = "options_ready"
SELECTED = "selected"
APPROVED_TO_APPLY = "approved_to_apply"
APPLYING = "applying"
APPLIED = "applied"
FAILED = "failed"
DISMISSED = "dismissed"

STATUSES: tuple[str, ...] = (
    PROPOSED,
    GENERATING,
    OPTIONS_READY,
    SELECTED,
    APPROVED_TO_APPLY,
    APPLYING,
    APPLIED,
    FAILED,
    DISMISSED,
)

# Groups the Revisions page shows, in order.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Awaiting Decision", (PROPOSED, GENERATING, OPTIONS_READY)),
    ("Ready to Apply", (SELECTED, APPROVED_TO_APPLY)),
    ("Applying", (APPLYING,)),
    ("Completed", (APPLIED,)),
    ("Failed", (FAILED,)),
    ("Dismissed", (DISMISSED,)),
)

OPEN_STATUSES: tuple[str, ...] = (
    PROPOSED,
    GENERATING,
    OPTIONS_READY,
    SELECTED,
    APPROVED_TO_APPLY,
    APPLYING,
    FAILED,
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def store_path(campaign_dir: Path) -> Path:
    return revisions_dir(campaign_dir) / REQUESTS_FILE


def default_store(campaign_dir: Path) -> dict[str, Any]:
    return {"campaign_id": campaign_dir.name, "updated_at": _now(), "requests": []}


def load_store(campaign_dir: Path) -> dict[str, Any]:
    data = load_json(store_path(campaign_dir), default=None)
    if not isinstance(data, dict):
        return default_store(campaign_dir)
    if not isinstance(data.get("requests"), list):
        data["requests"] = []
    data.setdefault("campaign_id", campaign_dir.name)
    return data


def save_store(campaign_dir: Path, data: dict[str, Any]) -> Path:
    requests = [r for r in data.get("requests") or [] if isinstance(r, dict)]
    path = atomic_write_json(
        store_path(campaign_dir),
        {
            "campaign_id": campaign_dir.name,
            "updated_at": _now(),
            "requests": requests,
        },
    )
    reloaded = load_store(campaign_dir)
    if len(reloaded.get("requests") or []) != len(requests):
        raise RuntimeError(
            "revision_requests.json could not be read back after saving; nothing was recorded."
        )
    return path


def list_requests(campaign_dir: Path) -> list[dict[str, Any]]:
    return [r for r in load_store(campaign_dir).get("requests") or [] if isinstance(r, dict)]


def next_request_id(campaign_dir: Path) -> str:
    highest = 0
    for request in list_requests(campaign_dir):
        digits = "".join(ch for ch in str(request.get("revision_request_id") or "") if ch.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return f"revreq_{highest + 1:03d}"


# --- Creating ---------------------------------------------------------------

def new_request(
    *,
    campaign_dir: Path,
    recommendation: dict[str, Any],
    classification: Any,
    instruction: str = "",
) -> dict[str, Any]:
    """A revision request in `proposed`, carrying its classification with it."""
    request = {
        "revision_request_id": next_request_id(campaign_dir),
        "campaign_id": campaign_dir.name,
        "content_piece_id": classification.asset_id,
        "affected_asset_id": classification.asset_id,
        "affected_asset_name": classification.asset_name,
        "affected_render_version_id": classification.render_version_id,
        "recommendation_id": str(recommendation.get("recommendation_id") or ""),
        "revision_type": classification.revision_type,
        "target_field": classification.target_field,
        "capability": classification.capability,
        "capability_rationale": classification.rationale,
        "capability_confidence": round(float(classification.confidence), 2),
        # The recommendation as written is kept intact; the instruction is
        # editable beside it and never replaces it.
        "original_recommendation": {
            "title": str(recommendation.get("title") or ""),
            "full_instruction": str(recommendation.get("full_instruction") or ""),
            "rationale": str(recommendation.get("rationale") or ""),
            "expected_changes": str(recommendation.get("expected_changes") or ""),
            "recommendation_type": str(recommendation.get("recommendation_type") or ""),
        },
        "default_instruction": classification.default_instruction,
        "instruction": (instruction or classification.default_instruction).strip(),
        "original_value": classification.original_value,
        "generated_options": [],
        "selected_option_id": None,
        "edited_value": None,
        "proposed_change": dict(classification.proposed_change),
        "requirement": dict(classification.requirement),
        "supplied_assets": [],
        "constraints_used": {},
        "generation_count": 0,
        "status": PROPOSED,
        "created_at": _now(),
        "updated_at": _now(),
        "applied_at": None,
        "resulting_render_version_id": None,
        "failure_reason": None,
    }
    store = load_store(campaign_dir)
    store.setdefault("requests", []).append(request)
    save_store(campaign_dir, store)
    saved = get_request(campaign_dir, str(request["revision_request_id"]))
    if saved is None:
        raise RuntimeError("The revision request was not written to disk.")
    return saved


def get_request(campaign_dir: Path, request_id: str) -> dict[str, Any] | None:
    for request in list_requests(campaign_dir):
        if str(request.get("revision_request_id")) == str(request_id):
            return request
    return None


def open_request_for_recommendation(
    campaign_dir: Path, recommendation_id: str
) -> dict[str, Any] | None:
    """The live request for a recommendation, newest first."""
    matches = [
        request
        for request in list_requests(campaign_dir)
        if str(request.get("recommendation_id")) == str(recommendation_id)
        and str(request.get("status")) in OPEN_STATUSES
    ]
    return matches[-1] if matches else None


def requests_for_recommendation(
    campaign_dir: Path, recommendation_id: str
) -> list[dict[str, Any]]:
    return [
        request
        for request in list_requests(campaign_dir)
        if str(request.get("recommendation_id")) == str(recommendation_id)
    ]


# --- Updating ---------------------------------------------------------------

def update_request(
    campaign_dir: Path, request_id: str, **changes: Any
) -> dict[str, Any] | None:
    """Apply named changes to one request and persist the whole file."""
    store = load_store(campaign_dir)
    found: dict[str, Any] | None = None
    for request in store.get("requests") or []:
        if not isinstance(request, dict):
            continue
        if str(request.get("revision_request_id")) != str(request_id):
            continue
        status = changes.get("status")
        if status is not None and status not in STATUSES:
            raise ValueError(f"`{status}` is not a revision status.")
        request.update(changes)
        request["updated_at"] = _now()
        if status == APPLIED and not request.get("applied_at"):
            request["applied_at"] = _now()
        if status not in {FAILED, None}:
            request.setdefault("failure_reason", None)
        found = request
        break
    if found is None:
        return None
    save_store(campaign_dir, store)
    return get_request(campaign_dir, request_id)


def record_options(
    campaign_dir: Path,
    request_id: str,
    *,
    options: list[dict[str, Any]],
    constraints_used: dict[str, Any],
    replace: bool = False,
) -> dict[str, Any] | None:
    """Store generated options with their validation verdicts attached."""
    request = get_request(campaign_dir, request_id)
    if request is None:
        return None
    existing = [] if replace else list(request.get("generated_options") or [])
    generation = int(request.get("generation_count") or 0) + 1
    for option in options:
        entry = dict(option)
        entry["generation"] = generation
        existing.append(entry)
    return update_request(
        campaign_dir,
        request_id,
        generated_options=existing,
        constraints_used=constraints_used,
        generation_count=generation,
        status=OPTIONS_READY if existing else PROPOSED,
        failure_reason=None,
    )


def option_texts(request: dict[str, Any]) -> list[str]:
    return [str(option.get("text") or "") for option in request.get("generated_options") or []]


def find_option(request: dict[str, Any], option_id: str) -> dict[str, Any] | None:
    for option in request.get("generated_options") or []:
        if str(option.get("option_id")) == str(option_id):
            return option
    return None


def selected_value(request: dict[str, Any]) -> str:
    """What would actually be applied: the edit if there is one, else the option."""
    edited = str(request.get("edited_value") or "").strip()
    if edited:
        return edited
    option = find_option(request, str(request.get("selected_option_id") or ""))
    return str(option.get("text") or "") if option else ""


def next_option_index(request: dict[str, Any]) -> int:
    highest = 0
    for option in request.get("generated_options") or []:
        digits = "".join(ch for ch in str(option.get("option_id") or "") if ch.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return highest + 1


# --- Reading for the interface ----------------------------------------------

def grouped_requests(campaign_dir: Path) -> list[tuple[str, list[dict[str, Any]]]]:
    requests = list_requests(campaign_dir)
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for label, statuses in GROUPS:
        bucket = [r for r in requests if str(r.get("status")) in statuses]
        if bucket:
            out.append((label, bucket))
    return out


def counts(campaign_dir: Path) -> dict[str, int]:
    tally = {status: 0 for status in STATUSES}
    for request in list_requests(campaign_dir):
        status = str(request.get("status") or PROPOSED)
        if status in tally:
            tally[status] += 1
    tally["awaiting_decision"] = tally[PROPOSED] + tally[GENERATING] + tally[OPTIONS_READY]
    tally["ready_to_apply"] = tally[SELECTED] + tally[APPROVED_TO_APPLY]
    tally["needs_human"] = sum(
        1
        for request in list_requests(campaign_dir)
        if str(request.get("capability")) == rt.HUMAN_INPUT_REQUIRED
        and str(request.get("status")) in OPEN_STATUSES
    )
    return tally


def describe(request: dict[str, Any]) -> str:
    """`Ritual Reel — rewrite the supporting copy`."""
    asset = str(request.get("affected_asset_name") or request.get("affected_asset_id") or "Asset")
    return f"{asset} — {rt.type_label(str(request.get('revision_type') or '')).lower()}"
