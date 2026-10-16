"""Lead-time lookups and work-back scheduling."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.campaign_intelligence.models import CampaignInputs, ScheduleDates
from src.campaign_intelligence.rules import lead_time_rule, load_strategy_rules


OBJECTIVE_LEAD_KEYS = {
    "grow the waitlist": "waitlist_or_preorder",
    "waitlist": "waitlist_or_preorder",
    "preorder": "waitlist_or_preorder",
    "launch a product": "major_product_launch",
    "product launch": "major_product_launch",
    "product education": "product_education",
    "increase product familiarity": "product_education",
    "product familiarity": "product_education",
    "seasonal": "small_seasonal",
    "holiday": "holiday_gifting",
    "gifting": "holiday_gifting",
    "partnership": "influencer_or_partnership",
    "influencer": "influencer_or_partnership",
    "paid": "paid_with_testing",
    "conversion": "product_education",
    "awareness": "simple_organic_burst",
    "organic": "simple_organic_burst",
}


def resolve_lead_time_key(objective: str, explicit_key: str | None = None) -> str:
    if explicit_key:
        return explicit_key
    text = (objective or "").strip().lower()
    for needle, key in OBJECTIVE_LEAD_KEYS.items():
        if needle in text:
            return key
    return "waitlist_or_preorder"


def lead_time_days(
    objective: str,
    *,
    explicit_key: str | None = None,
    rules: dict[str, Any] | None = None,
    inputs: CampaignInputs | None = None,
) -> tuple[int, int, str, list[str]]:
    """Return (min_days, max_days, label, assumptions)."""
    rules = rules or load_strategy_rules()
    key = resolve_lead_time_key(objective, explicit_key)
    rule = lead_time_rule(key, rules)
    min_days = int(rule.get("min_days") or 14)
    max_days = int(rule.get("max_days") or 28)
    label = str(rule.get("label") or key)
    assumptions = [
        f"Planning assumption: {label} typically needs {min_days}–{max_days} days of lead time.",
    ]

    inputs = inputs or CampaignInputs()
    # Adjust for filming / approval / reshoot buffers
    approval = int(rules.get("average_approval_turnaround_days") or 2)
    reshoot = int(rules.get("reshoot_buffer_days") or 3)
    min_days = max(min_days, approval + reshoot + 3)
    max_days = max(max_days, min_days + 7)
    assumptions.append(
        f"Includes about {approval} day(s) approval turnaround and {reshoot} day(s) reshoot buffer."
    )

    if inputs.filming_minutes_available is not None and inputs.filming_minutes_available < 45:
        min_days += 3
        max_days += 5
        assumptions.append(
            "Limited filming availability adds buffer for a second session if needed."
        )

    if inputs.inventory_available is False or (
        inputs.product_availability_date and inputs.target_milestone_date
        and inputs.product_availability_date > inputs.target_milestone_date
    ):
        assumptions.append(
            "Product availability constraints favor waitlist framing over availability promises."
        )

    if inputs.manufacturing_deadline and inputs.target_milestone_date:
        if inputs.manufacturing_deadline > inputs.target_milestone_date - timedelta(days=14):
            max_days += 7
            assumptions.append(
                "Manufacturing timeline is tight relative to the target milestone."
            )

    return min_days, max_days, label, assumptions


def work_back_schedule(
    milestone: date | None,
    *,
    objective: str,
    explicit_key: str | None = None,
    rules: dict[str, Any] | None = None,
    inputs: CampaignInputs | None = None,
    as_of: date | None = None,
) -> ScheduleDates:
    """Calculate start-by and production deadlines backward from a milestone."""
    as_of = as_of or date.today()
    rules = rules or load_strategy_rules()
    min_days, max_days, label, assumptions = lead_time_days(
        objective, explicit_key=explicit_key, rules=rules, inputs=inputs
    )
    approval = int(rules.get("average_approval_turnaround_days") or 2)
    reshoot = int(rules.get("reshoot_buffer_days") or 3)

    if milestone is None:
        # No false precision — recommend starting soon with a range note.
        return ScheduleDates(
            recommended_start=as_of,
            latest_safe_start=as_of + timedelta(days=7),
            production_deadline=as_of + timedelta(days=min_days),
            asset_deadline=as_of + timedelta(days=max(3, min_days - approval - 2)),
            approval_deadline=as_of + timedelta(days=max(5, min_days - 1)),
            milestone_date=None,
            range_note=(
                f"No confirmed milestone date. Using {label} planning range "
                f"({min_days}–{max_days} days). Confirm dates before treating deadlines as hard."
            ),
        )

    recommended_start = milestone - timedelta(days=max_days)
    latest_safe = milestone - timedelta(days=min_days)
    approval_deadline = milestone - timedelta(days=max(1, approval))
    production_deadline = approval_deadline - timedelta(days=max(2, reshoot // 2 + 1))
    asset_deadline = production_deadline - timedelta(days=2)

    range_note = (
        f"Work-back from {milestone.isoformat()} using {label} "
        f"({min_days}–{max_days} days). Dates are ranges, not exact promises."
    )
    if latest_safe < as_of:
        range_note += " Latest safe start is already overdue relative to today."

    # Attach assumptions into range note briefly
    if assumptions:
        range_note += " " + assumptions[0]

    return ScheduleDates(
        recommended_start=recommended_start,
        latest_safe_start=latest_safe,
        production_deadline=production_deadline,
        asset_deadline=asset_deadline,
        approval_deadline=approval_deadline,
        milestone_date=milestone,
        range_note=range_note,
    )


def is_overdue(schedule: ScheduleDates, *, as_of: date | None = None) -> bool:
    as_of = as_of or date.today()
    if schedule.latest_safe_start and schedule.latest_safe_start < as_of:
        return True
    if schedule.production_deadline and schedule.production_deadline < as_of:
        return True
    return False
