"""Campaign intelligence models — additive planning data for existing campaigns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    PLANNING_ASSUMPTION = "planning_assumption"
    BRAND_RULE = "brand_rule"
    HISTORICAL_EVIDENCE = "historical_evidence"
    CONNECTED_PERFORMANCE_EVIDENCE = "connected_performance_evidence"
    TARGET = "target"
    FORECAST = "forecast"
    OPERATIONAL_ESTIMATE = "operational_estimate"


class CampaignRole(str, Enum):
    PRIMARY = "primary"
    SUPPORTING_AWARENESS = "supporting_awareness"
    PRODUCT_EDUCATION = "product_education"
    FOUNDER_STORY = "founder_story"
    CONVERSION = "conversion"
    RETENTION = "retention"
    EVENT_SPECIFIC = "event_specific"
    SEASONAL = "seasonal"


class TimingRelation(str, Enum):
    TANDEM = "tandem"
    SEQUENTIAL = "sequential"


class AlertType(str, Enum):
    OPPORTUNITY = "opportunity"
    DEADLINE = "deadline"
    RISK = "risk"


class RecommendationDecision(str, Enum):
    ACCEPT = "accept"
    NOT_NOW = "not_now"
    DISMISS = "dismiss"
    ADJUST_OBJECTIVE = "adjust_objective"
    PENDING = "pending"


class DeadlineHardness(str, Enum):
    HARD = "hard"
    RECOMMENDED = "recommended"


def _date_to_iso(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


@dataclass
class DateRange:
    min_days: int
    max_days: int
    unit: str = "days"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def label(self) -> str:
        if self.min_days == self.max_days:
            if self.unit == "weeks":
                return f"{self.min_days} week{'s' if self.min_days != 1 else ''}"
            return f"{self.min_days} day{'s' if self.min_days != 1 else ''}"
        if self.unit == "weeks":
            return f"{self.min_days} to {self.max_days} weeks"
        return f"{self.min_days} to {self.max_days} days"


@dataclass
class EvidenceLabel:
    kind: EvidenceKind
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "summary": self.summary}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceLabel:
        return cls(
            kind=EvidenceKind(data.get("kind", EvidenceKind.PLANNING_ASSUMPTION.value)),
            summary=str(data.get("summary") or ""),
        )


@dataclass
class CampaignInputs:
    """Optional planning inputs. Progressive disclosure — none are required."""

    business_objective: str = ""
    target_milestone_date: date | None = None
    product_availability_date: date | None = None
    sample_availability_date: date | None = None
    inventory_arrival_date: date | None = None
    manufacturing_deadline: date | None = None
    preorder_start_date: date | None = None
    shipping_cutoff: date | None = None
    event_date: date | None = None
    partnership_date: date | None = None
    founder_availability: str = ""
    filming_availability: str = ""
    filming_minutes_available: int | None = None
    preferred_platforms: list[str] = field(default_factory=list)
    existing_assets_notes: str = ""
    known_dependencies: list[str] = field(default_factory=list)
    geographic_market: str = ""
    budget_notes: str = ""
    paid_media_notes: str = ""
    inventory_available: bool | None = None
    date_certainty: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "business_objective": self.business_objective,
            "target_milestone_date": _date_to_iso(self.target_milestone_date),
            "product_availability_date": _date_to_iso(self.product_availability_date),
            "sample_availability_date": _date_to_iso(self.sample_availability_date),
            "inventory_arrival_date": _date_to_iso(self.inventory_arrival_date),
            "manufacturing_deadline": _date_to_iso(self.manufacturing_deadline),
            "preorder_start_date": _date_to_iso(self.preorder_start_date),
            "shipping_cutoff": _date_to_iso(self.shipping_cutoff),
            "event_date": _date_to_iso(self.event_date),
            "partnership_date": _date_to_iso(self.partnership_date),
            "founder_availability": self.founder_availability,
            "filming_availability": self.filming_availability,
            "filming_minutes_available": self.filming_minutes_available,
            "preferred_platforms": list(self.preferred_platforms),
            "existing_assets_notes": self.existing_assets_notes,
            "known_dependencies": list(self.known_dependencies),
            "geographic_market": self.geographic_market,
            "budget_notes": self.budget_notes,
            "paid_media_notes": self.paid_media_notes,
            "inventory_available": self.inventory_available,
            "date_certainty": dict(self.date_certainty),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CampaignInputs:
        data = data or {}
        return cls(
            business_objective=str(data.get("business_objective") or ""),
            target_milestone_date=_parse_date(data.get("target_milestone_date")),
            product_availability_date=_parse_date(data.get("product_availability_date")),
            sample_availability_date=_parse_date(data.get("sample_availability_date")),
            inventory_arrival_date=_parse_date(data.get("inventory_arrival_date")),
            manufacturing_deadline=_parse_date(data.get("manufacturing_deadline")),
            preorder_start_date=_parse_date(data.get("preorder_start_date")),
            shipping_cutoff=_parse_date(data.get("shipping_cutoff")),
            event_date=_parse_date(data.get("event_date")),
            partnership_date=_parse_date(data.get("partnership_date")),
            founder_availability=str(data.get("founder_availability") or ""),
            filming_availability=str(data.get("filming_availability") or ""),
            filming_minutes_available=(
                int(data["filming_minutes_available"])
                if data.get("filming_minutes_available") is not None
                else None
            ),
            preferred_platforms=list(data.get("preferred_platforms") or []),
            existing_assets_notes=str(data.get("existing_assets_notes") or ""),
            known_dependencies=list(data.get("known_dependencies") or []),
            geographic_market=str(data.get("geographic_market") or ""),
            budget_notes=str(data.get("budget_notes") or ""),
            paid_media_notes=str(data.get("paid_media_notes") or ""),
            inventory_available=data.get("inventory_available"),
            date_certainty=dict(data.get("date_certainty") or {}),
        )


@dataclass
class CalendarOpportunity:
    event_id: str
    name: str
    occurrence_date: date | None
    date_uncertain: bool = False
    category: str = "seasonal"
    brand_relevance: float = 0.0
    product_relevance: float = 0.0
    audience_relevance: float = 0.0
    commercial_relevance: float = 0.0
    score: float = 0.0
    reason: str = ""
    lead_time_days: int | None = None
    included: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "occurrence_date": _date_to_iso(self.occurrence_date),
            "date_uncertain": self.date_uncertain,
            "category": self.category,
            "brand_relevance": self.brand_relevance,
            "product_relevance": self.product_relevance,
            "audience_relevance": self.audience_relevance,
            "commercial_relevance": self.commercial_relevance,
            "score": self.score,
            "reason": self.reason,
            "lead_time_days": self.lead_time_days,
            "included": self.included,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalendarOpportunity:
        return cls(
            event_id=str(data.get("event_id") or ""),
            name=str(data.get("name") or ""),
            occurrence_date=_parse_date(data.get("occurrence_date")),
            date_uncertain=bool(data.get("date_uncertain")),
            category=str(data.get("category") or "seasonal"),
            brand_relevance=float(data.get("brand_relevance") or 0),
            product_relevance=float(data.get("product_relevance") or 0),
            audience_relevance=float(data.get("audience_relevance") or 0),
            commercial_relevance=float(data.get("commercial_relevance") or 0),
            score=float(data.get("score") or 0),
            reason=str(data.get("reason") or ""),
            lead_time_days=data.get("lead_time_days"),
            included=bool(data.get("included", True)),
        )


@dataclass
class ScheduleDates:
    recommended_start: date | None = None
    latest_safe_start: date | None = None
    production_deadline: date | None = None
    asset_deadline: date | None = None
    approval_deadline: date | None = None
    milestone_date: date | None = None
    range_note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommended_start": _date_to_iso(self.recommended_start),
            "latest_safe_start": _date_to_iso(self.latest_safe_start),
            "production_deadline": _date_to_iso(self.production_deadline),
            "asset_deadline": _date_to_iso(self.asset_deadline),
            "approval_deadline": _date_to_iso(self.approval_deadline),
            "milestone_date": _date_to_iso(self.milestone_date),
            "range_note": self.range_note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ScheduleDates:
        data = data or {}
        return cls(
            recommended_start=_parse_date(data.get("recommended_start")),
            latest_safe_start=_parse_date(data.get("latest_safe_start")),
            production_deadline=_parse_date(data.get("production_deadline")),
            asset_deadline=_parse_date(data.get("asset_deadline")),
            approval_deadline=_parse_date(data.get("approval_deadline")),
            milestone_date=_parse_date(data.get("milestone_date")),
            range_note=str(data.get("range_note") or ""),
        )


@dataclass
class PortfolioRecommendation:
    recommendation_id: str
    campaign_name: str
    role: CampaignRole
    objective: str
    reason: str
    audience_stage: str
    timing: ScheduleDates
    dependency: str = ""
    relation: TimingRelation = TimingRelation.TANDEM
    estimated_additional_filming_minutes: DateRange = field(
        default_factory=lambda: DateRange(0, 0)
    )
    estimated_deliverables: DateRange = field(default_factory=lambda: DateRange(0, 0))
    estimated_runway_days: DateRange = field(default_factory=lambda: DateRange(0, 0))
    confidence: str = "medium"
    assumptions: list[str] = field(default_factory=list)
    evidence: EvidenceLabel = field(
        default_factory=lambda: EvidenceLabel(
            EvidenceKind.PLANNING_ASSUMPTION,
            "Based on configured lead-time and campaign-need assumptions.",
        )
    )
    decision: RecommendationDecision = RecommendationDecision.PENDING
    decision_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "campaign_name": self.campaign_name,
            "role": self.role.value,
            "objective": self.objective,
            "reason": self.reason,
            "audience_stage": self.audience_stage,
            "timing": self.timing.as_dict(),
            "dependency": self.dependency,
            "relation": self.relation.value,
            "estimated_additional_filming_minutes": self.estimated_additional_filming_minutes.as_dict(),
            "estimated_deliverables": self.estimated_deliverables.as_dict(),
            "estimated_runway_days": self.estimated_runway_days.as_dict(),
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "evidence": self.evidence.as_dict(),
            "decision": self.decision.value,
            "decision_at": self.decision_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortfolioRecommendation:
        return cls(
            recommendation_id=str(data.get("recommendation_id") or ""),
            campaign_name=str(data.get("campaign_name") or ""),
            role=CampaignRole(data.get("role", CampaignRole.PRIMARY.value)),
            objective=str(data.get("objective") or ""),
            reason=str(data.get("reason") or ""),
            audience_stage=str(data.get("audience_stage") or ""),
            timing=ScheduleDates.from_dict(data.get("timing")),
            dependency=str(data.get("dependency") or ""),
            relation=TimingRelation(data.get("relation", TimingRelation.TANDEM.value)),
            estimated_additional_filming_minutes=DateRange(
                **(data.get("estimated_additional_filming_minutes") or {"min_days": 0, "max_days": 0})
            )
            if "min_days" in (data.get("estimated_additional_filming_minutes") or {})
            else DateRange(
                int((data.get("estimated_additional_filming_minutes") or {}).get("min", 0) or 0),
                int((data.get("estimated_additional_filming_minutes") or {}).get("max", 0) or 0),
            ),
            estimated_deliverables=DateRange(
                **{
                    "min_days": int((data.get("estimated_deliverables") or {}).get("min_days", 0) or 0),
                    "max_days": int((data.get("estimated_deliverables") or {}).get("max_days", 0) or 0),
                }
            ),
            estimated_runway_days=DateRange(
                **{
                    "min_days": int((data.get("estimated_runway_days") or {}).get("min_days", 0) or 0),
                    "max_days": int((data.get("estimated_runway_days") or {}).get("max_days", 0) or 0),
                }
            ),
            confidence=str(data.get("confidence") or "medium"),
            assumptions=list(data.get("assumptions") or []),
            evidence=EvidenceLabel.from_dict(data.get("evidence") or {}),
            decision=RecommendationDecision(
                data.get("decision", RecommendationDecision.PENDING.value)
            ),
            decision_at=data.get("decision_at"),
        )


@dataclass
class StrategicAlert:
    alert_id: str
    alert_type: AlertType
    title: str
    detail: str
    relevance: str
    affected_objective: str
    recommended_action: str
    start_by: date | None = None
    confidence: str = "medium"
    assumptions: list[str] = field(default_factory=list)
    hardness: DeadlineHardness = DeadlineHardness.RECOMMENDED
    high_value: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "title": self.title,
            "detail": self.detail,
            "relevance": self.relevance,
            "affected_objective": self.affected_objective,
            "recommended_action": self.recommended_action,
            "start_by": _date_to_iso(self.start_by),
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "hardness": self.hardness.value,
            "high_value": self.high_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategicAlert:
        return cls(
            alert_id=str(data.get("alert_id") or ""),
            alert_type=AlertType(data.get("alert_type", AlertType.OPPORTUNITY.value)),
            title=str(data.get("title") or ""),
            detail=str(data.get("detail") or ""),
            relevance=str(data.get("relevance") or ""),
            affected_objective=str(data.get("affected_objective") or ""),
            recommended_action=str(data.get("recommended_action") or ""),
            start_by=_parse_date(data.get("start_by")),
            confidence=str(data.get("confidence") or "medium"),
            assumptions=list(data.get("assumptions") or []),
            hardness=DeadlineHardness(
                data.get("hardness", DeadlineHardness.RECOMMENDED.value)
            ),
            high_value=bool(data.get("high_value", True)),
        )


@dataclass
class ShotPlanItem:
    shot_id: str
    description: str
    must_have: bool = True
    shared: bool = False
    campaigns: list[str] = field(default_factory=list)
    framing: str = ""
    lighting: str = ""
    props: str = ""
    negative_space: str = ""
    sequence_order: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShotPlanItem:
        return cls(**{k: data.get(k, getattr(cls, k, None) if False else data.get(k)) for k in (
            "shot_id", "description", "must_have", "shared", "campaigns",
            "framing", "lighting", "props", "negative_space", "sequence_order",
        )} if False else {
            "shot_id": str(data.get("shot_id") or ""),
            "description": str(data.get("description") or ""),
            "must_have": bool(data.get("must_have", True)),
            "shared": bool(data.get("shared", False)),
            "campaigns": list(data.get("campaigns") or []),
            "framing": str(data.get("framing") or ""),
            "lighting": str(data.get("lighting") or ""),
            "props": str(data.get("props") or ""),
            "negative_space": str(data.get("negative_space") or ""),
            "sequence_order": int(data.get("sequence_order") or 0),
        })


@dataclass
class CadenceRecommendation:
    platform: str
    min_per_week: int
    max_per_week: int
    reason: str
    evidence: EvidenceLabel

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "min_per_week": self.min_per_week,
            "max_per_week": self.max_per_week,
            "reason": self.reason,
            "evidence": self.evidence.as_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CadenceRecommendation:
        return cls(
            platform=str(data.get("platform") or ""),
            min_per_week=int(data.get("min_per_week") or 0),
            max_per_week=int(data.get("max_per_week") or 0),
            reason=str(data.get("reason") or ""),
            evidence=EvidenceLabel.from_dict(data.get("evidence") or {}),
        )


@dataclass
class RunwayEstimate:
    """Content runway — distinct from strategic campaign duration."""

    phase: str  # pre_shoot | post_capture | final_planned | actual_published
    days: DateRange
    weeks: DateRange | None = None
    approximate_start: date | None = None
    approximate_end: date | None = None
    by_platform: dict[str, dict[str, int]] = field(default_factory=dict)
    confidence: str = "medium"
    assumptions: list[str] = field(default_factory=list)
    reason_for_change: str = ""
    evidence: EvidenceLabel = field(
        default_factory=lambda: EvidenceLabel(
            EvidenceKind.OPERATIONAL_ESTIMATE,
            "Operational content-output estimate, not a performance forecast.",
        )
    )
    recorded_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "days": self.days.as_dict(),
            "weeks": self.weeks.as_dict() if self.weeks else None,
            "approximate_start": _date_to_iso(self.approximate_start),
            "approximate_end": _date_to_iso(self.approximate_end),
            "by_platform": self.by_platform,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "reason_for_change": self.reason_for_change,
            "evidence": self.evidence.as_dict(),
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunwayEstimate:
        days_data = data.get("days") or {"min_days": 0, "max_days": 0}
        weeks_data = data.get("weeks")
        return cls(
            phase=str(data.get("phase") or "pre_shoot"),
            days=DateRange(
                int(days_data.get("min_days") or 0),
                int(days_data.get("max_days") or 0),
            ),
            weeks=DateRange(
                int(weeks_data.get("min_days") or 0),
                int(weeks_data.get("max_days") or 0),
                unit="weeks",
            )
            if weeks_data
            else None,
            approximate_start=_parse_date(data.get("approximate_start")),
            approximate_end=_parse_date(data.get("approximate_end")),
            by_platform=dict(data.get("by_platform") or {}),
            confidence=str(data.get("confidence") or "medium"),
            assumptions=list(data.get("assumptions") or []),
            reason_for_change=str(data.get("reason_for_change") or ""),
            evidence=EvidenceLabel.from_dict(data.get("evidence") or {}),
            recorded_at=data.get("recorded_at"),
        )


@dataclass
class DeliverableEstimate:
    final_assets: DateRange
    formats: list[str]
    platforms: list[str]
    filming_minutes: DateRange
    editing_minutes: DateRange
    approval_days: DateRange
    confidence: str = "medium"
    assumptions: list[str] = field(default_factory=list)
    evidence: EvidenceLabel = field(
        default_factory=lambda: EvidenceLabel(
            EvidenceKind.OPERATIONAL_ESTIMATE,
            "Operational estimate from planned shots and planning assumptions.",
        )
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_assets": self.final_assets.as_dict(),
            "formats": list(self.formats),
            "platforms": list(self.platforms),
            "filming_minutes": self.filming_minutes.as_dict(),
            "editing_minutes": self.editing_minutes.as_dict(),
            "approval_days": self.approval_days.as_dict(),
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "evidence": self.evidence.as_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DeliverableEstimate | None:
        if not data:
            return None
        return cls(
            final_assets=DateRange(
                int((data.get("final_assets") or {}).get("min_days") or 0),
                int((data.get("final_assets") or {}).get("max_days") or 0),
            ),
            formats=list(data.get("formats") or []),
            platforms=list(data.get("platforms") or []),
            filming_minutes=DateRange(
                int((data.get("filming_minutes") or {}).get("min_days") or 0),
                int((data.get("filming_minutes") or {}).get("max_days") or 0),
            ),
            editing_minutes=DateRange(
                int((data.get("editing_minutes") or {}).get("min_days") or 0),
                int((data.get("editing_minutes") or {}).get("max_days") or 0),
            ),
            approval_days=DateRange(
                int((data.get("approval_days") or {}).get("min_days") or 0),
                int((data.get("approval_days") or {}).get("max_days") or 0),
            ),
            confidence=str(data.get("confidence") or "medium"),
            assumptions=list(data.get("assumptions") or []),
            evidence=EvidenceLabel.from_dict(data.get("evidence") or {}),
        )


@dataclass
class CombinedProductionSession:
    session_name: str
    campaign_names: list[str]
    filming_minutes: DateRange
    expected_formats: list[str]
    expected_assets: DateRange
    combined_runway_days: DateRange
    shots: list[ShotPlanItem] = field(default_factory=list)
    notes: str = ""
    confidence: str = "medium"
    assumptions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_name": self.session_name,
            "campaign_names": list(self.campaign_names),
            "filming_minutes": self.filming_minutes.as_dict(),
            "expected_formats": list(self.expected_formats),
            "expected_assets": self.expected_assets.as_dict(),
            "combined_runway_days": self.combined_runway_days.as_dict(),
            "shots": [s.as_dict() for s in self.shots],
            "notes": self.notes,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CombinedProductionSession | None:
        if not data:
            return None
        return cls(
            session_name=str(data.get("session_name") or ""),
            campaign_names=list(data.get("campaign_names") or []),
            filming_minutes=DateRange(
                int((data.get("filming_minutes") or {}).get("min_days") or 0),
                int((data.get("filming_minutes") or {}).get("max_days") or 0),
            ),
            expected_formats=list(data.get("expected_formats") or []),
            expected_assets=DateRange(
                int((data.get("expected_assets") or {}).get("min_days") or 0),
                int((data.get("expected_assets") or {}).get("max_days") or 0),
            ),
            combined_runway_days=DateRange(
                int((data.get("combined_runway_days") or {}).get("min_days") or 0),
                int((data.get("combined_runway_days") or {}).get("max_days") or 0),
            ),
            shots=[ShotPlanItem.from_dict(s) for s in (data.get("shots") or [])],
            notes=str(data.get("notes") or ""),
            confidence=str(data.get("confidence") or "medium"),
            assumptions=list(data.get("assumptions") or []),
        )


@dataclass
class PublishingPlanItem:
    day_offset: int
    window_label: str
    platform: str
    format_name: str
    campaign_role: str
    cta: str
    campaign_relationship: str = ""
    supporting_overlap: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublishingPlanItem:
        return cls(
            day_offset=int(data.get("day_offset") or 0),
            window_label=str(data.get("window_label") or ""),
            platform=str(data.get("platform") or ""),
            format_name=str(data.get("format_name") or ""),
            campaign_role=str(data.get("campaign_role") or ""),
            cta=str(data.get("cta") or ""),
            campaign_relationship=str(data.get("campaign_relationship") or ""),
            supporting_overlap=str(data.get("supporting_overlap") or ""),
        )


@dataclass
class ProductionBriefRecord:
    brief_id: str
    filename: str
    path: str
    created_at: str
    campaign_slug: str
    page_count: int
    file_size_bytes: int
    summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductionBriefRecord:
        return cls(
            brief_id=str(data.get("brief_id") or ""),
            filename=str(data.get("filename") or ""),
            path=str(data.get("path") or ""),
            created_at=str(data.get("created_at") or ""),
            campaign_slug=str(data.get("campaign_slug") or ""),
            page_count=int(data.get("page_count") or 0),
            file_size_bytes=int(data.get("file_size_bytes") or 0),
            summary=dict(data.get("summary") or {}),
        )


@dataclass
class LearningOutcome:
    """Estimated versus actual operational outcomes for future estimate improvement."""

    estimated_filming_minutes: DateRange | None = None
    actual_filming_minutes: int | None = None
    estimated_usable_shots: DateRange | None = None
    actual_usable_shots: int | None = None
    estimated_final_assets: DateRange | None = None
    actual_final_assets: int | None = None
    estimated_editing_minutes: DateRange | None = None
    actual_editing_minutes: int | None = None
    estimated_runway_days: DateRange | None = None
    actual_runway_days: int | None = None
    estimated_campaign_start: date | None = None
    actual_campaign_start: date | None = None
    missed_deadlines: list[str] = field(default_factory=list)
    reshoots: int = 0
    approvals_and_revisions: int = 0
    notes: str = ""
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        def range_dict(value: DateRange | None) -> dict[str, Any] | None:
            return value.as_dict() if value else None

        return {
            "estimated_filming_minutes": range_dict(self.estimated_filming_minutes),
            "actual_filming_minutes": self.actual_filming_minutes,
            "estimated_usable_shots": range_dict(self.estimated_usable_shots),
            "actual_usable_shots": self.actual_usable_shots,
            "estimated_final_assets": range_dict(self.estimated_final_assets),
            "actual_final_assets": self.actual_final_assets,
            "estimated_editing_minutes": range_dict(self.estimated_editing_minutes),
            "actual_editing_minutes": self.actual_editing_minutes,
            "estimated_runway_days": range_dict(self.estimated_runway_days),
            "actual_runway_days": self.actual_runway_days,
            "estimated_campaign_start": _date_to_iso(self.estimated_campaign_start),
            "actual_campaign_start": _date_to_iso(self.actual_campaign_start),
            "missed_deadlines": list(self.missed_deadlines),
            "reshoots": self.reshoots,
            "approvals_and_revisions": self.approvals_and_revisions,
            "notes": self.notes,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LearningOutcome:
        data = data or {}

        def parse_range(key: str) -> DateRange | None:
            raw = data.get(key)
            if not raw:
                return None
            return DateRange(int(raw.get("min_days") or 0), int(raw.get("max_days") or 0))

        return cls(
            estimated_filming_minutes=parse_range("estimated_filming_minutes"),
            actual_filming_minutes=data.get("actual_filming_minutes"),
            estimated_usable_shots=parse_range("estimated_usable_shots"),
            actual_usable_shots=data.get("actual_usable_shots"),
            estimated_final_assets=parse_range("estimated_final_assets"),
            actual_final_assets=data.get("actual_final_assets"),
            estimated_editing_minutes=parse_range("estimated_editing_minutes"),
            actual_editing_minutes=data.get("actual_editing_minutes"),
            estimated_runway_days=parse_range("estimated_runway_days"),
            actual_runway_days=data.get("actual_runway_days"),
            estimated_campaign_start=_parse_date(data.get("estimated_campaign_start")),
            actual_campaign_start=_parse_date(data.get("actual_campaign_start")),
            missed_deadlines=list(data.get("missed_deadlines") or []),
            reshoots=int(data.get("reshoots") or 0),
            approvals_and_revisions=int(data.get("approvals_and_revisions") or 0),
            notes=str(data.get("notes") or ""),
            updated_at=data.get("updated_at"),
        )


@dataclass
class CampaignIntelligence:
    """Persisted campaign intelligence attached to an existing campaign folder."""

    version: int = 1
    campaign_name: str = ""
    brand_id: str = "oh_betty_jaletti"
    inputs: CampaignInputs = field(default_factory=CampaignInputs)
    opportunities: list[CalendarOpportunity] = field(default_factory=list)
    recommendations: list[PortfolioRecommendation] = field(default_factory=list)
    alerts: list[StrategicAlert] = field(default_factory=list)
    production_session: CombinedProductionSession | None = None
    deliverable_estimate: DeliverableEstimate | None = None
    cadence: list[CadenceRecommendation] = field(default_factory=list)
    runway_history: list[RunwayEstimate] = field(default_factory=list)
    publishing_plan: list[PublishingPlanItem] = field(default_factory=list)
    creative_direction: str = ""
    portfolio_accepted: bool = False
    plan_accepted_at: str | None = None
    newest_brief_id: str | None = None
    updated_at: str | None = None

    def current_runway(self, phase: str | None = None) -> RunwayEstimate | None:
        if not self.runway_history:
            return None
        if phase:
            matches = [r for r in self.runway_history if r.phase == phase]
            return matches[-1] if matches else None
        return self.runway_history[-1]

    def primary_recommendation(self) -> PortfolioRecommendation | None:
        for item in self.recommendations:
            if item.role == CampaignRole.PRIMARY:
                return item
        return self.recommendations[0] if self.recommendations else None

    def accepted_recommendations(self) -> list[PortfolioRecommendation]:
        return [
            r
            for r in self.recommendations
            if r.decision == RecommendationDecision.ACCEPT
            or (
                r.role == CampaignRole.PRIMARY
                and r.decision == RecommendationDecision.PENDING
                and self.portfolio_accepted
            )
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "campaign_name": self.campaign_name,
            "brand_id": self.brand_id,
            "inputs": self.inputs.as_dict(),
            "opportunities": [o.as_dict() for o in self.opportunities],
            "recommendations": [r.as_dict() for r in self.recommendations],
            "alerts": [a.as_dict() for a in self.alerts],
            "production_session": (
                self.production_session.as_dict() if self.production_session else None
            ),
            "deliverable_estimate": (
                self.deliverable_estimate.as_dict() if self.deliverable_estimate else None
            ),
            "cadence": [c.as_dict() for c in self.cadence],
            "runway_history": [r.as_dict() for r in self.runway_history],
            "publishing_plan": [p.as_dict() for p in self.publishing_plan],
            "creative_direction": self.creative_direction,
            "portfolio_accepted": self.portfolio_accepted,
            "plan_accepted_at": self.plan_accepted_at,
            "newest_brief_id": self.newest_brief_id,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CampaignIntelligence:
        data = data or {}
        return cls(
            version=int(data.get("version") or 1),
            campaign_name=str(data.get("campaign_name") or ""),
            brand_id=str(data.get("brand_id") or "oh_betty_jaletti"),
            inputs=CampaignInputs.from_dict(data.get("inputs")),
            opportunities=[
                CalendarOpportunity.from_dict(o) for o in (data.get("opportunities") or [])
            ],
            recommendations=[
                PortfolioRecommendation.from_dict(r)
                for r in (data.get("recommendations") or [])
            ],
            alerts=[StrategicAlert.from_dict(a) for a in (data.get("alerts") or [])],
            production_session=CombinedProductionSession.from_dict(
                data.get("production_session")
            ),
            deliverable_estimate=DeliverableEstimate.from_dict(
                data.get("deliverable_estimate")
            ),
            cadence=[CadenceRecommendation.from_dict(c) for c in (data.get("cadence") or [])],
            runway_history=[
                RunwayEstimate.from_dict(r) for r in (data.get("runway_history") or [])
            ],
            publishing_plan=[
                PublishingPlanItem.from_dict(p) for p in (data.get("publishing_plan") or [])
            ],
            creative_direction=str(data.get("creative_direction") or ""),
            portfolio_accepted=bool(data.get("portfolio_accepted")),
            plan_accepted_at=data.get("plan_accepted_at"),
            newest_brief_id=data.get("newest_brief_id"),
            updated_at=data.get("updated_at"),
        )
