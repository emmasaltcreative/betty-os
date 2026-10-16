"""Deliverable, cadence, and content-runway operational estimates."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.campaign_intelligence.models import (
    CadenceRecommendation,
    CampaignInputs,
    DateRange,
    DeliverableEstimate,
    EvidenceKind,
    EvidenceLabel,
    RunwayEstimate,
)
from src.campaign_intelligence.rules import load_strategy_rules, preferred_cadence


ASSUMPTION_EVIDENCE = EvidenceLabel(
    EvidenceKind.PLANNING_ASSUMPTION,
    "Recommended cadence based on campaign needs and current planning assumptions.",
)

OPERATIONAL_EVIDENCE = EvidenceLabel(
    EvidenceKind.OPERATIONAL_ESTIMATE,
    "Operational content-output estimate, not a performance forecast.",
)


def forbid_performance_forecast(
    has_connected_performance: bool = False,
) -> EvidenceLabel:
    """Never label operational estimates as forecasts without connected evidence."""
    if has_connected_performance:
        return EvidenceLabel(
            EvidenceKind.CONNECTED_PERFORMANCE_EVIDENCE,
            "Supported by connected performance evidence.",
        )
    return OPERATIONAL_EVIDENCE


def estimate_deliverables(
    *,
    piece_count: int,
    platforms: list[str],
    filming_minutes_available: int | None = None,
    must_have_shots: int | None = None,
    rules: dict[str, Any] | None = None,
) -> DeliverableEstimate:
    rules = rules or load_strategy_rules()
    assumptions_cfg = rules.get("deliverable_assumptions") or {}
    usable_rate = float(assumptions_cfg.get("usable_shot_rate") or 0.7)
    per_min = float(assumptions_cfg.get("assets_per_hero_shot_min") or 1)
    per_max = float(assumptions_cfg.get("assets_per_hero_shot_max") or 2)
    edit_min = int(assumptions_cfg.get("editing_minutes_per_asset_min") or 4)
    edit_max = int(assumptions_cfg.get("editing_minutes_per_asset_max") or 7)
    approval = int(rules.get("average_approval_turnaround_days") or 2)

    shots = must_have_shots if must_have_shots is not None else max(3, piece_count + 1)
    usable_min = max(1, int(shots * usable_rate * 0.85))
    usable_max = max(usable_min, int(shots * usable_rate * 1.15) + 1)

    assets_min = max(piece_count, int(usable_min * per_min))
    assets_max = max(assets_min, int(usable_max * per_max))
    # Cap inflation — quality over volume
    assets_max = min(assets_max, max(assets_min + 3, piece_count + 4))

    default_film = int(rules.get("filming_availability_default_minutes") or 60)
    film_avail = filming_minutes_available or default_film
    film_min = max(25, min(film_avail, 20 + shots * 6))
    film_max = max(film_min, min(film_avail + 15, film_min + 20))

    formats = _formats_for_platforms(platforms)
    assumptions = [
        "Most planned hero shots are usable.",
        "Natural light remains consistent.",
        "No reshoot is required.",
        "At least one strong product or ritual sequence is captured.",
    ]

    return DeliverableEstimate(
        final_assets=DateRange(assets_min, assets_max),
        formats=formats,
        platforms=list(platforms) or ["Instagram", "Pinterest"],
        filming_minutes=DateRange(film_min, film_max),
        editing_minutes=DateRange(assets_min * edit_min, assets_max * edit_max),
        approval_days=DateRange(max(1, approval - 1), approval + 1),
        confidence="medium",
        assumptions=assumptions,
        evidence=OPERATIONAL_EVIDENCE,
    )


def recommend_cadence(
    *,
    platforms: list[str],
    objective: str = "",
    asset_count_max: int = 6,
    campaign_duration_days: int | None = None,
    has_connected_performance: bool = False,
    rules: dict[str, Any] | None = None,
) -> list[CadenceRecommendation]:
    rules = rules or load_strategy_rules()
    if has_connected_performance:
        # Still do not invent forecasts — only acknowledge evidence exists.
        evidence = EvidenceLabel(
            EvidenceKind.CONNECTED_PERFORMANCE_EVIDENCE,
            "Cadence informed by connected performance evidence where available; "
            "still treat as a recommendation, not a proven optimum.",
        )
    else:
        evidence = ASSUMPTION_EVIDENCE

    results: list[CadenceRecommendation] = []
    platforms = platforms or ["Instagram", "Pinterest"]
    for platform in platforms:
        lo, hi = preferred_cadence(platform, rules)
        # Stretch runway when assets are limited
        if asset_count_max < 5:
            lo = max(1, lo - 1)
            hi = max(lo, hi - 1)
        if "waitlist" in (objective or "").lower() and platform in {"Instagram", "Pinterest"}:
            reason = (
                "Repeated exposure supports waitlist familiarity without exhausting "
                "the current asset set."
            )
        else:
            reason = (
                "Provides repeated exposure without exhausting the current asset set."
            )
        if campaign_duration_days and campaign_duration_days < 14:
            hi = max(lo, min(hi, 4))
            reason += " Campaign window is short, so cadence stays moderate."
        results.append(
            CadenceRecommendation(
                platform=platform,
                min_per_week=lo,
                max_per_week=hi,
                reason=reason,
                evidence=evidence,
            )
        )
    return results


def estimate_runway(
    *,
    deliverables: DeliverableEstimate,
    cadence: list[CadenceRecommendation],
    phase: str = "pre_shoot",
    as_of: date | None = None,
    reason_for_change: str = "",
) -> RunwayEstimate:
    as_of = as_of or date.today()
    # Combined posts per week across platforms (average of midpoints, not sum —
    # same assets often cross-post). Use dominant platform midpoints blended.
    if not cadence:
        posts_lo, posts_hi = 2.0, 3.0
    else:
        mids = [(c.min_per_week + c.max_per_week) / 2 for c in cadence]
        # Cross-post factor: primary cadence drives runway more than sum.
        primary = max(mids) if mids else 2.5
        secondary = (sum(mids) / len(mids)) if mids else 2.0
        posts_lo = max(1.0, min(primary, secondary) * 0.85)
        posts_hi = max(posts_lo, primary * 1.1)

    assets_min = deliverables.final_assets.min_days
    assets_max = deliverables.final_assets.max_days
    # Days of runway ≈ assets / posts_per_week * 7
    days_min = max(3, int((assets_min / posts_hi) * 7))
    days_max = max(days_min, int((assets_max / posts_lo) * 7))
    weeks_min = max(1, round(days_min / 7))
    weeks_max = max(weeks_min, round(days_max / 7))

    by_platform: dict[str, dict[str, int]] = {}
    for item in cadence:
        mid = max(1.0, (item.min_per_week + item.max_per_week) / 2)
        by_platform[item.platform] = {
            "min_days": max(3, int((assets_min / mid) * 7)),
            "max_days": max(3, int((assets_max / max(0.5, mid * 0.85)) * 7)),
        }

    return RunwayEstimate(
        phase=phase,
        days=DateRange(days_min, days_max),
        weeks=DateRange(weeks_min, weeks_max, unit="weeks"),
        approximate_start=as_of,
        approximate_end=as_of + timedelta(days=days_max),
        by_platform=by_platform,
        confidence=deliverables.confidence,
        assumptions=list(deliverables.assumptions),
        reason_for_change=reason_for_change,
        evidence=OPERATIONAL_EVIDENCE,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def revise_runway_after_capture(
    previous: RunwayEstimate,
    *,
    usable_shots: int,
    planned_shots: int,
    quality_note: str = "",
) -> RunwayEstimate:
    """Update runway after footage review while preserving history externally."""
    if planned_shots <= 0:
        planned_shots = max(1, usable_shots)
    ratio = usable_shots / planned_shots
    new_min = max(2, int(previous.days.min_days * ratio))
    new_max = max(new_min, int(previous.days.max_days * ratio))
    if ratio >= 1.1:
        reason = quality_note or (
            "Capture produced more usable variations than the pre-shoot estimate assumed."
        )
        confidence = "medium"
    elif ratio <= 0.75:
        reason = quality_note or (
            "Capture quality reduced the number of publishable clips versus the pre-shoot estimate."
        )
        confidence = "medium"
    else:
        reason = quality_note or "Capture aligned closely with the pre-shoot estimate."
        confidence = previous.confidence

    weeks_min = max(1, round(new_min / 7))
    weeks_max = max(weeks_min, round(new_max / 7))
    as_of = previous.approximate_start or date.today()
    return RunwayEstimate(
        phase="post_capture",
        days=DateRange(new_min, new_max),
        weeks=DateRange(weeks_min, weeks_max, unit="weeks"),
        approximate_start=as_of,
        approximate_end=as_of + timedelta(days=new_max),
        by_platform=dict(previous.by_platform),
        confidence=confidence,
        assumptions=list(previous.assumptions),
        reason_for_change=reason,
        evidence=OPERATIONAL_EVIDENCE,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def _formats_for_platforms(platforms: list[str]) -> list[str]:
    formats: list[str] = []
    lowered = {p.lower() for p in platforms}
    if "instagram" in lowered or "tiktok" in lowered or "youtube shorts" in lowered:
        formats.append("Reel / short video")
    if "pinterest" in lowered:
        formats.extend(["Video Pin", "Static Pin"])
    if "instagram" in lowered:
        formats.append("Carousel")
    if "email" in lowered or "waitlist" in lowered:
        formats.append("Email / waitlist creative")
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for item in formats:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out or ["Short video", "Static image"]
