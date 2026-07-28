"""Score models and validation for the Review Brain."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from review.recommendations import (
    Recommendation,
    parse_recommendation_payload,
    recommendations_to_json,
    structure_improvements,
)

SCORE_DIMENSIONS: tuple[str, ...] = (
    "brand_alignment",
    "business_alignment",
    "emotional_specificity",
    "editorial_quality",
    "visual_consistency",
    "conversion_potential",
    "overall_readiness",
)

SCORE_LABELS: dict[str, str] = {
    "brand_alignment": "Brand Alignment",
    "business_alignment": "Business Alignment",
    "emotional_specificity": "Emotional Specificity",
    "editorial_quality": "Editorial Quality",
    "visual_consistency": "Visual Consistency",
    "conversion_potential": "Conversion Potential",
    "overall_readiness": "Overall Readiness",
}


class ScoreItem(BaseModel):
    score: float = Field(ge=0, le=10)
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_must_critique(cls, value: str) -> str:
        text = value.strip()
        if len(text) < 40:
            raise ValueError("Reason must be a real critique (at least ~2 sentences).")
        return text


class ReviewResult(BaseModel):
    brand_alignment: ScoreItem
    business_alignment: ScoreItem
    emotional_specificity: ScoreItem
    editorial_quality: ScoreItem
    visual_consistency: ScoreItem
    conversion_potential: ScoreItem
    overall_readiness: ScoreItem
    highest_impact_improvements: list[str] = Field(min_length=3, max_length=3)
    recommendations: list[Recommendation] = Field(default_factory=list)

    def scores_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in SCORE_DIMENSIONS:
            item: ScoreItem = getattr(self, key)
            payload[key] = {
                "label": SCORE_LABELS[key],
                "score": item.score,
                "reason": item.reason,
            }
        payload["highest_impact_improvements"] = list(self.highest_impact_improvements)
        if self.recommendations:
            payload["recommendations"] = recommendations_to_json(self.recommendations)
        else:
            payload["recommendations"] = recommendations_to_json(
                structure_improvements(self.highest_impact_improvements)
            )
        payload["overall_readiness_score"] = self.overall_readiness.score
        return payload


def parse_review_payload(data: dict[str, Any]) -> ReviewResult:
    """Normalize Claude JSON into a validated ReviewResult."""
    scores_raw = data.get("scores")
    if not isinstance(scores_raw, dict):
        raise ValueError("Review JSON must include a 'scores' object.")

    kwargs: dict[str, Any] = {}
    for key in SCORE_DIMENSIONS:
        entry = scores_raw.get(key)
        if not isinstance(entry, dict):
            raise ValueError(f"Missing score entry: {key}")
        kwargs[key] = ScoreItem(
            score=float(entry["score"]),
            reason=str(entry.get("reason", "")),
        )

    improvements = data.get("highest_impact_improvements")
    if not isinstance(improvements, list):
        raise ValueError("highest_impact_improvements must be a list of three strings.")
    cleaned = [str(item).strip() for item in improvements if str(item).strip()]
    if len(cleaned) < 3:
        raise ValueError("Need exactly three highest-impact improvements.")
    kwargs["highest_impact_improvements"] = cleaned[:3]

    structured = parse_recommendation_payload(data.get("recommendations"))
    if not structured:
        structured = structure_improvements(cleaned[:3])
    kwargs["recommendations"] = structured
    return ReviewResult(**kwargs)


def ensure_scores_recommendations(scores: dict[str, Any]) -> dict[str, Any]:
    """Backfill structured recommendations onto an existing scores payload."""
    payload = dict(scores)
    existing = payload.get("recommendations")
    improvements = [str(i) for i in payload.get("highest_impact_improvements") or []]
    structured = structure_improvements(
        improvements,
        existing=existing if isinstance(existing, list) else None,
    )
    payload["recommendations"] = recommendations_to_json(structured)
    return payload
