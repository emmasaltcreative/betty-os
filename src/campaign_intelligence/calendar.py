"""Commerce and opportunity calendar with real calendar-date calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from src.campaign_intelligence.models import CalendarOpportunity, CampaignInputs
from src.campaign_intelligence.rules import load_calendar_rules, load_strategy_rules
from src.common import DEFAULT_BRAND_ID


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    name: str
    category: str
    date_resolver: Callable[[int], date | None]
    default_brand: float
    default_product: float
    default_audience: float
    default_commercial: float
    lead_time_key: str = "small_seasonal"
    uncertain: bool = False


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th weekday (Mon=0) in month. n may be negative for last."""
    if n > 0:
        first = date(year, month, 1)
        adjust = (weekday - first.weekday()) % 7
        return first + timedelta(days=adjust + 7 * (n - 1))
    # last weekday
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    adjust = (last.weekday() - weekday) % 7
    return last - timedelta(days=adjust)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _fixed(month: int, day: int) -> Callable[[int], date | None]:
    return lambda year: date(year, month, day)


def occurrence_for_planning_period(
    resolver: Callable[[int], date | None],
    *,
    as_of: date,
    horizon_days: int = 400,
) -> date | None:
    """Next occurrence on or after as_of within horizon; else nearest upcoming."""
    candidates: list[date] = []
    for year in (as_of.year - 1, as_of.year, as_of.year + 1, as_of.year + 2):
        try:
            value = resolver(year)
        except ValueError:
            value = None
        if value is not None:
            candidates.append(value)
    future = [d for d in candidates if d >= as_of]
    if not future:
        return None
    chosen = min(future)
    if (chosen - as_of).days > horizon_days:
        return None
    return chosen


CANONICAL_EVENTS: tuple[CanonicalEvent, ...] = (
    CanonicalEvent(
        "valentines_day",
        "Valentine's Day",
        "holiday",
        _fixed(2, 14),
        0.55,
        0.6,
        0.65,
        0.75,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "mothers_day",
        "Mother's Day",
        "holiday",
        lambda y: _nth_weekday(y, 5, 6, 2),  # 2nd Sunday in May
        0.7,
        0.7,
        0.75,
        0.8,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "graduation_season",
        "Graduation season",
        "seasonal",
        _fixed(5, 15),
        0.45,
        0.4,
        0.5,
        0.45,
        "small_seasonal",
    ),
    CanonicalEvent(
        "summer_travel",
        "Summer travel",
        "seasonal",
        _fixed(6, 15),
        0.5,
        0.45,
        0.55,
        0.4,
        "small_seasonal",
    ),
    CanonicalEvent(
        "back_to_school",
        "Back to school",
        "retail",
        _fixed(8, 15),
        0.55,
        0.5,
        0.6,
        0.5,
        "small_seasonal",
    ),
    CanonicalEvent(
        "fall_reading_season",
        "Fall reading season",
        "literary",
        _fixed(9, 1),
        0.95,
        0.95,
        0.95,
        0.7,
        "product_education",
    ),
    CanonicalEvent(
        "halloween",
        "Halloween",
        "holiday",
        _fixed(10, 31),
        0.25,
        0.2,
        0.3,
        0.35,
        "small_seasonal",
    ),
    CanonicalEvent(
        "thanksgiving",
        "Thanksgiving",
        "holiday",
        lambda y: _nth_weekday(y, 11, 3, 4),  # 4th Thursday in November
        0.55,
        0.5,
        0.6,
        0.65,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "black_friday",
        "Black Friday",
        "retail",
        lambda y: _nth_weekday(y, 11, 3, 4) + timedelta(days=1),
        0.35,
        0.4,
        0.4,
        0.85,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "cyber_monday",
        "Cyber Monday",
        "retail",
        lambda y: _nth_weekday(y, 11, 3, 4) + timedelta(days=4),
        0.3,
        0.35,
        0.35,
        0.8,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "holiday_gifting",
        "Holiday gifting",
        "gifting",
        _fixed(12, 1),
        0.8,
        0.85,
        0.85,
        0.9,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "final_holiday_shipping",
        "Final holiday shipping cutoff",
        "deadline",
        _fixed(12, 15),
        0.7,
        0.75,
        0.7,
        0.95,
        "holiday_gifting",
    ),
    CanonicalEvent(
        "new_year",
        "New Year",
        "holiday",
        _fixed(1, 1),
        0.6,
        0.55,
        0.65,
        0.5,
        "small_seasonal",
    ),
    CanonicalEvent(
        "national_book_month",
        "National Book Month",
        "literary",
        _fixed(10, 1),
        0.95,
        0.9,
        0.9,
        0.55,
        "product_education",
    ),
    CanonicalEvent(
        "world_book_day",
        "World Book Day",
        "literary",
        _fixed(4, 23),
        0.9,
        0.85,
        0.9,
        0.5,
        "product_education",
    ),
    # Explicitly curated novelty events — exist so exclusion rules can filter them.
    CanonicalEvent(
        "national_pizza_day",
        "National Pizza Day",
        "novelty",
        _fixed(2, 9),
        0.05,
        0.05,
        0.05,
        0.05,
        "simple_organic_burst",
    ),
    CanonicalEvent(
        "national_dog_day",
        "National Dog Day",
        "novelty",
        _fixed(8, 26),
        0.05,
        0.05,
        0.05,
        0.05,
        "simple_organic_burst",
    ),
    CanonicalEvent(
        "april_fools",
        "April Fools' Day",
        "novelty",
        _fixed(4, 1),
        0.05,
        0.05,
        0.1,
        0.1,
        "simple_organic_burst",
    ),
    CanonicalEvent(
        "super_bowl",
        "Super Bowl",
        "novelty",
        lambda y: _nth_weekday(y, 2, 6, 2),  # approx 2nd Sunday Feb (varies historically)
        0.05,
        0.05,
        0.1,
        0.2,
        "simple_organic_burst",
    ),
    CanonicalEvent(
        "st_patricks_day",
        "St. Patrick's Day",
        "novelty",
        _fixed(3, 17),
        0.1,
        0.05,
        0.15,
        0.2,
        "simple_organic_burst",
    ),
)


def evaluate_opportunities(
    *,
    inputs: CampaignInputs | None = None,
    brand_id: str = DEFAULT_BRAND_ID,
    as_of: date | None = None,
    user_events: list[dict[str, Any]] | None = None,
    inventory_available: bool | None = None,
) -> list[CalendarOpportunity]:
    """Score and filter calendar opportunities for the brand and planning context."""
    as_of = as_of or date.today()
    inputs = inputs or CampaignInputs()
    calendar_rules = load_calendar_rules(brand_id)
    strategy = load_strategy_rules()
    included = set(calendar_rules.get("included_event_ids") or [])
    excluded = set(calendar_rules.get("excluded_event_ids") or [])
    weights = calendar_rules.get("relevance_weights") or {}
    strong = calendar_rules.get("strong_alignments") or {}
    weak = calendar_rules.get("weak_or_conditional") or {}
    inventory_sensitive = set(calendar_rules.get("inventory_sensitive_event_ids") or [])
    inv = (
        inventory_available
        if inventory_available is not None
        else inputs.inventory_available
    )
    if inv is None:
        inv = False  # Oh Betty default: waitlist / no inventory

    results: list[CalendarOpportunity] = []
    for event in CANONICAL_EVENTS:
        if event.event_id in excluded:
            continue
        # Novelty never recommended for this brand unless explicitly included.
        if event.category == "novelty" and event.event_id not in included:
            continue

        occurrence = occurrence_for_planning_period(event.date_resolver, as_of=as_of)
        brand_r = event.default_brand
        product_r = event.default_product
        audience_r = event.default_audience
        commercial_r = event.default_commercial

        if event.event_id in weak:
            brand_r *= 0.6
            audience_r *= 0.7

        if event.event_id in inventory_sensitive and not inv:
            commercial_r *= 0.35
            product_r *= 0.5

        score = (
            brand_r * float(weights.get("brand", 1))
            + product_r * float(weights.get("product", 1))
            + audience_r * float(weights.get("audience", 1))
            + commercial_r * float(weights.get("commercial", 0.85))
        ) / 4.0

        # Lead-time feasibility
        lead = (strategy.get("lead_times") or {}).get(event.lead_time_key) or {}
        lead_min = int(lead.get("min_days") or 14)
        days_until = (occurrence - as_of).days if occurrence else None
        if days_until is not None and days_until < lead_min // 2:
            score *= 0.55

        reason = strong.get(event.event_id) or weak.get(event.event_id) or event.name
        if event.event_id in inventory_sensitive and not inv:
            reason = (
                f"{reason}. Inventory is not available — prefer waitlist or awareness "
                "framing over availability promises."
            )

        # Filter low-value noise
        if score < 0.35 and event.event_id not in strong:
            continue
        if included and event.event_id not in included and score < 0.55:
            continue

        results.append(
            CalendarOpportunity(
                event_id=event.event_id,
                name=event.name,
                occurrence_date=occurrence,
                date_uncertain=event.uncertain or occurrence is None,
                category=event.category,
                brand_relevance=round(brand_r, 3),
                product_relevance=round(product_r, 3),
                audience_relevance=round(audience_r, 3),
                commercial_relevance=round(commercial_r, 3),
                score=round(score, 3),
                reason=reason,
                lead_time_days=lead_min,
                included=True,
            )
        )

    # User-created milestones / events
    for raw in user_events or []:
        name = str(raw.get("name") or "Custom event")
        event_id = str(raw.get("event_id") or f"user_{name.lower().replace(' ', '_')}")
        occ = raw.get("occurrence_date")
        if isinstance(occ, str):
            try:
                occ_date: date | None = date.fromisoformat(occ[:10])
            except ValueError:
                occ_date = None
        elif isinstance(occ, date):
            occ_date = occ
        else:
            occ_date = None
        uncertain = bool(raw.get("date_uncertain")) or occ_date is None
        results.append(
            CalendarOpportunity(
                event_id=event_id,
                name=name,
                occurrence_date=occ_date,
                date_uncertain=uncertain,
                category=str(raw.get("category") or "user"),
                brand_relevance=float(raw.get("brand_relevance") or 0.8),
                product_relevance=float(raw.get("product_relevance") or 0.8),
                audience_relevance=float(raw.get("audience_relevance") or 0.8),
                commercial_relevance=float(raw.get("commercial_relevance") or 0.8),
                score=float(raw.get("score") or 0.85),
                reason=str(raw.get("reason") or "Founder-entered milestone"),
                lead_time_days=raw.get("lead_time_days"),
                included=True,
            )
        )

    # Inject planning inputs as milestones
    milestone_map = [
        ("target_launch", "Target launch", inputs.target_milestone_date),
        ("product_availability", "Product availability", inputs.product_availability_date),
        ("shipping_cutoff", "Shipping cutoff", inputs.shipping_cutoff),
        ("event_date", "Event", inputs.event_date),
        ("partnership_date", "Partnership", inputs.partnership_date),
        ("preorder_start", "Preorder start", inputs.preorder_start_date),
        ("manufacturing_deadline", "Manufacturing deadline", inputs.manufacturing_deadline),
        ("inventory_arrival", "Inventory arrival", inputs.inventory_arrival_date),
    ]
    for event_id, name, occ_date in milestone_map:
        if occ_date is None:
            continue
        certainty = (inputs.date_certainty or {}).get(event_id, "confirmed")
        results.append(
            CalendarOpportunity(
                event_id=event_id,
                name=name,
                occurrence_date=occ_date,
                date_uncertain=certainty != "confirmed",
                category="milestone",
                brand_relevance=1.0,
                product_relevance=1.0,
                audience_relevance=0.9,
                commercial_relevance=1.0,
                score=1.0,
                reason="Campaign planning milestone",
                lead_time_days=None,
                included=True,
            )
        )

    results.sort(
        key=lambda o: (
            -(o.score),
            o.occurrence_date or date.max,
        )
    )
    return results


def holiday_date(event_id: str, year: int) -> date | None:
    for event in CANONICAL_EVENTS:
        if event.event_id == event_id:
            return event.date_resolver(year)
    return None
