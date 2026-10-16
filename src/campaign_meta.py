"""Campaign metadata — meaningful titles and planned deliverable coverage.

Persists beside the existing campaign folder as campaign.json. Does not replace
folder identity or break historical paths.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from src.persistence import atomic_write_json, load_json

CAMPAIGN_META_FILENAME = "campaign.json"

CampaignReadiness = Literal[
    "planning",
    "waiting_for_footage",
    "creating",
    "reviewing",
    "campaign_incomplete",
    "ready_to_deliver",
    "delivered",
]

DeliverableStatus = Literal[
    "planned",
    "missing_footage",
    "ready_to_create",
    "in_review",
    "approved",
    "rejected",
    "intentionally_removed",
]


@dataclass
class PlannedDeliverable:
    deliverable_id: str
    title: str
    platform: str
    format_name: str
    role: str = "awareness"
    required: bool = True
    piece_id: str | None = None
    template_id: str | None = None
    status: DeliverableStatus = "planned"
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlannedDeliverable:
        return cls(
            deliverable_id=str(data.get("deliverable_id") or ""),
            title=str(data.get("title") or ""),
            platform=str(data.get("platform") or ""),
            format_name=str(data.get("format_name") or ""),
            role=str(data.get("role") or "awareness"),
            required=bool(data.get("required", True)),
            piece_id=data.get("piece_id"),
            template_id=data.get("template_id"),
            status=str(data.get("status") or "planned"),  # type: ignore[arg-type]
            notes=str(data.get("notes") or ""),
        )


@dataclass
class CampaignMeta:
    version: int = 1
    display_title: str = ""
    objective: str = ""
    target_audience: str = ""
    milestone_date: str | None = None
    readiness: CampaignReadiness = "planning"
    deliverables: list[PlannedDeliverable] = field(default_factory=list)
    finalize_without: list[str] = field(default_factory=list)
    finalize_reason: str = ""
    title_accepted: bool = False
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "display_title": self.display_title,
            "objective": self.objective,
            "target_audience": self.target_audience,
            "milestone_date": self.milestone_date,
            "readiness": self.readiness,
            "deliverables": [d.as_dict() for d in self.deliverables],
            "finalize_without": list(self.finalize_without),
            "finalize_reason": self.finalize_reason,
            "title_accepted": self.title_accepted,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CampaignMeta:
        data = data or {}
        return cls(
            version=int(data.get("version") or 1),
            display_title=str(data.get("display_title") or ""),
            objective=str(data.get("objective") or ""),
            target_audience=str(data.get("target_audience") or ""),
            milestone_date=data.get("milestone_date"),
            readiness=str(data.get("readiness") or "planning"),  # type: ignore[arg-type]
            deliverables=[
                PlannedDeliverable.from_dict(d) for d in (data.get("deliverables") or [])
            ],
            finalize_without=list(data.get("finalize_without") or []),
            finalize_reason=str(data.get("finalize_reason") or ""),
            title_accepted=bool(data.get("title_accepted")),
            updated_at=data.get("updated_at"),
        )


def meta_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / CAMPAIGN_META_FILENAME


def load_campaign_meta(campaign_dir: Path | None) -> CampaignMeta | None:
    if campaign_dir is None or not Path(campaign_dir).is_dir():
        return None
    data = load_json(meta_path(campaign_dir), default=None)
    if not data:
        return None
    return CampaignMeta.from_dict(data)


def save_campaign_meta(campaign_dir: Path, meta: CampaignMeta) -> Path:
    meta.updated_at = datetime.now(timezone.utc).isoformat()
    return atomic_write_json(meta_path(campaign_dir), meta.as_dict())


def suggest_campaign_title(objective: str, *, fallback: str = "Campaign") -> str:
    """Human title from objective — not a timestamp."""
    text = (objective or "").strip()
    if not text or text == "No goal recorded":
        return fallback
    lowered = text.lower()
    if "waitlist" in lowered and ("reading hour" in lowered or "reading" in lowered):
        return "Reading Hour Waitlist"
    if "holiday" in lowered or "gifting" in lowered:
        return "Holiday Gifting"
    if "familiarity" in lowered or "education" in lowered:
        return "Product Familiarity"
    if "launch" in lowered:
        return "First Edition Launch"
    # First clause, cleaned
    clause = re.split(r"[.!\n]", text)[0].strip()
    clause = re.sub(r"^(grow|build|increase|create|support)\s+(a|an|the)\s+", "", clause, flags=re.I)
    clause = clause[:60].strip(" -:")
    if not clause:
        return fallback
    return clause[0].upper() + clause[1:]


def ensure_campaign_meta(campaign_dir: Path, *, objective: str = "", pieces: list | None = None) -> CampaignMeta:
    """Load or create campaign.json with a meaningful display title and deliverables."""
    existing = load_campaign_meta(campaign_dir)
    if existing and existing.display_title and existing.deliverables:
        # Refresh statuses from pieces when provided
        if pieces is not None:
            existing = sync_deliverable_statuses(existing, pieces)
            save_campaign_meta(campaign_dir, existing)
        return existing

    meta = existing or CampaignMeta()
    if not meta.objective and objective and objective != "No goal recorded":
        meta.objective = objective
    if not meta.display_title:
        meta.display_title = suggest_campaign_title(
            meta.objective or objective, fallback="Campaign"
        )
    if not meta.deliverables and pieces is not None:
        meta.deliverables = deliverables_from_pieces(pieces)
    elif pieces is not None:
        meta = sync_deliverable_statuses(meta, pieces)
    meta.readiness = compute_readiness(meta, pieces)
    save_campaign_meta(campaign_dir, meta)
    return meta


def deliverables_from_pieces(pieces: list) -> list[PlannedDeliverable]:
    items: list[PlannedDeliverable] = []
    for piece in pieces:
        record = piece.record
        platform = _canonical_platform(record.platform or "")
        fmt = (record.format or piece.template_name or "Asset").strip()
        role = (record.objective or "awareness").strip().lower()
        if "convert" in role or "waitlist" in role:
            role_key = "conversion"
        elif "familiar" in role or "educat" in role:
            role_key = "consideration"
        else:
            role_key = "awareness"
        status = _status_from_piece(piece)
        items.append(
            PlannedDeliverable(
                deliverable_id=record.piece_id or f"piece_{len(items)+1}",
                title=record.title or fmt,
                platform=platform,
                format_name=fmt,
                role=role_key,
                required=True,
                piece_id=record.piece_id,
                template_id=getattr(piece, "template_id", None),
                status=status,
            )
        )
    return items


def sync_deliverable_statuses(meta: CampaignMeta, pieces: list) -> CampaignMeta:
    by_id = {p.record.piece_id: p for p in pieces if p.record.piece_id}
    for item in meta.deliverables:
        if item.status == "intentionally_removed":
            continue
        piece = by_id.get(item.piece_id or "")
        if piece is not None:
            item.status = _status_from_piece(piece)
    # Add any new pieces not yet in the plan
    known = {d.piece_id for d in meta.deliverables}
    for piece in pieces:
        pid = piece.record.piece_id
        if pid and pid not in known:
            meta.deliverables.extend(deliverables_from_pieces([piece]))
    meta.readiness = compute_readiness(meta, pieces)
    return meta


def compute_readiness(meta: CampaignMeta, pieces: list | None = None) -> CampaignReadiness:
    required = [
        d
        for d in meta.deliverables
        if d.required and d.deliverable_id not in meta.finalize_without
        and d.status != "intentionally_removed"
    ]
    if not required and not meta.deliverables:
        return "planning"
    approved = [d for d in required if d.status == "approved"]
    missing = [d for d in required if d.status == "missing_footage"]
    in_review = [d for d in required if d.status == "in_review"]
    ready_create = [d for d in required if d.status == "ready_to_create"]

    if meta.finalize_without and len(approved) + len(meta.finalize_without) >= len(
        [d for d in meta.deliverables if d.required and d.status != "intentionally_removed"]
    ):
        # Check if a package exists via caller; default incomplete until delivered externally
        if len(approved) == len(required):
            return "ready_to_deliver"
        return "ready_to_deliver" if meta.finalize_reason else "campaign_incomplete"

    if len(approved) == len(required) and required:
        return "ready_to_deliver"
    if missing:
        return "waiting_for_footage"
    if in_review:
        return "reviewing"
    if ready_create or approved:
        return "creating" if ready_create or len(approved) < len(required) else "campaign_incomplete"
    if approved and len(approved) < len(required):
        return "campaign_incomplete"
    return "planning"


def coverage_summary(meta: CampaignMeta) -> dict[str, Any]:
    required = [
        d
        for d in meta.deliverables
        if d.required
        and d.status != "intentionally_removed"
        and d.deliverable_id not in meta.finalize_without
    ]
    approved = [d for d in required if d.status == "approved"]
    remaining = [d for d in required if d.status != "approved"]
    removed = [
        d
        for d in meta.deliverables
        if d.status == "intentionally_removed" or d.deliverable_id in meta.finalize_without
    ]
    by_platform: dict[str, list[PlannedDeliverable]] = {}
    for d in meta.deliverables:
        if d.status == "intentionally_removed":
            continue
        by_platform.setdefault(d.platform or "Other", []).append(d)
    return {
        "required_total": len(required),
        "approved_count": len(approved),
        "remaining": remaining,
        "approved": approved,
        "removed": removed,
        "by_platform": by_platform,
        "readiness": meta.readiness,
        "progress_label": f"{len(approved)} of {len(required)} deliverables approved"
        if required
        else "No deliverables planned",
    }


def next_recommended_deliverable(meta: CampaignMeta) -> PlannedDeliverable | None:
    """Prefer consideration-stage gaps, then ready_to_create, then missing footage."""
    remaining = [
        d
        for d in meta.deliverables
        if d.required
        and d.status not in {"approved", "intentionally_removed"}
        and d.deliverable_id not in meta.finalize_without
    ]
    if not remaining:
        return None
    for preferred in ("consideration", "conversion", "awareness"):
        for d in remaining:
            if d.role == preferred and d.status in {"ready_to_create", "planned", "missing_footage"}:
                return d
    for status in ("ready_to_create", "in_review", "missing_footage", "planned"):
        for d in remaining:
            if d.status == status:
                return d
    return remaining[0]


def why_next_matters(
    item: PlannedDeliverable | dict[str, Any] | None,
    *,
    runway_days: int | None = 4,
) -> str:
    """Explain why the recommended next deliverable matters.

    Accepts a PlannedDeliverable, a plain dict, or None. Never returns None
    or technical identifiers.
    """
    if item is None:
        return "All required deliverables are complete."

    def _field(name: str, default: str = "") -> str:
        if isinstance(item, dict):
            value = item.get(name, default)
        else:
            value = getattr(item, name, default)
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    title = _field("title") or _field("format_name") or "next deliverable"
    role = _field("role", "awareness").lower()

    if role == "consideration":
        gap = "It fills the campaign’s consideration-stage gap"
    elif role == "conversion":
        gap = "It strengthens the campaign’s conversion ask"
    else:
        gap = "It builds awareness for the campaign"

    lead = f"Create the {title} next."
    if runway_days:
        return (
            f"{lead} {gap} and extends the planned publishing runway "
            f"by approximately {runway_days} days."
        )
    return f"{lead} {gap}."


def campaign_slug_from_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (title or "campaign").lower()).strip("-")
    return text[:60] or "campaign"


def _status_from_piece(piece) -> DeliverableStatus:
    key = getattr(piece, "status_key", "") or ""
    if key == "missing_inputs":
        return "missing_footage"
    if key == "ready_to_render":
        return "ready_to_create"
    versions = list(getattr(piece, "versions", []) or [])
    if any(getattr(v, "approval_status", "") == "approved" for v in versions):
        return "approved"
    if any(getattr(v, "approval_status", "") == "rejected" for v in versions):
        return "rejected"
    if any(
        getattr(v, "approval_status", "") in {"awaiting_review", "needs_revision"}
        for v in versions
    ):
        return "in_review"
    if versions:
        return "in_review"
    return "planned"


def _canonical_platform(raw: str) -> str:
    try:
        from src.platforms import canonical_platform

        return canonical_platform(raw) or (raw.split("(")[0].strip() or "Other")
    except Exception:
        return raw.split("(")[0].strip() or "Other"
