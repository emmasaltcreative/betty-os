"""Structured Edit Decision — one best finishing recommendation per run.

Canonical schema merges the identity-rich Automatic Studio decision model with
provenance fields (brand guide / production rule file lists) and dual-readable
execution/cleanup shapes so both historical on-disk formats deserialize cleanly.
"""

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

_DECISION_FIELD_NAMES = (
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
)


def _known(cls: type) -> set[str]:
    return {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]


@dataclass
class DecisionField:
    """One decided value with rationale and guidance provenance."""

    value: Any = None
    reason: str = ""
    source: str = ""
    applied: bool = True
    unsupported_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> DecisionField:
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return cls(value=data, reason="", source="Brand Guide")
        return cls(**{k: v for k, v in data.items() if k in _known(cls)})


@dataclass
class CleanupRecommendation:
    """Selective cleanup honesty record.

    Primary fields follow the Automatic Studio engine (`issue` / `classification`).
    Older `category` / `recommendation` / `unsupported_reason` keys still deserialize.
    """

    issue: str = ""
    classification: str = "ai_provider_required"
    reason: str = ""
    detected: bool = False
    applied: bool = False
    source: str = "automatic_studio"
    unsupported_reason: str | None = "ai_provider_required"

    def __post_init__(self) -> None:
        if not self.issue and self.classification:
            pass
        if self.unsupported_reason is None and self.classification == "ai_provider_required":
            self.unsupported_reason = "ai_provider_required"

    @property
    def category(self) -> str:
        return self.issue

    @property
    def recommendation(self) -> str:
        return self.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue": self.issue,
            "classification": self.classification,
            "reason": self.reason,
            "detected": self.detected,
            "applied": self.applied,
            "source": self.source,
            "unsupported_reason": self.unsupported_reason,
            # Dual-read aliases for older consumers
            "category": self.issue,
            "recommendation": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CleanupRecommendation:
        if not isinstance(data, dict):
            return cls()
        issue = str(data.get("issue") or data.get("category") or "")
        classification = str(
            data.get("classification")
            or data.get("unsupported_reason")
            or "ai_provider_required"
        )
        reason = str(data.get("reason") or data.get("recommendation") or "")
        return cls(
            issue=issue,
            classification=classification,
            reason=reason,
            detected=bool(data.get("detected", False)),
            applied=bool(data.get("applied", False)),
            source=str(data.get("source") or "automatic_studio"),
            unsupported_reason=data.get("unsupported_reason") or classification,
        )


@dataclass
class AppliedAction:
    label: str = ""
    detail: str = ""
    action: str = ""
    value: Any = None
    reason: str = ""
    source: str = "automatic_studio"

    def __post_init__(self) -> None:
        if not self.label and self.action:
            self.label = self.action
        if not self.action and self.label:
            self.action = self.label
        if not self.reason and self.detail:
            self.reason = self.detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "detail": self.detail,
            "action": self.action or self.label,
            "value": self.value,
            "reason": self.reason,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppliedAction:
        if not isinstance(data, dict):
            return cls()
        label = str(data.get("label") or data.get("action") or "")
        return cls(
            label=label,
            detail=str(data.get("detail") or data.get("reason") or ""),
            action=str(data.get("action") or label),
            value=data.get("value"),
            reason=str(data.get("reason") or data.get("detail") or ""),
            source=str(data.get("source") or "automatic_studio"),
        )


@dataclass
class NotAppliedAction:
    label: str = ""
    reason: str = ""
    action: str = ""
    source: str = "automatic_studio"
    unsupported_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.label and self.action:
            self.label = self.action
        if not self.action and self.label:
            self.action = self.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "reason": self.reason,
            "action": self.action or self.label,
            "source": self.source,
            "unsupported_reason": self.unsupported_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotAppliedAction:
        if not isinstance(data, dict):
            return cls()
        label = str(data.get("label") or data.get("action") or "")
        return cls(
            label=label,
            reason=str(data.get("reason") or ""),
            action=str(data.get("action") or label),
            source=str(data.get("source") or "automatic_studio"),
            unsupported_reason=data.get("unsupported_reason"),
        )


@dataclass
class ExecutionReport:
    """Honest accounting of what the automatic finish actually did."""

    state: str = "decision_generated"
    applied: list[AppliedAction] = field(default_factory=list)
    not_applied: list[NotAppliedAction] = field(default_factory=list)
    summary: str = ""
    warnings_acknowledged: list[str] = field(default_factory=list)
    render_engine: str = "studio"
    notes: list[str] = field(default_factory=list)

    @property
    def applied_actions(self) -> list[AppliedAction]:
        return self.applied

    @property
    def not_applied_actions(self) -> list[NotAppliedAction]:
        return self.not_applied

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "applied": [a.to_dict() for a in self.applied],
            "not_applied": [a.to_dict() for a in self.not_applied],
            "summary": self.summary,
            "warnings_acknowledged": list(self.warnings_acknowledged),
            "render_engine": self.render_engine,
            "notes": list(self.notes),
            # Dual-read aliases
            "applied_actions": [a.to_dict() for a in self.applied],
            "not_applied_actions": [a.to_dict() for a in self.not_applied],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExecutionReport:
        if not isinstance(data, dict):
            return cls()
        applied_raw = data.get("applied") or data.get("applied_actions") or []
        not_applied_raw = data.get("not_applied") or data.get("not_applied_actions") or []
        return cls(
            state=str(data.get("state") or "decision_generated"),
            applied=[
                AppliedAction.from_dict(a) for a in applied_raw if isinstance(a, dict)
            ],
            not_applied=[
                NotAppliedAction.from_dict(a) for a in not_applied_raw if isinstance(a, dict)
            ],
            summary=str(data.get("summary") or ""),
            warnings_acknowledged=list(data.get("warnings_acknowledged") or []),
            render_engine=str(data.get("render_engine") or "studio"),
            notes=list(data.get("notes") or []),
        )


@dataclass
class EditDecision:
    """Complete structured edit recommendation persisted with a finish version."""

    decision_id: str = ""
    brand_id: str = ""
    campaign_id: str = ""
    content_piece_id: str | None = None
    template_id: str = ""
    platform: str = ""
    campaign_goal: str = ""
    piece_objective: str = ""
    media_type: str = ""
    source_file: str = ""
    parent_render_version_id: str = ""
    parent_finish_version_id: str | None = None

    selected_source_assets: DecisionField = field(default_factory=DecisionField)
    clip_order: DecisionField = field(default_factory=DecisionField)
    trim_points: DecisionField = field(default_factory=DecisionField)
    target_duration: DecisionField = field(default_factory=DecisionField)
    crop_strategy: DecisionField = field(default_factory=DecisionField)
    pacing: DecisionField = field(default_factory=DecisionField)
    transitions: DecisionField = field(default_factory=DecisionField)
    overlay_copy: DecisionField = field(default_factory=DecisionField)
    overlay_timing: DecisionField = field(default_factory=DecisionField)
    cta_copy: DecisionField = field(default_factory=DecisionField)
    cta_timing: DecisionField = field(default_factory=DecisionField)
    logo_decision: DecisionField = field(default_factory=DecisionField)
    logo_placement: DecisionField = field(default_factory=DecisionField)
    lighting: DecisionField = field(default_factory=DecisionField)
    color: DecisionField = field(default_factory=DecisionField)
    color_recipe: DecisionField = field(default_factory=DecisionField)
    grain: DecisionField = field(default_factory=DecisionField)
    sharpening: DecisionField = field(default_factory=DecisionField)
    vignette: DecisionField = field(default_factory=DecisionField)
    audio: DecisionField = field(default_factory=DecisionField)
    export_settings: DecisionField = field(default_factory=DecisionField)
    selective_cleanup: list[CleanupRecommendation] = field(default_factory=list)

    rationale: str = ""
    confidence: float = 0.0
    unsupported_actions: list[str] = field(default_factory=list)
    major_decisions: list[str] = field(default_factory=list)
    creative_review_score: float | None = None
    brand_guide_loaded: bool = False
    production_rules_loaded: bool = False
    brand_guide_files: list[str] = field(default_factory=list)
    production_rule_files: list[str] = field(default_factory=list)
    guidance_conflict_resolutions: list[str] = field(default_factory=list)
    recipe_id: str | None = None
    content_type: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    revision_of: str | None = None
    revision_note: str | None = None

    def __post_init__(self) -> None:
        self.major_decisions = [str(x).strip() for x in self.major_decisions if str(x).strip()][:3]
        if not self.recipe_id:
            recipe_val = self.color_recipe.value if self.color_recipe else None
            if isinstance(recipe_val, dict):
                self.recipe_id = recipe_val.get("recipe_id")
            elif isinstance(recipe_val, str):
                self.recipe_id = recipe_val
        # Normalize legacy unsupported_actions that were dict/NotAppliedAction shaped
        normalized: list[str] = []
        for item in self.unsupported_actions:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(str(item.get("reason") or item.get("action") or item.get("label") or ""))
            else:
                normalized.append(str(getattr(item, "reason", None) or getattr(item, "label", "") or item))
        self.unsupported_actions = [x for x in normalized if x]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision_id": self.decision_id,
            "brand_id": self.brand_id,
            "campaign_id": self.campaign_id,
            "content_piece_id": self.content_piece_id,
            "template_id": self.template_id,
            "platform": self.platform,
            "campaign_goal": self.campaign_goal,
            "piece_objective": self.piece_objective,
            "media_type": self.media_type,
            "source_file": self.source_file,
            "parent_render_version_id": self.parent_render_version_id,
            "parent_finish_version_id": self.parent_finish_version_id,
        }
        for name in _DECISION_FIELD_NAMES:
            payload[name] = getattr(self, name).to_dict()
        payload.update(
            {
                "selective_cleanup": [x.to_dict() for x in self.selective_cleanup],
                "rationale": self.rationale,
                "confidence": self.confidence,
                "unsupported_actions": list(self.unsupported_actions),
                "major_decisions": list(self.major_decisions[:3]),
                "creative_review_score": self.creative_review_score,
                "brand_guide_loaded": self.brand_guide_loaded,
                "production_rules_loaded": self.production_rules_loaded,
                "brand_guide_files": list(self.brand_guide_files),
                "production_rule_files": list(self.production_rule_files),
                "guidance_conflict_resolutions": list(self.guidance_conflict_resolutions),
                "recipe_id": self.recipe_id,
                "content_type": self.content_type,
                "created_at": self.created_at,
                "revision_of": self.revision_of,
                "revision_note": self.revision_note,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EditDecision | None:
        if not data:
            return None
        if not isinstance(data, dict):
            return None
        kwargs: dict[str, Any] = {}
        for name in _DECISION_FIELD_NAMES:
            kwargs[name] = DecisionField.from_dict(data.get(name))
        kwargs["selective_cleanup"] = [
            CleanupRecommendation.from_dict(x)
            for x in (data.get("selective_cleanup") or [])
            if isinstance(x, dict)
        ]
        for key in (
            "decision_id",
            "brand_id",
            "campaign_id",
            "content_piece_id",
            "template_id",
            "platform",
            "campaign_goal",
            "piece_objective",
            "media_type",
            "source_file",
            "parent_render_version_id",
            "parent_finish_version_id",
            "rationale",
            "confidence",
            "unsupported_actions",
            "major_decisions",
            "creative_review_score",
            "brand_guide_loaded",
            "production_rules_loaded",
            "brand_guide_files",
            "production_rule_files",
            "guidance_conflict_resolutions",
            "recipe_id",
            "content_type",
            "created_at",
            "revision_of",
            "revision_note",
        ):
            if key in data:
                kwargs[key] = data[key]
        try:
            return cls(**kwargs)
        except TypeError:
            return None

    def major_decision_summaries(self, *, limit: int = 3) -> list[str]:
        items = [str(x).strip() for x in self.major_decisions if str(x).strip()]
        return items[:limit]
