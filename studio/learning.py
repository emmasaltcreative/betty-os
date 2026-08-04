"""Creative-preference findings and performance-learning foundation.

Persists approval evidence, promotes creative preferences after repeated signals,
and holds a performance-records schema for future learning. Canonical on-disk
shape matches the Automatic Studio engine; dual-read helpers accept older fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.models import utc_now_iso
from studio.paths import brand_studio_dir

PREFERENCE_EVIDENCE_THRESHOLD = 3
LOGO_OMIT_FINDING = "Avoid persistent logo overlays on OBJ lifestyle reels"


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
    finding: str = ""
    evidence_count: int = 0
    confidence: str = "low"  # low | medium | high
    scope: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    active: bool = True
    # Dual-compat / evidence tracking
    brand_id: str = ""
    statement: str = ""
    context: str = ""
    evidence_keys: list[str] = field(default_factory=list)
    status: str = "candidate"  # candidate | promoted
    source: str = "approval_events"

    def __post_init__(self) -> None:
        if not self.finding and self.statement:
            self.finding = self.statement
        if not self.statement and self.finding:
            self.statement = self.finding
        if self.evidence_count <= 0 and self.evidence_keys:
            self.evidence_count = len(self.evidence_keys)
        if self.status == "candidate" and (
            self.active and self.evidence_count >= PREFERENCE_EVIDENCE_THRESHOLD
        ):
            self.status = "promoted"
        if self.status == "promoted":
            self.active = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding": self.finding or self.statement,
            "evidence_count": self.evidence_count,
            "confidence": self.confidence,
            "scope": dict(self.scope),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active": self.active,
            "brand_id": self.brand_id,
            "statement": self.statement or self.finding,
            "context": self.context,
            "evidence_keys": list(self.evidence_keys),
            "status": self.status,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreativePreferenceFinding:
        known = _known(cls)
        payload = {k: v for k, v in data.items() if k in known}
        finding = CreativePreferenceFinding(**payload)
        return finding


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
    # Dual-compat fields from the other Automatic Studio branch
    parent_finish_version_id: str | None = None
    edit_decision: dict[str, Any] = field(default_factory=dict)
    creative_review_score: float | None = None

    @property
    def approval_status(self) -> str:
        return self.status

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["approval_status"] = self.status
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalEvent:
        payload = dict(data)
        if "status" not in payload and "approval_status" in payload:
            payload["status"] = payload["approval_status"]
        # Fill required defaults for leaner historical rows
        payload.setdefault("template_id", "")
        payload.setdefault("render_version_id", "")
        payload.setdefault("edit_decision_id", None)
        payload.setdefault("content_type", "")
        payload.setdefault("platform", "")
        payload.setdefault("logo_decision", None)
        payload.setdefault("recipe_id", None)
        payload.setdefault("resulting_changes", {})
        payload.setdefault("revision_note", None)
        known = _known(cls)
        return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass
class PerformanceRecord:
    """Traceability + metrics for a published asset.

    Supports both the rich Automatic Studio metrics shape and the leaner
    metric_name / metric_value rows from the finishing-engine branch.
    """

    record_id: str
    campaign_id: str
    content_piece_id: str | None = None
    template_id: str = ""
    render_version_id: str = ""
    finish_version_id: str = ""
    platform: str = ""
    brand_id: str = DEFAULT_BRAND_ID
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
    metric_name: str = ""
    metric_value: float | None = None
    metric_unit: str = ""
    observed_at: str = ""
    recorded_at: str = field(default_factory=utc_now_iso)
    notes: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceRecord:
        known = _known(cls)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PerformanceFinding:
    finding_id: str
    observed_pattern: str = ""
    sample_size: int = 0
    date_range: dict[str, str] = field(default_factory=dict)
    platform: str = ""
    affected_content_type: str = ""
    confidence: str = "low"
    limitations: str = ""
    created_at: str = ""
    active: bool = True
    # Dual-compat
    brand_id: str = ""
    statement: str = ""
    metric_name: str = ""
    evidence_count: int = 0
    evidence_record_ids: list[str] = field(default_factory=list)
    status: str = "candidate"
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.observed_pattern and self.statement:
            self.observed_pattern = self.statement
        if not self.statement and self.observed_pattern:
            self.statement = self.observed_pattern

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceFinding:
        known = _known(cls)
        return cls(**{k: v for k, v in data.items() if k in known})


def _known(cls: type) -> set[str]:
    return {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]


def list_approval_events(brand_id: str = DEFAULT_BRAND_ID) -> list[ApprovalEvent]:
    data = load_json(approval_events_path(brand_id), default={"events": []}) or {"events": []}
    return [ApprovalEvent.from_dict(e) for e in data.get("events") or [] if isinstance(e, dict)]


def record_approval_event(event: ApprovalEvent) -> ApprovalEvent:
    path = approval_events_path(event.brand_id)
    data = load_json(path, default={"events": []}) or {"events": []}
    events = [e for e in (data.get("events") or []) if isinstance(e, dict)]
    # Deduplicate by event_id (finishing-engine behavior)
    if not any(e.get("event_id") == event.event_id for e in events):
        events.append(event.to_dict())
    data["events"] = events
    data["updated_at"] = utc_now_iso()
    atomic_write_json(path, data)
    _maybe_promote_findings(event.brand_id)
    _update_creative_preferences_from_event(event)
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
        return [f for f in findings if f.active or f.status == "promoted"]
    return findings


def list_creative_preferences(brand_id: str = DEFAULT_BRAND_ID) -> list[CreativePreferenceFinding]:
    """Alias used by the finishing-engine branch."""
    return list_creative_findings(brand_id, active_only=False)


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


def save_performance_record(
    record: PerformanceRecord,
    brand_id: str | None = None,
) -> PerformanceRecord:
    target_brand = brand_id or record.brand_id or DEFAULT_BRAND_ID
    if not record.brand_id:
        record.brand_id = target_brand
    path = performance_records_path(target_brand)
    data = load_json(path, default={"records": []}) or {"records": []}
    records = [r for r in (data.get("records") or []) if r.get("record_id") != record.record_id]
    records.append(record.to_dict())
    data["records"] = records
    data["updated_at"] = utc_now_iso()
    data["brand_id"] = target_brand
    atomic_write_json(path, data)
    return record


def _maybe_promote_findings(brand_id: str) -> None:
    """Create structured preference findings only after repeated evidence (≥3)."""
    events = list_approval_events(brand_id)
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
    if evidence < PREFERENCE_EVIDENCE_THRESHOLD:
        return

    existing = list_creative_findings(brand_id, active_only=False)
    for item in existing:
        if item.finding == LOGO_OMIT_FINDING or item.statement == LOGO_OMIT_FINDING:
            item.evidence_count = max(item.evidence_count, evidence)
            item.confidence = "medium" if evidence < 6 else "high"
            item.updated_at = utc_now_iso()
            item.active = True
            item.status = "promoted"
            item.statement = LOGO_OMIT_FINDING
            item.finding = LOGO_OMIT_FINDING
            _write_findings(brand_id, existing)
            return

    now = utc_now_iso()
    existing.append(
        CreativePreferenceFinding(
            finding_id=f"pref_{uuid4().hex[:10]}",
            finding=LOGO_OMIT_FINDING,
            statement=LOGO_OMIT_FINDING,
            evidence_count=evidence,
            confidence="medium" if evidence < 6 else "high",
            scope={"brand": brand_id, "content_type": "lifestyle_reel"},
            created_at=now,
            updated_at=now,
            active=True,
            brand_id=brand_id,
            status="promoted",
            source="approval_events",
        )
    )
    _write_findings(brand_id, existing)


def _update_creative_preferences_from_event(event: ApprovalEvent) -> None:
    """Evidence-keyed preference promotion from the finishing-engine branch."""
    candidates = _preference_candidates(event)
    if not candidates:
        return
    findings = list_creative_findings(event.brand_id, active_only=False)
    by_statement = {(f.statement or f.finding): f for f in findings}
    changed = False
    for statement, context in candidates:
        finding = by_statement.get(statement)
        if finding is None:
            now = utc_now_iso()
            finding = CreativePreferenceFinding(
                finding_id=f"cpf_{uuid4().hex[:10]}",
                brand_id=event.brand_id,
                finding=statement,
                statement=statement,
                context=context,
                evidence_count=0,
                evidence_keys=[],
                status="candidate",
                source="approval_events",
                created_at=now,
                updated_at=now,
                active=True,
                confidence="low",
                scope={"brand": event.brand_id, "content_type": event.content_type},
            )
            findings.append(finding)
            by_statement[statement] = finding
        key = event.event_id
        if key not in finding.evidence_keys:
            finding.evidence_keys.append(key)
            finding.evidence_count = max(finding.evidence_count, len(finding.evidence_keys))
            if finding.evidence_count >= PREFERENCE_EVIDENCE_THRESHOLD:
                finding.status = "promoted"
                finding.active = True
                finding.confidence = "medium" if finding.evidence_count < 6 else "high"
            finding.updated_at = utc_now_iso()
            changed = True
    if changed:
        _write_findings(event.brand_id, findings)


def _preference_candidates(event: ApprovalEvent) -> list[tuple[str, str]]:
    note = (event.revision_note or "").lower()
    decision = event.edit_decision or {}
    content_type = str(
        event.content_type or decision.get("content_type") or ""
    ).lower()
    platform = str(event.platform or decision.get("platform") or "").lower()
    logo_value = event.logo_decision
    if logo_value is None and isinstance(decision.get("logo_decision"), dict):
        logo_value = decision["logo_decision"].get("value")
    recipe = str(event.recipe_id or decision.get("recipe_id") or "")
    is_lifestyle_reel = "lifestyle" in content_type and (
        "reel" in platform or "instagram" in platform or "reel" in content_type
    )
    candidates: list[tuple[str, str]] = []
    if is_lifestyle_reel and (
        "logo" in note
        or str(logo_value or "").lower() == "omit"
        or event.status in {"approved", "needs_revision"}
    ):
        candidates.append(
            (
                LOGO_OMIT_FINDING,
                f"content_type={content_type}; platform={platform}; recipe={recipe}",
            )
        )
    return candidates


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
    brand_id: str = DEFAULT_BRAND_ID,
    campaign_id: str,
    content_piece_id: str | None,
    finish_version_id: str,
    status: str | None = None,
    approval_status: str | None = None,
    revision_note: str | None = None,
    template_id: str = "",
    render_version_id: str = "",
    edit_decision_id: str | None = None,
    content_type: str = "",
    platform: str = "",
    logo_decision: str | None = None,
    recipe_id: str | None = None,
    resulting_changes: dict[str, Any] | None = None,
    parent_finish_version_id: str | None = None,
    edit_decision: dict[str, Any] | None = None,
    creative_review_score: float | None = None,
) -> ApprovalEvent:
    resolved_status = status or approval_status or "approved"
    decision = dict(edit_decision or {})
    if edit_decision_id is None:
        edit_decision_id = decision.get("decision_id")
    if not content_type:
        content_type = str(decision.get("content_type") or "")
    if not platform:
        platform = str(decision.get("platform") or "")
    if logo_decision is None and isinstance(decision.get("logo_decision"), dict):
        logo_decision = decision["logo_decision"].get("value")
    if recipe_id is None:
        recipe_id = decision.get("recipe_id")
        recipe_val = decision.get("color_recipe")
        if not recipe_id and isinstance(recipe_val, dict):
            inner = recipe_val.get("value") if "value" in recipe_val else recipe_val
            if isinstance(inner, dict):
                recipe_id = inner.get("recipe_id")
    return ApprovalEvent(
        event_id=f"evt_{uuid4().hex[:12]}",
        brand_id=brand_id,
        campaign_id=campaign_id,
        content_piece_id=content_piece_id,
        template_id=template_id,
        render_version_id=render_version_id,
        finish_version_id=finish_version_id,
        status=resolved_status,
        revision_note=revision_note,
        edit_decision_id=edit_decision_id,
        content_type=content_type,
        platform=platform,
        logo_decision=str(logo_decision) if logo_decision else None,
        recipe_id=recipe_id,
        resulting_changes=dict(resulting_changes or {"approval_status": resolved_status}),
        created_at=utc_now_iso(),
        parent_finish_version_id=parent_finish_version_id,
        edit_decision=decision,
        creative_review_score=creative_review_score,
    )
