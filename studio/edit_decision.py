"""Structured automatic Studio edit decisions.

The decision is the record of BettyOS's single best recommendation. It is
persisted beside the immutable finish version so a reviewer can see what was
applied and what was intentionally left unsupported.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _known(cls: type) -> set[str]:
    return {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]


@dataclass
class DecisionField:
    value: Any = None
    reason: str = ""
    source: str = ""
    applied: bool = True
    unsupported_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "DecisionField":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return cls(value=data)
        return cls(**{k: v for k, v in data.items() if k in _known(cls)})


@dataclass
class CleanupRecommendation:
    category: str
    recommendation: str
    reason: str
    source: str = "automatic_studio"
    applied: bool = False
    unsupported_reason: str | None = "ai_provider_required"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CleanupRecommendation":
        return cls(**{k: v for k, v in data.items() if k in _known(cls)})


@dataclass
class AppliedAction:
    action: str
    value: Any = None
    reason: str = ""
    source: str = "automatic_studio"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppliedAction":
        return cls(**{k: v for k, v in data.items() if k in _known(cls)})


@dataclass
class NotAppliedAction:
    action: str
    reason: str
    source: str = "automatic_studio"
    unsupported_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotAppliedAction":
        return cls(**{k: v for k, v in data.items() if k in _known(cls)})


@dataclass
class ExecutionReport:
    applied_actions: list[AppliedAction] = field(default_factory=list)
    not_applied_actions: list[NotAppliedAction] = field(default_factory=list)
    warnings_acknowledged: list[str] = field(default_factory=list)
    render_engine: str = "studio"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied_actions": [a.to_dict() for a in self.applied_actions],
            "not_applied_actions": [a.to_dict() for a in self.not_applied_actions],
            "warnings_acknowledged": list(self.warnings_acknowledged),
            "render_engine": self.render_engine,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ExecutionReport":
        if not isinstance(data, dict):
            return cls()
        return cls(
            applied_actions=[
                AppliedAction.from_dict(x)
                for x in data.get("applied_actions", [])
                if isinstance(x, dict)
            ],
            not_applied_actions=[
                NotAppliedAction.from_dict(x)
                for x in data.get("not_applied_actions", [])
                if isinstance(x, dict)
            ],
            warnings_acknowledged=list(data.get("warnings_acknowledged") or []),
            render_engine=str(data.get("render_engine") or "studio"),
            notes=list(data.get("notes") or []),
        )


@dataclass
class EditDecision:
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
    unsupported_actions: list[NotAppliedAction] = field(default_factory=list)
    major_decisions: list[str] = field(default_factory=list)
    creative_review_score: float | None = None
    brand_guide_loaded: bool = False
    production_rules_loaded: bool = False
    brand_guide_files: list[str] = field(default_factory=list)
    production_rule_files: list[str] = field(default_factory=list)
    recipe_id: str | None = None
    platform: str = ""
    content_type: str = ""

    def __post_init__(self) -> None:
        self.major_decisions = list(self.major_decisions[:3])

    def to_dict(self) -> dict[str, Any]:
        field_names = [
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
        ]
        payload: dict[str, Any] = {name: getattr(self, name).to_dict() for name in field_names}
        payload.update(
            {
                "selective_cleanup": [x.to_dict() for x in self.selective_cleanup],
                "rationale": self.rationale,
                "confidence": self.confidence,
                "unsupported_actions": [x.to_dict() for x in self.unsupported_actions],
                "major_decisions": list(self.major_decisions[:3]),
                "creative_review_score": self.creative_review_score,
                "brand_guide_loaded": self.brand_guide_loaded,
                "production_rules_loaded": self.production_rules_loaded,
                "brand_guide_files": list(self.brand_guide_files),
                "production_rule_files": list(self.production_rule_files),
                "recipe_id": self.recipe_id,
                "platform": self.platform,
                "content_type": self.content_type,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EditDecision":
        if not isinstance(data, dict):
            return cls()
        field_names = [
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
        ]
        kwargs: dict[str, Any] = {name: DecisionField.from_dict(data.get(name)) for name in field_names}
        kwargs.update(
            {
                "selective_cleanup": [
                    CleanupRecommendation.from_dict(x)
                    for x in data.get("selective_cleanup", [])
                    if isinstance(x, dict)
                ],
                "rationale": str(data.get("rationale") or ""),
                "confidence": float(data.get("confidence") or 0.0),
                "unsupported_actions": [
                    NotAppliedAction.from_dict(x)
                    for x in data.get("unsupported_actions", [])
                    if isinstance(x, dict)
                ],
                "major_decisions": list(data.get("major_decisions") or [])[:3],
                "creative_review_score": data.get("creative_review_score"),
                "brand_guide_loaded": bool(data.get("brand_guide_loaded")),
                "production_rules_loaded": bool(data.get("production_rules_loaded")),
                "brand_guide_files": list(data.get("brand_guide_files") or []),
                "production_rule_files": list(data.get("production_rule_files") or []),
                "recipe_id": data.get("recipe_id"),
                "platform": str(data.get("platform") or ""),
                "content_type": str(data.get("content_type") or ""),
            }
        )
        return cls(**kwargs)
