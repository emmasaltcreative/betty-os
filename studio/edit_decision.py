"""Structured Edit Decision — one best finishing recommendation per run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from studio.models import utc_now_iso

GUIDANCE_SOURCES = (
    "Brand Guide",
    "Production Rules",
    "platform requirement",
    "asset analysis",
    "performance finding",
    "prior approval feedback",
    "campaign objective",
    "template assignment",
)

CLEANUP_CLASSIFICATIONS = (
    "not_worth_changing",
    "deterministic_adjustment_sufficient",
    "ai_edit_supported",
    "ai_provider_required",
    "human_input_required",
    "prohibited_product_or_identity",
)

EXECUTION_STATES = (
    "decision_generated",
    "edit_partially_applied",
    "edit_fully_applied",
    "unsupported_action",
    "failed_action",
)

LOGO_CHOICES = ("required", "optional", "omit")


@dataclass
class DecisionField:
    """One decided value with rationale and guidance provenance."""

    value: Any
    reason: str
    source: str  # one of GUIDANCE_SOURCES (or comma-joined)
    applied: bool = True
    unsupported_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DecisionField:
        if not data:
            return cls(value=None, reason="", source="Brand Guide")
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class CleanupRecommendation:
    issue: str
    classification: str
    reason: str
    detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CleanupRecommendation:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AppliedAction:
    label: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NotAppliedAction:
    label: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionReport:
    """Honest accounting of what the automatic finish actually did."""

    state: str  # EXECUTION_STATES
    applied: list[AppliedAction] = field(default_factory=list)
    not_applied: list[NotAppliedAction] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "applied": [a.to_dict() for a in self.applied],
            "not_applied": [a.to_dict() for a in self.not_applied],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExecutionReport:
        if not data:
            return cls(state="decision_generated")
        return cls(
            state=str(data.get("state") or "decision_generated"),
            applied=[AppliedAction(**a) for a in (data.get("applied") or []) if isinstance(a, dict)],
            not_applied=[
                NotAppliedAction(**a) for a in (data.get("not_applied") or []) if isinstance(a, dict)
            ],
            summary=str(data.get("summary") or ""),
        )


def _field_dict(data: dict[str, Any] | None, key: str) -> DecisionField | None:
    raw = (data or {}).get(key)
    if raw is None:
        return None
    if isinstance(raw, dict):
        return DecisionField.from_dict(raw)
    return DecisionField(value=raw, reason="", source="Brand Guide")


@dataclass
class EditDecision:
    """Complete structured edit recommendation persisted with a finish version."""

    decision_id: str
    brand_id: str
    campaign_id: str
    content_piece_id: str | None
    template_id: str
    platform: str
    campaign_goal: str
    piece_objective: str
    media_type: str
    source_file: str
    parent_render_version_id: str
    parent_finish_version_id: str | None

    selected_source_assets: DecisionField
    clip_order: DecisionField
    trim_points: DecisionField
    target_duration: DecisionField
    crop_strategy: DecisionField
    pacing: DecisionField
    transitions: DecisionField
    overlay_copy: DecisionField
    overlay_timing: DecisionField
    cta_copy: DecisionField
    cta_timing: DecisionField
    logo_decision: DecisionField
    logo_placement: DecisionField
    lighting: DecisionField
    color: DecisionField
    color_recipe: DecisionField
    grain: DecisionField
    sharpening: DecisionField
    vignette: DecisionField
    audio: DecisionField
    export_settings: DecisionField
    selective_cleanup: list[CleanupRecommendation]

    rationale: str
    confidence: float  # 0..1
    unsupported_actions: list[str]
    major_decisions: list[str]  # ≤3 user-facing highlights
    creative_review_score: float  # 0..100 predicted / heuristic score
    brand_guide_loaded: bool
    production_rules_loaded: bool
    guidance_conflict_resolutions: list[str]
    created_at: str = field(default_factory=utc_now_iso)
    revision_of: str | None = None
    revision_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EditDecision | None:
        if not data:
            return None
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        payload: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if key == "selective_cleanup":
                payload[key] = [
                    CleanupRecommendation.from_dict(item) if isinstance(item, dict) else item
                    for item in (value or [])
                ]
            elif key in {
                "selected_source_assets",
                "clip_order",
                "trim_points",
                "target_duration",
                "crop_strategy",
                "pacing",
                "transitions",
                "overlay_copy",
                "overlay_timing",
                "cta_copy",
                "cta_timing",
                "logo_decision",
                "logo_placement",
                "lighting",
                "color",
                "color_recipe",
                "grain",
                "sharpening",
                "vignette",
                "audio",
                "export_settings",
            }:
                payload[key] = DecisionField.from_dict(value if isinstance(value, dict) else None)
            else:
                payload[key] = value
        try:
            return cls(**payload)
        except TypeError:
            return None

    def major_decision_summaries(self, *, limit: int = 3) -> list[str]:
        items = [str(x).strip() for x in self.major_decisions if str(x).strip()]
        return items[:limit]
