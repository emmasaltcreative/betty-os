"""Combined production session and shared shot planning."""

from __future__ import annotations

from src.campaign_intelligence.models import (
    CombinedProductionSession,
    DateRange,
    PortfolioRecommendation,
    RecommendationDecision,
    ShotPlanItem,
)


def build_combined_session(
    recommendations: list[PortfolioRecommendation],
    *,
    filming_minutes_available: int | None = None,
    platforms: list[str] | None = None,
) -> CombinedProductionSession:
    """Identify shared filming across accepted or pending primary+supporting campaigns."""
    active = [
        r
        for r in recommendations
        if r.decision
        in {
            RecommendationDecision.PENDING,
            RecommendationDecision.ACCEPT,
        }
    ]
    if not active:
        active = list(recommendations)

    names = [r.campaign_name for r in active]
    # Base filming from primary + modest add for supporting (shared session)
    film_min = 45
    film_max = 60
    assets_min = 4
    assets_max = 6
    runway_min = 10
    runway_max = 16
    for index, rec in enumerate(active):
        add = rec.estimated_additional_filming_minutes
        deliv = rec.estimated_deliverables
        run = rec.estimated_runway_days
        if index == 0:
            film_min = add.min_days or film_min
            film_max = add.max_days or film_max
            assets_min = deliv.min_days or assets_min
            assets_max = deliv.max_days or assets_max
            runway_min = run.min_days or runway_min
            runway_max = run.max_days or runway_max
        else:
            # Supporting adds partial time — shared hero shots avoid full duplication
            film_min += max(8, (add.min_days or 15) // 2)
            film_max += max(12, (add.max_days or 20) // 2)
            assets_min += max(1, (deliv.min_days or 2) // 2 + 1)
            assets_max += max(2, (deliv.max_days or 3) // 2 + 1)
            runway_min += max(3, (run.min_days or 5) // 2 + 2)
            runway_max += max(4, (run.max_days or 7) // 2 + 3)

    if filming_minutes_available is not None:
        film_max = min(film_max, filming_minutes_available)
        film_min = min(film_min, film_max)

    shots = _shot_plan(active, platforms or ["Instagram", "Pinterest"], film_max)
    formats = [
        "Reel / short video",
        "Video Pin",
        "Static Pin",
        "Carousel",
    ]

    notes = (
        "One filming session can support these campaigns. Shared hero shots come first; "
        "campaign-specific shots follow. Optional shots drop first when time is limited."
    )
    return CombinedProductionSession(
        session_name="Combined production session",
        campaign_names=names,
        filming_minutes=DateRange(film_min, film_max),
        expected_formats=formats,
        expected_assets=DateRange(assets_min, assets_max),
        combined_runway_days=DateRange(runway_min, runway_max),
        shots=shots,
        notes=notes,
        confidence="medium",
        assumptions=[
            "Shared hero shots avoid duplicate footage requests.",
            "Must-have shots take priority over optional coverage.",
            "Estimate assumes consistent natural light and no reshoot.",
        ],
    )


def _shot_plan(
    recommendations: list[PortfolioRecommendation],
    platforms: list[str],
    film_budget: int,
) -> list[ShotPlanItem]:
    primary = recommendations[0].campaign_name if recommendations else "Primary"
    supporting = (
        recommendations[1].campaign_name if len(recommendations) > 1 else None
    )
    campaigns = [primary] + ([supporting] if supporting else [])

    shots = [
        ShotPlanItem(
            shot_id="hero_ritual",
            description="Hero ritual wide: reading hour scene with quiet atmosphere",
            must_have=True,
            shared=True,
            campaigns=list(campaigns),
            framing="Vertical, centered subject with breathing room at top for type",
            lighting="Soft natural window light; avoid harsh overhead",
            props="Book, Heirloom Book Cover if available, candle unlit or softly lit",
            negative_space="Leave upper third and one side clear for typography",
            sequence_order=1,
        ),
        ShotPlanItem(
            shot_id="page_turn",
            description="Page-turn sequence — slow, considered, loop-friendly",
            must_have=True,
            shared=True,
            campaigns=list(campaigns),
            framing="Close detail, vertical or slightly tighter crop",
            lighting="Side window light across pages",
            props="Open book; commonplace book nearby optional",
            negative_space="Keep margins clean; no busy backgrounds",
            sequence_order=2,
        ),
        ShotPlanItem(
            shot_id="product_familiarity",
            description="Product familiarity: hands placing cover / glass / candle into scene",
            must_have=True,
            shared=bool(supporting),
            campaigns=list(campaigns),
            framing="Medium close; product readable without catalog energy",
            lighting="Same window setup — do not relight yet",
            props="One First Edition object at a time",
            negative_space="Quiet surface; no logo stacks",
            sequence_order=3,
        ),
        ShotPlanItem(
            shot_id="waitlist_cta_plate",
            description="Still plate for waitlist CTA overlay — calm desk vignette",
            must_have=True,
            shared=False,
            campaigns=[primary],
            framing="Vertical still with generous negative space",
            lighting="Even, soft",
            props="Minimal — one book and one object",
            negative_space="Large clear region for Join the waitlist type",
            sequence_order=4,
        ),
    ]

    if supporting:
        shots.append(
            ShotPlanItem(
                shot_id="familiarity_detail",
                description="Supporting detail: texture of cover or candle for education cuts",
                must_have=False,
                shared=False,
                campaigns=[supporting],
                framing="Macro / detail",
                lighting="Same setup before any prop change",
                props="Single object",
                negative_space="Not required",
                sequence_order=5,
            )
        )

    shots.append(
        ShotPlanItem(
            shot_id="optional_lifestyle",
            description="Optional lifestyle: founder hands pouring tea / settling into chair",
            must_have=False,
            shared=True,
            campaigns=list(campaigns),
            framing="Wider vertical lifestyle",
            lighting="Only if window light still holds",
            props="The Good Glass or tea",
            negative_space="Keep background quiet",
            sequence_order=6,
        )
    )

    # Trim optional shots when time is tight
    if film_budget < 50:
        shots = [s for s in shots if s.must_have]
    return shots
