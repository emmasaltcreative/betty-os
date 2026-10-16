"""Campaign intelligence — proactive planning on top of existing BettyOS campaigns."""

from __future__ import annotations

from src.campaign_intelligence.brief import generate_production_brief
from src.campaign_intelligence.calendar import evaluate_opportunities, holiday_date
from src.campaign_intelligence.engine import (
    accept_plan_and_generate_brief,
    accept_portfolio,
    missing_material_inputs,
    plan_campaign_intelligence,
    record_recommendation_decision,
    today_intelligence_card,
    update_estimates_after_capture,
)
from src.campaign_intelligence.estimates import (
    estimate_deliverables,
    estimate_runway,
    forbid_performance_forecast,
    recommend_cadence,
    revise_runway_after_capture,
)
from src.campaign_intelligence.models import (
    AlertType,
    CampaignInputs,
    CampaignIntelligence,
    CampaignRole,
    EvidenceKind,
    RecommendationDecision,
    TimingRelation,
)
from src.campaign_intelligence.scheduling import (
    is_overdue,
    lead_time_days,
    work_back_schedule,
)
from src.campaign_intelligence.store import (
    load_intelligence,
    newest_brief,
    resolve_brief_file,
    save_intelligence,
)

__all__ = [
    "AlertType",
    "CampaignInputs",
    "CampaignIntelligence",
    "CampaignRole",
    "EvidenceKind",
    "RecommendationDecision",
    "TimingRelation",
    "accept_plan_and_generate_brief",
    "accept_portfolio",
    "estimate_deliverables",
    "estimate_runway",
    "evaluate_opportunities",
    "forbid_performance_forecast",
    "generate_production_brief",
    "holiday_date",
    "is_overdue",
    "lead_time_days",
    "load_intelligence",
    "missing_material_inputs",
    "newest_brief",
    "plan_campaign_intelligence",
    "recommend_cadence",
    "record_recommendation_decision",
    "resolve_brief_file",
    "revise_runway_after_capture",
    "save_intelligence",
    "today_intelligence_card",
    "update_estimates_after_capture",
    "work_back_schedule",
]
