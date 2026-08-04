"""Lightweight Studio learning records.

These records are evidence for future defaults. They do not fine-tune a model or
publish anything; BettyOS only promotes a preference after repeated approvals or
revision signals in the persisted Studio history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.models import utc_now_iso
from studio.paths import brand_studio_dir

PREFERENCE_EVIDENCE_THRESHOLD = 3


@dataclass
class CreativePreferenceFinding:
    finding_id: str
    brand_id: str
    statement: str
    context: str
    evidence_count: int
    evidence_keys: list[str]
    status: str
    source: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CreativePreferenceFinding":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ApprovalEvent:
    event_id: str
    brand_id: str
    campaign_id: str
    content_piece_id: str | None
    finish_version_id: str
    parent_finish_version_id: str | None
    approval_status: str
    revision_note: str | None
    edit_decision: dict[str, Any]
    creative_review_score: float | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalEvent":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PerformanceRecord:
    record_id: str
    brand_id: str
    campaign_id: str
    content_piece_id: str | None
    finish_version_id: str
    platform: str
    metric_name: str
    metric_value: float
    metric_unit: str
    observed_at: str
    notes: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PerformanceFinding:
    finding_id: str
    brand_id: str
    statement: str
    metric_name: str
    evidence_count: int
    evidence_record_ids: list[str]
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceFinding":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def _path(brand_id: str, filename: str):
    return brand_studio_dir(brand_id) / filename


def _load_rows(brand_id: str, filename: str, key: str) -> list[dict[str, Any]]:
    data = load_json(_path(brand_id, filename), default={key: []})
    if not isinstance(data, dict):
        return []
    rows = data.get(key) or []
    return [r for r in rows if isinstance(r, dict)]


def _save_rows(brand_id: str, filename: str, key: str, rows: list[dict[str, Any]]) -> None:
    atomic_write_json(
        _path(brand_id, filename),
        {"brand_id": brand_id, "updated_at": utc_now_iso(), key: rows},
    )


def list_creative_preferences(brand_id: str = DEFAULT_BRAND_ID) -> list[CreativePreferenceFinding]:
    return [
        CreativePreferenceFinding.from_dict(x)
        for x in _load_rows(brand_id, "creative_preferences.json", "findings")
    ]


def list_approval_events(brand_id: str = DEFAULT_BRAND_ID) -> list[ApprovalEvent]:
    return [
        ApprovalEvent.from_dict(x)
        for x in _load_rows(brand_id, "approval_events.json", "events")
    ]


def list_performance_records(brand_id: str = DEFAULT_BRAND_ID) -> list[PerformanceRecord]:
    return [
        PerformanceRecord.from_dict(x)
        for x in _load_rows(brand_id, "performance_records.json", "records")
    ]


def list_performance_findings(brand_id: str = DEFAULT_BRAND_ID) -> list[PerformanceFinding]:
    return [
        PerformanceFinding.from_dict(x)
        for x in _load_rows(brand_id, "performance_findings.json", "findings")
    ]


def new_approval_event(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    campaign_id: str,
    content_piece_id: str | None,
    finish_version_id: str,
    parent_finish_version_id: str | None,
    approval_status: str,
    revision_note: str | None = None,
    edit_decision: dict[str, Any] | None = None,
    creative_review_score: float | None = None,
) -> ApprovalEvent:
    return ApprovalEvent(
        event_id=f"ae_{uuid4().hex[:12]}",
        brand_id=brand_id,
        campaign_id=campaign_id,
        content_piece_id=content_piece_id,
        finish_version_id=finish_version_id,
        parent_finish_version_id=parent_finish_version_id,
        approval_status=approval_status,
        revision_note=revision_note,
        edit_decision=dict(edit_decision or {}),
        creative_review_score=creative_review_score,
        created_at=utc_now_iso(),
    )


def record_approval_event(event: ApprovalEvent) -> ApprovalEvent:
    events = list_approval_events(event.brand_id)
    if not any(e.event_id == event.event_id for e in events):
        events.append(event)
        _save_rows(event.brand_id, "approval_events.json", "events", [e.to_dict() for e in events])
    _update_creative_preferences(event)
    return event


def _update_creative_preferences(event: ApprovalEvent) -> None:
    candidates = _preference_candidates(event)
    if not candidates:
        return
    findings = list_creative_preferences(event.brand_id)
    by_statement = {f.statement: f for f in findings}
    changed = False
    for statement, context in candidates:
        finding = by_statement.get(statement)
        if finding is None:
            now = utc_now_iso()
            finding = CreativePreferenceFinding(
                finding_id=f"cpf_{uuid4().hex[:10]}",
                brand_id=event.brand_id,
                statement=statement,
                context=context,
                evidence_count=0,
                evidence_keys=[],
                status="candidate",
                source="approval_events",
                created_at=now,
                updated_at=now,
            )
            findings.append(finding)
            by_statement[statement] = finding
        key = event.event_id
        if key not in finding.evidence_keys:
            finding.evidence_keys.append(key)
            finding.evidence_count = len(finding.evidence_keys)
            if finding.evidence_count >= PREFERENCE_EVIDENCE_THRESHOLD:
                finding.status = "promoted"
            finding.updated_at = utc_now_iso()
            changed = True
    if changed:
        _save_rows(
            event.brand_id,
            "creative_preferences.json",
            "findings",
            [f.to_dict() for f in findings],
        )


def _preference_candidates(event: ApprovalEvent) -> list[tuple[str, str]]:
    note = (event.revision_note or "").lower()
    decision = event.edit_decision or {}
    content_type = str(decision.get("content_type") or "").lower()
    platform = str(decision.get("platform") or "").lower()
    logo_value = ((decision.get("logo_decision") or {}).get("value") or "")
    recipe = str(decision.get("recipe_id") or "")
    is_lifestyle_reel = "lifestyle" in content_type and ("reel" in platform or "instagram" in platform)
    candidates: list[tuple[str, str]] = []
    if is_lifestyle_reel and (
        "logo" in note
        or str(logo_value).lower() == "omit"
        or event.approval_status in {"approved", "needs_revision"}
    ):
        candidates.append(
            (
                "Avoid persistent logo overlays on OBJ lifestyle reels",
                f"content_type={content_type}; platform={platform}; recipe={recipe}",
            )
        )
    return candidates


def save_performance_record(record: PerformanceRecord) -> PerformanceRecord:
    records = list_performance_records(record.brand_id)
    existing = [r for r in records if r.record_id != record.record_id]
    existing.append(record)
    _save_rows(
        record.brand_id,
        "performance_records.json",
        "records",
        [r.to_dict() for r in existing],
    )
    return record
