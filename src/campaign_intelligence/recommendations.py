"""Portfolio recommendations and strategic alerts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from src.campaign_intelligence.calendar import evaluate_opportunities
from src.campaign_intelligence.estimates import (
    estimate_deliverables,
    estimate_runway,
    recommend_cadence,
)
from src.campaign_intelligence.models import (
    AlertType,
    CalendarOpportunity,
    CampaignInputs,
    CampaignIntelligence,
    CampaignRole,
    DateRange,
    DeadlineHardness,
    EvidenceKind,
    EvidenceLabel,
    PortfolioRecommendation,
    RecommendationDecision,
    StrategicAlert,
    TimingRelation,
)
from src.campaign_intelligence.rules import load_strategy_rules
from src.campaign_intelligence.scheduling import (
    is_overdue,
    resolve_lead_time_key,
    work_back_schedule,
)
from src.common import DEFAULT_BRAND_ID


def build_portfolio_recommendations(
    inputs: CampaignInputs,
    *,
    campaign_name: str = "",
    opportunities: list[CalendarOpportunity] | None = None,
    as_of: date | None = None,
    brand_id: str = DEFAULT_BRAND_ID,
) -> list[PortfolioRecommendation]:
    """Recommend primary (+ optional supporting) campaigns. Never auto-creates them."""
    as_of = as_of or date.today()
    objective = (inputs.business_objective or "grow the waitlist").strip()
    name = campaign_name or _default_primary_name(objective)
    milestone = (
        inputs.target_milestone_date
        or inputs.preorder_start_date
        or inputs.event_date
        or _best_opportunity_date(opportunities)
    )
    primary_timing = work_back_schedule(
        milestone, objective=objective, inputs=inputs, as_of=as_of
    )
    primary = PortfolioRecommendation(
        recommendation_id=f"rec_primary_{uuid4().hex[:8]}",
        campaign_name=name,
        role=CampaignRole.PRIMARY,
        objective=objective,
        reason=_primary_reason(objective, opportunities),
        audience_stage=_audience_stage(objective),
        timing=primary_timing,
        dependency="",
        relation=TimingRelation.TANDEM,
        estimated_additional_filming_minutes=DateRange(45, 70),
        estimated_deliverables=DateRange(4, 7),
        estimated_runway_days=DateRange(10, 18),
        confidence="medium",
        assumptions=[
            "Lead times are planning assumptions from strategy rules.",
            "Content-output estimates are operational, not performance forecasts.",
        ],
        evidence=EvidenceLabel(
            EvidenceKind.PLANNING_ASSUMPTION,
            "Based on configured lead-time rules and campaign objective.",
        ),
        decision=RecommendationDecision.PENDING,
    )

    recommendations = [primary]
    supporting = _maybe_supporting(
        inputs, primary=primary, opportunities=opportunities, as_of=as_of
    )
    if supporting:
        recommendations.append(supporting)
    return recommendations


def _maybe_supporting(
    inputs: CampaignInputs,
    *,
    primary: PortfolioRecommendation,
    opportunities: list[CalendarOpportunity] | None,
    as_of: date,
) -> PortfolioRecommendation | None:
    objective = (inputs.business_objective or "").lower()
    # Only recommend supporting when strategically justified.
    needs_familiarity = any(
        token in objective
        for token in ("waitlist", "preorder", "launch", "conversion", "grow")
    )
    if not needs_familiarity:
        return None

    # If inventory-sensitive retail is near and no inventory — supporting waitlist education
    retail_pressure = False
    for opp in opportunities or []:
        if opp.event_id in {"black_friday", "cyber_monday", "holiday_gifting"} and opp.score >= 0.4:
            retail_pressure = True
            break

    if "familiarity" in objective or "education" in objective:
        # Primary already is education — don't stack another education campaign.
        if not retail_pressure:
            return None

    support_objective = "increase product familiarity"
    support_name = "Build product familiarity"
    reason = (
        "The audience should repeatedly understand the product concept before the "
        "strongest conversion or waitlist ask."
    )
    if retail_pressure and (inputs.inventory_available is False or inputs.inventory_available is None):
        reason += (
            " Nearby retail moments make familiarity and waitlist framing safer than "
            "availability promises."
        )

    # Start slightly before or with primary
    base_start = primary.timing.recommended_start or as_of
    timing = work_back_schedule(
        primary.timing.milestone_date or (base_start + timedelta(days=28)),
        objective=support_objective,
        explicit_key="product_education",
        inputs=inputs,
        as_of=as_of,
    )
    # Prefer tandem start a few days before primary conversion push
    if timing.recommended_start and primary.timing.recommended_start:
        timing.recommended_start = min(
            timing.recommended_start,
            primary.timing.recommended_start - timedelta(days=7),
        )

    return PortfolioRecommendation(
        recommendation_id=f"rec_support_{uuid4().hex[:8]}",
        campaign_name=support_name,
        role=CampaignRole.PRODUCT_EDUCATION,
        objective=support_objective,
        reason=reason,
        audience_stage="awareness → familiarity",
        timing=timing,
        dependency=primary.campaign_name,
        relation=TimingRelation.TANDEM,
        estimated_additional_filming_minutes=DateRange(10, 20),
        estimated_deliverables=DateRange(2, 3),
        estimated_runway_days=DateRange(5, 7),
        confidence="medium",
        assumptions=[
            "Additional filming reuses the same production session where possible.",
            "Supporting campaign is justified by audience-stage needs, not calendar filler.",
        ],
        evidence=EvidenceLabel(
            EvidenceKind.PLANNING_ASSUMPTION,
            "Supporting campaign recommended from objective and audience-stage logic.",
        ),
        decision=RecommendationDecision.PENDING,
    )


def build_alerts(
    inputs: CampaignInputs,
    *,
    opportunities: list[CalendarOpportunity],
    recommendations: list[PortfolioRecommendation],
    as_of: date | None = None,
) -> list[StrategicAlert]:
    """High-value opportunity, deadline, and risk alerts only."""
    as_of = as_of or date.today()
    alerts: list[StrategicAlert] = []
    objective = inputs.business_objective or "grow the waitlist"

    # Top opportunity
    for opp in opportunities:
        if opp.category in {"novelty"}:
            continue
        if opp.score < 0.55:
            continue
        if opp.occurrence_date is None:
            continue
        days = (opp.occurrence_date - as_of).days
        if days < 0 or days > 120:
            continue
        # Prefer seasonal/literary opportunities over raw milestone echoes for Today
        if opp.category == "milestone":
            continue
        start_by = opp.occurrence_date - timedelta(days=opp.lead_time_days or 21)
        weeks = max(1, days // 7)
        alerts.append(
            StrategicAlert(
                alert_id=f"opp_{opp.event_id}",
                alert_type=AlertType.OPPORTUNITY,
                title=f"{opp.name} is approaching",
                detail=(
                    f"{opp.name} begins in about {weeks} week{'s' if weeks != 1 else ''} "
                    f"({opp.occurrence_date.isoformat()}). {opp.reason}"
                ),
                relevance=f"Score {opp.score:.2f} — {opp.reason}",
                affected_objective=objective,
                recommended_action=f"Prepare a campaign aligned with {opp.name}.",
                start_by=start_by,
                confidence="medium",
                assumptions=["Calendar occurrence calculated for the active planning period."],
                hardness=DeadlineHardness.RECOMMENDED,
                high_value=True,
            )
        )
        break  # one highest-value opportunity

    # Deadline from primary schedule
    primary = next((r for r in recommendations if r.role == CampaignRole.PRIMARY), None)
    if primary and primary.timing.production_deadline:
        alerts.append(
            StrategicAlert(
                alert_id="deadline_production",
                alert_type=AlertType.DEADLINE,
                title="Production deadline",
                detail=(
                    f"To support the plan, production should be complete by "
                    f"{primary.timing.production_deadline.isoformat()}."
                ),
                relevance="Work-back schedule from campaign milestone",
                affected_objective=objective,
                recommended_action="Complete filming and editing before the production deadline.",
                start_by=primary.timing.latest_safe_start,
                confidence="medium",
                assumptions=[primary.timing.range_note] if primary.timing.range_note else [],
                hardness=DeadlineHardness.RECOMMENDED,
                high_value=True,
            )
        )

    # Risk: manufacturing / inventory vs retail
    inv = inputs.inventory_available
    if inv is False or inv is None:
        for opp in opportunities:
            if opp.event_id in {"black_friday", "cyber_monday"} and opp.score >= 0.3:
                alerts.append(
                    StrategicAlert(
                        alert_id=f"risk_{opp.event_id}_inventory",
                        alert_type=AlertType.RISK,
                        title=f"{opp.name} availability risk",
                        detail=(
                            "The current manufacturing or inventory timeline does not leave "
                            f"enough margin for a {opp.name} product-availability campaign. "
                            "Recommend focusing on waitlist growth rather than promising availability."
                        ),
                        relevance="Inventory unavailable per brand / campaign inputs",
                        affected_objective=objective,
                        recommended_action="Focus on waitlist growth and product familiarity.",
                        start_by=as_of,
                        confidence="high",
                        assumptions=[
                            "Brand Guide states inventory is not available unless overridden.",
                        ],
                        hardness=DeadlineHardness.HARD,
                        high_value=True,
                    )
                )
                break

    if inputs.manufacturing_deadline and inputs.target_milestone_date:
        if inputs.manufacturing_deadline > inputs.target_milestone_date - timedelta(days=10):
            alerts.append(
                StrategicAlert(
                    alert_id="risk_manufacturing_margin",
                    alert_type=AlertType.RISK,
                    title="Manufacturing margin is tight",
                    detail=(
                        "Manufacturing deadline leaves little margin before the target milestone."
                    ),
                    relevance="Manufacturing vs launch timing",
                    affected_objective=objective,
                    recommended_action="Shift messaging toward waitlist or delay availability claims.",
                    start_by=as_of,
                    confidence="medium",
                    assumptions=["Comparing founder-entered manufacturing and milestone dates."],
                    hardness=DeadlineHardness.HARD,
                    high_value=True,
                )
            )

    if primary and is_overdue(primary.timing, as_of=as_of):
        alerts.append(
            StrategicAlert(
                alert_id="risk_overdue_start",
                alert_type=AlertType.RISK,
                title="Campaign start is overdue",
                detail=(
                    "The latest safe start date has passed relative to the milestone. "
                    "Narrow scope or adjust the target date."
                ),
                relevance="Work-back schedule vs today",
                affected_objective=objective,
                recommended_action="Reduce deliverables or move the milestone.",
                start_by=as_of,
                confidence="medium",
                assumptions=["Based on configured lead-time ranges."],
                hardness=DeadlineHardness.HARD,
                high_value=True,
            )
        )

    # Deduplicate by alert_id, keep high_value only for default display
    seen: set[str] = set()
    unique: list[StrategicAlert] = []
    for alert in alerts:
        if alert.alert_id in seen:
            continue
        seen.add(alert.alert_id)
        unique.append(alert)
    return unique


def high_value_alerts(alerts: list[StrategicAlert]) -> list[StrategicAlert]:
    return [a for a in alerts if a.high_value]


def _default_primary_name(objective: str) -> str:
    text = objective.strip()
    if not text:
        return "Primary campaign"
    if "waitlist" in text.lower():
        return "Grow The Reading Hour waitlist"
    return text[:1].upper() + text[1:]


def _primary_reason(
    objective: str, opportunities: list[CalendarOpportunity] | None
) -> str:
    base = f"Best matches the stated business objective: {objective}."
    if opportunities:
        top = opportunities[0]
        if top.score >= 0.7 and top.occurrence_date:
            return (
                f"{base} Aligns with {top.name} "
                f"({top.occurrence_date.isoformat()})."
            )
    return base


def _audience_stage(objective: str) -> str:
    text = objective.lower()
    if "waitlist" in text or "preorder" in text:
        return "interest → waitlist"
    if "conversion" in text or "purchase" in text:
        return "consideration → conversion"
    if "familiarity" in text or "education" in text:
        return "awareness → familiarity"
    if "retention" in text or "repeat" in text:
        return "customer → retention"
    return "awareness"


def _best_opportunity_date(
    opportunities: list[CalendarOpportunity] | None,
) -> date | None:
    if not opportunities:
        return None
    for opp in opportunities:
        if opp.occurrence_date and opp.score >= 0.7:
            return opp.occurrence_date
    return None
