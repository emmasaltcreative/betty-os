"""Orchestrate campaign intelligence planning for an existing campaign."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.campaign_intelligence.brief import generate_production_brief
from src.campaign_intelligence.calendar import evaluate_opportunities
from src.campaign_intelligence.estimates import (
    estimate_deliverables,
    estimate_runway,
    recommend_cadence,
    revise_runway_after_capture,
)
from src.campaign_intelligence.models import (
    CampaignInputs,
    CampaignIntelligence,
    LearningOutcome,
    PublishingPlanItem,
    RecommendationDecision,
)
from src.campaign_intelligence.production_session import build_combined_session
from src.campaign_intelligence.recommendations import build_alerts, build_portfolio_recommendations
from src.campaign_intelligence.store import (
    default_brand_inventory_available,
    load_intelligence,
    load_learning,
    save_intelligence,
    save_learning,
)
from src.common import DEFAULT_BRAND_ID


def plan_campaign_intelligence(
    *,
    campaign_dir: Path | None = None,
    campaign_name: str = "",
    inputs: CampaignInputs | None = None,
    piece_count: int = 5,
    brand_id: str = DEFAULT_BRAND_ID,
    as_of: date | None = None,
    persist: bool = True,
) -> CampaignIntelligence:
    """Build full intelligence snapshot. Optionally persist on the campaign folder."""
    as_of = as_of or date.today()
    existing = load_intelligence(campaign_dir) if campaign_dir else None
    inputs = inputs or (existing.inputs if existing else CampaignInputs())

    if inputs.inventory_available is None:
        inputs.inventory_available = default_brand_inventory_available(brand_id)

    if not inputs.business_objective and existing and existing.inputs.business_objective:
        inputs.business_objective = existing.inputs.business_objective

    opportunities = evaluate_opportunities(
        inputs=inputs, brand_id=brand_id, as_of=as_of
    )
    recommendations = build_portfolio_recommendations(
        inputs,
        campaign_name=campaign_name or (existing.campaign_name if existing else ""),
        opportunities=opportunities,
        as_of=as_of,
        brand_id=brand_id,
    )
    # Preserve prior decisions when re-planning same roles
    if existing:
        by_role = {r.role: r for r in existing.recommendations}
        for rec in recommendations:
            prior = by_role.get(rec.role)
            if prior and prior.decision != RecommendationDecision.PENDING:
                rec.decision = prior.decision
                rec.decision_at = prior.decision_at

    alerts = build_alerts(
        inputs,
        opportunities=opportunities,
        recommendations=recommendations,
        as_of=as_of,
    )
    session = build_combined_session(
        recommendations,
        filming_minutes_available=inputs.filming_minutes_available,
        platforms=inputs.preferred_platforms,
    )
    platforms = inputs.preferred_platforms or ["Instagram", "Pinterest"]
    deliverables = estimate_deliverables(
        piece_count=piece_count,
        platforms=platforms,
        filming_minutes_available=inputs.filming_minutes_available,
        must_have_shots=len([s for s in session.shots if s.must_have]),
    )
    # Prefer combined session asset range when portfolio has supporting campaign
    if len([r for r in recommendations if r.decision != RecommendationDecision.DISMISS]) > 1:
        deliverables.final_assets = session.expected_assets
        deliverables.filming_minutes = session.filming_minutes

    cadence = recommend_cadence(
        platforms=platforms,
        objective=inputs.business_objective,
        asset_count_max=deliverables.final_assets.max_days,
        has_connected_performance=False,
    )
    runway = estimate_runway(
        deliverables=deliverables, cadence=cadence, phase="pre_shoot", as_of=as_of
    )
    publishing = _default_publishing_plan(platforms, inputs.business_objective)

    intel = CampaignIntelligence(
        campaign_name=campaign_name
        or (existing.campaign_name if existing else "")
        or "Campaign",
        brand_id=brand_id,
        inputs=inputs,
        opportunities=opportunities,
        recommendations=recommendations,
        alerts=alerts,
        production_session=session,
        deliverable_estimate=deliverables,
        cadence=cadence,
        runway_history=[runway],
        publishing_plan=publishing,
        creative_direction=(
            existing.creative_direction
            if existing and existing.creative_direction
            else "Quiet ritual imagery, honest waitlist framing, product familiarity before the ask."
        ),
        portfolio_accepted=existing.portfolio_accepted if existing else False,
        plan_accepted_at=existing.plan_accepted_at if existing else None,
        newest_brief_id=existing.newest_brief_id if existing else None,
    )

    # Keep prior runway history when re-planning after capture
    if existing and existing.runway_history:
        prior_phases = {r.phase for r in existing.runway_history}
        if "post_capture" in prior_phases or "actual_published" in prior_phases:
            intel.runway_history = list(existing.runway_history) + [runway]

    if persist and campaign_dir is not None:
        save_intelligence(campaign_dir, intel)
        _seed_learning(campaign_dir, intel)

    return intel


def record_recommendation_decision(
    campaign_dir: Path,
    recommendation_id: str,
    decision: RecommendationDecision | str,
) -> CampaignIntelligence:
    intel = load_intelligence(campaign_dir)
    if intel is None:
        raise FileNotFoundError("No campaign intelligence saved for this campaign.")
    decision = RecommendationDecision(decision)
    now = datetime.now(timezone.utc).isoformat()
    for rec in intel.recommendations:
        if rec.recommendation_id == recommendation_id:
            rec.decision = decision
            rec.decision_at = now
    if decision == RecommendationDecision.ACCEPT:
        # Refresh combined session from accepted + primary
        accepted = [
            r
            for r in intel.recommendations
            if r.decision == RecommendationDecision.ACCEPT
            or r.role.value == "primary"
        ]
        intel.production_session = build_combined_session(
            accepted,
            filming_minutes_available=intel.inputs.filming_minutes_available,
            platforms=intel.inputs.preferred_platforms,
        )
    save_intelligence(campaign_dir, intel)
    return intel


def accept_portfolio(campaign_dir: Path) -> CampaignIntelligence:
    intel = load_intelligence(campaign_dir)
    if intel is None:
        raise FileNotFoundError("No campaign intelligence saved for this campaign.")
    now = datetime.now(timezone.utc).isoformat()
    for rec in intel.recommendations:
        if rec.decision == RecommendationDecision.PENDING:
            # Accept primary always; leave supporting pending unless already decided
            if rec.role.value == "primary":
                rec.decision = RecommendationDecision.ACCEPT
                rec.decision_at = now
    intel.portfolio_accepted = True
    save_intelligence(campaign_dir, intel)
    return intel


def accept_plan_and_generate_brief(
    campaign_dir: Path,
    *,
    include_csv: bool = False,
) -> dict[str, Any]:
    """Accept plan, generate Production Brief, persist, return download payload."""
    intel = load_intelligence(campaign_dir)
    if intel is None:
        raise FileNotFoundError("No campaign intelligence saved for this campaign.")

    now = datetime.now(timezone.utc).isoformat()
    for rec in intel.recommendations:
        if rec.decision == RecommendationDecision.PENDING and rec.role.value == "primary":
            rec.decision = RecommendationDecision.ACCEPT
            rec.decision_at = now
    # Include supporting if still pending when portfolio was broadly accepted
    if intel.portfolio_accepted:
        for rec in intel.recommendations:
            if rec.decision == RecommendationDecision.PENDING:
                rec.decision = RecommendationDecision.ACCEPT
                rec.decision_at = now

    intel.portfolio_accepted = True
    intel.plan_accepted_at = now
    accepted = [
        r
        for r in intel.recommendations
        if r.decision == RecommendationDecision.ACCEPT
    ]
    if accepted:
        intel.production_session = build_combined_session(
            accepted,
            filming_minutes_available=intel.inputs.filming_minutes_available,
            platforms=intel.inputs.preferred_platforms,
        )

    brief = generate_production_brief(
        campaign_dir, intel, include_csv=include_csv
    )
    save_intelligence(campaign_dir, intel)
    return {
        "intelligence": intel,
        "brief": brief,
    }


def update_estimates_after_capture(
    campaign_dir: Path,
    *,
    usable_shots: int,
    planned_shots: int | None = None,
    quality_note: str = "",
    actual_filming_minutes: int | None = None,
) -> CampaignIntelligence:
    intel = load_intelligence(campaign_dir)
    if intel is None:
        raise FileNotFoundError("No campaign intelligence saved for this campaign.")

    previous = intel.current_runway("pre_shoot") or intel.current_runway()
    if previous is None:
        raise ValueError("No pre-shoot runway estimate to revise.")

    planned = planned_shots
    if planned is None and intel.production_session:
        planned = len([s for s in intel.production_session.shots if s.must_have])
    planned = planned or max(usable_shots, 1)

    revised = revise_runway_after_capture(
        previous,
        usable_shots=usable_shots,
        planned_shots=planned,
        quality_note=quality_note,
    )
    intel.runway_history.append(revised)

    # Adjust deliverable estimate asset range
    if intel.deliverable_estimate:
        ratio = usable_shots / planned
        lo = max(1, int(intel.deliverable_estimate.final_assets.min_days * ratio))
        hi = max(lo, int(intel.deliverable_estimate.final_assets.max_days * ratio))
        intel.deliverable_estimate.final_assets.min_days = lo
        intel.deliverable_estimate.final_assets.max_days = hi

    save_intelligence(campaign_dir, intel)

    learning = load_learning(campaign_dir)
    if intel.deliverable_estimate:
        learning.estimated_filming_minutes = intel.deliverable_estimate.filming_minutes
        learning.estimated_final_assets = intel.deliverable_estimate.final_assets
        learning.estimated_usable_shots = previous.days  # placeholder span unused
    learning.actual_usable_shots = usable_shots
    if actual_filming_minutes is not None:
        learning.actual_filming_minutes = actual_filming_minutes
    learning.estimated_runway_days = previous.days
    # Store revised mid as note — actual runway filled later at publish time
    learning.notes = revised.reason_for_change
    save_learning(campaign_dir, learning)
    return intel


def missing_material_inputs(inputs: CampaignInputs) -> list[str]:
    """Progressive disclosure: only ask for fields that materially affect recommendations."""
    missing: list[str] = []
    if not inputs.business_objective.strip():
        missing.append("business_objective")
    if inputs.target_milestone_date is None and inputs.event_date is None:
        missing.append("target_milestone_date")
    if inputs.filming_minutes_available is None and not inputs.filming_availability:
        missing.append("filming_availability")
    if not inputs.preferred_platforms:
        missing.append("preferred_platforms")
    return missing


def today_intelligence_card(
    campaign_dir: Path | None,
    *,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """Single highest-value Today recommendation from campaign intelligence."""
    if campaign_dir is None:
        return None
    intel = load_intelligence(campaign_dir)
    if intel is None:
        return None
    as_of = as_of or date.today()

    high = [a for a in intel.alerts if a.high_value]
    # Prefer deadline/risk if overdue-ish, else opportunity
    risk = next((a for a in high if a.alert_type.value == "risk"), None)
    deadline = next((a for a in high if a.alert_type.value == "deadline"), None)
    opportunity = next((a for a in high if a.alert_type.value == "opportunity"), None)

    session = intel.production_session
    runway = intel.current_runway()
    film = None
    if session:
        film = f"{session.filming_minutes.min_days}–{session.filming_minutes.max_days} minutes"
    runway_label = None
    if runway:
        runway_label = (
            f"Approximately {runway.days.min_days}–{runway.days.max_days} days"
        )

    if risk:
        return {
            "kind": "risk",
            "title": risk.title,
            "body": risk.detail,
            "filming": film,
            "runway": runway_label,
            "action_label": "Review Recommendation",
            "action": "plan",
        }
    if deadline and deadline.start_by and (deadline.start_by - as_of).days <= 21:
        names = ", ".join(session.campaign_names) if session else intel.campaign_name
        return {
            "kind": "deadline",
            "title": "Your next deadline",
            "body": (
                f"Film {names} together by "
                f"{deadline.start_by.isoformat() if deadline.start_by else 'soon'}."
            ),
            "filming": film,
            "runway": runway_label,
            "action_label": "Review Production Brief",
            "action": "brief" if intel.newest_brief_id else "plan",
        }
    if opportunity:
        return {
            "kind": "opportunity",
            "title": "An opportunity is approaching",
            "body": opportunity.detail,
            "filming": film,
            "runway": runway_label,
            "action_label": "Review Recommendation",
            "action": "plan",
        }
    if intel.plan_accepted_at and intel.newest_brief_id:
        return {
            "kind": "brief_ready",
            "title": "Production Brief is ready",
            "body": f"Continue {intel.campaign_name} with the current production plan.",
            "filming": film,
            "runway": runway_label,
            "action_label": "Review Production Brief",
            "action": "brief",
        }
    return None


def _default_publishing_plan(
    platforms: list[str], objective: str
) -> list[PublishingPlanItem]:
    cta = "Join the waitlist" if "waitlist" in (objective or "").lower() else "Learn more"
    items = [
        PublishingPlanItem(
            0,
            "Day 1",
            "Instagram" if "Instagram" in platforms else platforms[0],
            "Reel",
            "Awareness",
            cta,
            "Primary",
            "",
        ),
        PublishingPlanItem(
            2,
            "Day 2–3",
            "Pinterest" if "Pinterest" in platforms else platforms[-1],
            "Video Pin",
            "Product familiarity",
            cta,
            "Supporting overlap",
            "Shares hero footage with primary",
        ),
        PublishingPlanItem(
            4,
            "Day 4–5",
            "Pinterest" if "Pinterest" in platforms else platforms[-1],
            "Static Pin",
            "Product familiarity",
            "First Edition",
            "Supporting",
            "",
        ),
        PublishingPlanItem(
            6,
            "Day 6–7",
            "Instagram" if "Instagram" in platforms else platforms[0],
            "Carousel",
            "Education",
            cta,
            "Primary",
            "",
        ),
    ]
    if "Email" in platforms or "Waitlist" in platforms:
        items.append(
            PublishingPlanItem(
                8,
                "This content window",
                "Email",
                "Campaign email",
                "Conversion",
                cta,
                "Primary",
                "",
            )
        )
    return items


def _seed_learning(campaign_dir: Path, intel: CampaignIntelligence) -> None:
    learning = load_learning(campaign_dir)
    if intel.deliverable_estimate:
        learning.estimated_filming_minutes = intel.deliverable_estimate.filming_minutes
        learning.estimated_final_assets = intel.deliverable_estimate.final_assets
        learning.estimated_editing_minutes = intel.deliverable_estimate.editing_minutes
    runway = intel.current_runway("pre_shoot") or intel.current_runway()
    if runway:
        learning.estimated_runway_days = runway.days
    primary = intel.primary_recommendation()
    if primary and primary.timing.recommended_start:
        learning.estimated_campaign_start = primary.timing.recommended_start
    save_learning(campaign_dir, learning)
