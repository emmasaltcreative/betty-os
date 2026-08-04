"""Creative-preference findings and performance-learning foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.models import utc_now_iso
from studio.paths import brand_studio_dir


def creative_preferences_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "creative_preferences.json"


def approval_events_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "approval_events.json"


def performance_records_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "performance_records.json"


def performance_findings_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "performance_findings.json"


@dataclass
class CreativePreferenceFinding:
    finding_id: str
    finding: str
    evidence_count: int
    confidence: str  # low | medium | high
    scope: dict[str, Any]
    created_at: str
    updated_at: str
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreativePreferenceFinding:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ApprovalEvent:
    event_id: str
    brand_id: str
    campaign_id: str
    content_piece_id: str | None
    template_id: str
    render_version_id: str
    finish_version_id: str
    status: str  # approved | needs_revision | rejected
    revision_note: str | None
    edit_decision_id: str | None
    content_type: str
    platform: str
    logo_decision: str | None
    recipe_id: str | None
    resulting_changes: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalEvent:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PerformanceRecord:
    """Traceability + metrics for a published asset. APIs not wired in this sprint."""

    record_id: str
    campaign_id: str
    content_piece_id: str | None
    template_id: str
    render_version_id: str
    finish_version_id: str
    platform: str
    publication_id: str | None = None
    destination_url: str | None = None
    tracking_parameters: dict[str, str] = field(default_factory=dict)
    impressions: int | None = None
    views: int | None = None
    watch_time_seconds: float | None = None
    completion_rate: float | None = None
    saves: int | None = None
    shares: int | None = None
    comments: int | None = None
    outbound_clicks: int | None = None
    landing_page_sessions: int | None = None
    waitlist_signups: int | None = None
    conversion_rate: float | None = None
    recorded_at: str = field(default_factory=utc_now_iso)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PerformanceFinding:
    finding_id: str
    observed_pattern: str
    sample_size: int
    date_range: dict[str, str]
    platform: str
    affected_content_type: str
    confidence: str
    limitations: str
    created_at: str
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceFinding:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def list_approval_events(brand_id: str = DEFAULT_BRAND_ID) -> list[ApprovalEvent]:
    data = load_json(approval_events_path(brand_id), default={"events": []}) or {"events": []}
    return [ApprovalEvent.from_dict(e) for e in data.get("events") or [] if isinstance(e, dict)]


def record_approval_event(event: ApprovalEvent) -> ApprovalEvent:
    path = approval_events_path(event.brand_id)
    data = load_json(path, default={"events": []}) or {"events": []}
    events = list(data.get("events") or [])
    events.append(event.to_dict())
    data["events"] = events
    data["updated_at"] = utc_now_iso()
    atomic_write_json(path, data)
    _maybe_promote_findings(event.brand_id)
    return event


def list_creative_findings(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    active_only: bool = True,
) -> list[CreativePreferenceFinding]:
    data = load_json(creative_preferences_path(brand_id), default={"findings": []}) or {
        "findings": []
    }
    findings = [
        CreativePreferenceFinding.from_dict(f)
        for f in data.get("findings") or []
        if isinstance(f, dict)
    ]
    if active_only:
        return [f for f in findings if f.active]
    return findings


def list_performance_findings(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    active_only: bool = True,
) -> list[PerformanceFinding]:
    data = load_json(performance_findings_path(brand_id), default={"findings": []}) or {
        "findings": []
    }
    findings = [
        PerformanceFinding.from_dict(f) for f in data.get("findings") or [] if isinstance(f, dict)
    ]
    if active_only:
        return [f for f in findings if f.active]
    return findings


def list_performance_records(brand_id: str = DEFAULT_BRAND_ID) -> list[PerformanceRecord]:
    data = load_json(performance_records_path(brand_id), default={"records": []}) or {"records": []}
    return [PerformanceRecord.from_dict(r) for r in data.get("records") or [] if isinstance(r, dict)]


def save_performance_record(record: PerformanceRecord, brand_id: str = DEFAULT_BRAND_ID) -> PerformanceRecord:
    path = performance_records_path(brand_id)
    data = load_json(path, default={"records": []}) or {"records": []}
    records = [r for r in (data.get("records") or []) if r.get("record_id") != record.record_id]
    records.append(record.to_dict())
    data["records"] = records
    data["updated_at"] = utc_now_iso()
    atomic_write_json(path, data)
    return record


def _maybe_promote_findings(brand_id: str) -> None:
    """Create structured preference findings only after repeated evidence (≥3)."""
    events = list_approval_events(brand_id)
    # Logo omit on lifestyle reels after repeated revision/rejection for logo distraction
    logo_omit_signals = [
        e
        for e in events
        if e.status in {"needs_revision", "rejected", "approved"}
        and e.logo_decision == "omit"
        and "lifestyle" in (e.content_type or "").lower()
    ]
    approved_omit = [e for e in logo_omit_signals if e.status == "approved"]
    revised_logo = [
        e
        for e in events
        if e.status == "needs_revision"
        and e.revision_note
        and "logo" in e.revision_note.lower()
    ]

    evidence = len(approved_omit) + len(revised_logo)
    if evidence < 3:
        return

    finding_text = "Avoid persistent logo overlays on OBJ lifestyle reels"
    existing = list_creative_findings(brand_id, active_only=False)
    for item in existing:
        if item.finding == finding_text:
            item.evidence_count = evidence
            item.confidence = "medium" if evidence < 6 else "high"
            item.updated_at = utc_now_iso()
            _write_findings(brand_id, existing)
            return

    now = utc_now_iso()
    existing.append(
        CreativePreferenceFinding(
            finding_id=f"pref_{uuid4().hex[:10]}",
            finding=finding_text,
            evidence_count=evidence,
            confidence="medium" if evidence < 6 else "high",
            scope={
                "brand": brand_id,
                "content_type": "lifestyle_reel",
            },
            created_at=now,
            updated_at=now,
            active=True,
        )
    )
    _write_findings(brand_id, existing)


def _write_findings(brand_id: str, findings: list[CreativePreferenceFinding]) -> None:
    atomic_write_json(
        creative_preferences_path(brand_id),
        {
            "brand_id": brand_id,
            "updated_at": utc_now_iso(),
            "findings": [f.to_dict() for f in findings],
        },
    )


def new_approval_event(
    *,
    brand_id: str,
    campaign_id: str,
    content_piece_id: str | None,
    template_id: str,
    render_version_id: str,
    finish_version_id: str,
    status: str,
    revision_note: str | None = None,
    edit_decision_id: str | None = None,
    content_type: str = "",
    platform: str = "",
    logo_decision: str | None = None,
    recipe_id: str | None = None,
    resulting_changes: dict[str, Any] | None = None,
) -> ApprovalEvent:
    return ApprovalEvent(
        event_id=f"evt_{uuid4().hex[:12]}",
        brand_id=brand_id,
        campaign_id=campaign_id,
        content_piece_id=content_piece_id,
        template_id=template_id,
        render_version_id=render_version_id,
        finish_version_id=finish_version_id,
        status=status,
        revision_note=revision_note,
        edit_decision_id=edit_decision_id,
        content_type=content_type,
        platform=platform,
        logo_decision=logo_decision,
        recipe_id=recipe_id,
        resulting_changes=dict(resulting_changes or {}),
        created_at=utc_now_iso(),
    )
