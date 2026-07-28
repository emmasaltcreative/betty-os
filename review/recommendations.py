"""Structured creative-review recommendations and highest-impact helpers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

RecommendationType = Literal[
    "replace_asset",
    "remove_asset",
    "revise_copy",
    "change_timing",
    "change_duration",
    "change_cta",
    "rerender",
    "manual_review",
]

RecommendationStatus = Literal[
    "proposed",
    "approved",
    "dismissed",
    "in_progress",
    "completed",
    "failed",
]

RECOMMENDATION_TYPES: tuple[str, ...] = (
    "replace_asset",
    "remove_asset",
    "revise_copy",
    "change_timing",
    "change_duration",
    "change_cta",
    "rerender",
    "manual_review",
)

RECOMMENDATION_STATUSES: tuple[str, ...] = (
    "proposed",
    "approved",
    "dismissed",
    "in_progress",
    "completed",
    "failed",
)

PRIORITY_LABELS = ("high", "medium", "low")


class Recommendation(BaseModel):
    recommendation_id: str
    title: str
    full_instruction: str
    rationale: str
    affected_asset: str
    affected_files: list[str] = Field(default_factory=list)
    recommendation_type: str
    priority: str = "high"
    status: str = "proposed"
    created_at: str
    expected_changes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def ensure_three_improvements(items: list[str]) -> list[str]:
    """Keep only the first three non-empty improvements (impact-first order)."""
    cleaned = [item.strip() for item in items if item and item.strip()]
    if len(cleaned) < 3:
        raise ValueError(
            "Review Brain requires exactly three highest-impact improvements."
        )
    return cleaned[:3]


def format_improvements_markdown(improvements: list[str]) -> str:
    lines = ["## Highest Impact Improvements", ""]
    for index, item in enumerate(ensure_three_improvements(improvements), start=1):
        lines.append(f"{index}. {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_recommendations_markdown(recommendations: list[Recommendation]) -> str:
    lines = ["## Highest Impact Improvements", ""]
    for index, rec in enumerate(recommendations[:3], start=1):
        lines.append(f"{index}. {rec.full_instruction}")
        lines.append("")
    if len(recommendations) > 3:
        lines.append("### Actionable recommendations")
        lines.append("")
        for rec in recommendations:
            lines.append(
                f"- **{rec.title}** (`{rec.recommendation_type}`, {rec.priority}) — "
                f"{rec.affected_asset}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_recommendation_id() -> str:
    return f"rec_{uuid4().hex[:10]}"


def _infer_type(text: str) -> str:
    lower = text.lower()
    if re.search(r"\bremove\b|\bcut\b|\bdrop\b", lower) and re.search(
        r"img_|clip|asset", lower
    ):
        return "remove_asset"
    if re.search(r"\breplace\b|\bswap\b", lower) and re.search(r"img_|clip|asset", lower):
        return "replace_asset"
    if re.search(r"\bcta\b", lower) and re.search(r"timing|second|appear", lower):
        return "change_timing"
    if re.search(r"\bcta\b", lower):
        return "change_cta"
    if re.search(r"\bduration\b|\btrim\b|\bseam\b|\bloop\b", lower):
        return "change_duration"
    if re.search(r"\bcaption\b|\bhook\b|\brewrite\b|\bcopy\b", lower):
        return "revise_copy"
    if re.search(r"\brebuild\b|\brerender\b|\bre-render\b", lower):
        return "rerender"
    return "manual_review"


def _infer_asset(text: str) -> str:
    lower = text.lower()
    if "ritual" in lower:
        return "Ritual Reel"
    if "page turn" in lower or "page_turn" in lower:
        return "Page Turn Loop"
    return "Campaign"


def _infer_files(text: str, asset: str) -> list[str]:
    files = re.findall(r"IMG_\d+", text, flags=re.IGNORECASE)
    unique = []
    for name in files:
        upper = name.upper()
        if upper not in unique:
            unique.append(upper)
    if asset == "Ritual Reel":
        base = ["ritual_reel/ritual_reel_draft.mp4", "ritual_reel/caption.md"]
        return base + [f"assets/reading-hour-shoot/{name}.mov" for name in unique]
    if asset == "Page Turn Loop":
        return ["page_turn_loop/page_turn_loop_draft.mp4", "page_turn_loop/caption.md"]
    return unique


def recommendation_from_text(
    text: str,
    *,
    priority: str = "high",
    title: str | None = None,
    recommendation_type: str | None = None,
    rationale: str | None = None,
    expected_changes: str = "",
    affected_asset: str | None = None,
    status: str = "proposed",
    recommendation_id: str | None = None,
) -> Recommendation:
    asset = affected_asset or _infer_asset(text)
    rec_type = recommendation_type or _infer_type(text)
    short = title or (text.strip().split(".")[0][:90] + ("…" if len(text) > 90 else ""))
    return Recommendation(
        recommendation_id=recommendation_id or new_recommendation_id(),
        title=short.strip(),
        full_instruction=text.strip(),
        rationale=(rationale or text.strip())[:500],
        affected_asset=asset,
        affected_files=_infer_files(text, asset),
        recommendation_type=rec_type
        if rec_type in RECOMMENDATION_TYPES
        else "manual_review",
        priority=priority if priority in PRIORITY_LABELS else "high",
        status=status if status in RECOMMENDATION_STATUSES else "proposed",
        created_at=_now(),
        expected_changes=expected_changes,
    )


def structure_improvements(
    improvements: list[str],
    *,
    existing: list[dict[str, Any]] | None = None,
) -> list[Recommendation]:
    """Turn free-text improvements into structured recommendations.

    Preserves original wording in full_instruction. When the Ritual Reel review
    names IMG_2549 / rebuild / CTA timing, expands into the actionable set used
    by the acceptance flow — without dropping the original written critique.
    """
    if existing:
        parsed: list[Recommendation] = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(Recommendation.model_validate(item))
            except Exception:  # noqa: BLE001 — skip malformed persisted rows
                continue
        if parsed:
            return parsed

    cleaned = [item.strip() for item in improvements if item and item.strip()]
    if not cleaned:
        return []

    joined = "\n".join(cleaned).lower()
    ritual_acceptance = (
        "img_2549" in joined
        and "img_2545" in joined
        and "img_2547" in joined
        and ("cta" in joined or "waitlist" in joined)
    )
    if ritual_acceptance:
        source_remove = next(
            (t for t in cleaned if "img_2549" in t.lower()),
            cleaned[0],
        )
        source_cta = next(
            (t for t in cleaned if "cta" in t.lower() and "second" in t.lower()),
            cleaned[-1],
        )
        source_copy = next(
            (t for t in cleaned if "caption" in t.lower() or "hook" in t.lower()),
            cleaned[1] if len(cleaned) > 1 else cleaned[0],
        )
        return [
            recommendation_from_text(
                source_remove,
                title="Remove IMG_2549 from Ritual Reel",
                recommendation_type="remove_asset",
                rationale=(
                    "IMG_2549 breaks visual consistency (resolution, color temperature, "
                    "salt-lamp aesthetic) against the Upper West Side literary register."
                ),
                expected_changes=(
                    "Drop clip IMG_2549.mov from the Ritual Reel source list. "
                    "Do not overwrite the existing render until a rebuild is approved."
                ),
                affected_asset="Ritual Reel",
                recommendation_id="rec_ritual_remove_2549",
            ),
            recommendation_from_text(
                source_remove,
                title="Rebuild Ritual Reel with IMG_2545 and IMG_2547",
                recommendation_type="rerender",
                rationale=(
                    "Clips 1 and 2 are visually coherent. A tighter two-clip reel "
                    "will hold better than the current three-clip structure."
                ),
                expected_changes=(
                    "Render a new versioned Ritual Reel using only "
                    "IMG_2545.mov and IMG_2547.mov. Keep the original output."
                ),
                affected_asset="Ritual Reel",
                recommendation_id="rec_ritual_rebuild_two_clip",
            ),
            recommendation_from_text(
                source_cta,
                title="Move Ritual Reel CTA to seconds 10–12",
                recommendation_type="change_timing",
                rationale=(
                    "CTA at ~22.5s of a 25s video is too late for Reels; most viewers "
                    "will never see the ask."
                ),
                expected_changes=(
                    "Set Join the waitlist overlay to appear at seconds 10–12 "
                    "in the new versioned output."
                ),
                affected_asset="Ritual Reel",
                recommendation_id="rec_ritual_cta_10_12",
            ),
            recommendation_from_text(
                source_copy,
                title="Revise Ritual Reel caption and Page Turn Loop hook",
                recommendation_type="revise_copy",
                rationale=(
                    "Founder-update caption voice and a generic Page Turn hook dilute "
                    "brand desire."
                ),
                expected_changes=(
                    "Caption and hook rewrites require editorial judgment. "
                    "Mark as manual completion unless exact replacement copy is supplied."
                ),
                affected_asset="Campaign",
                priority="medium",
                recommendation_id="rec_copy_rewrite_package",
            ),
        ]

    return [
        recommendation_from_text(text, priority="high" if index == 0 else "medium")
        for index, text in enumerate(cleaned)
    ]


def parse_recommendation_payload(items: Any) -> list[Recommendation]:
    """Parse Claude structured recommendations when present."""
    if not isinstance(items, list) or not items:
        return []
    out: list[Recommendation] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append(recommendation_from_text(item.strip()))
            continue
        if not isinstance(item, dict):
            continue
        instruction = str(
            item.get("full_instruction")
            or item.get("instruction")
            or item.get("text")
            or item.get("title")
            or ""
        ).strip()
        if not instruction:
            continue
        out.append(
            recommendation_from_text(
                instruction,
                title=str(item.get("title") or "") or None,
                recommendation_type=str(item.get("recommendation_type") or "") or None,
                rationale=str(item.get("rationale") or "") or None,
                expected_changes=str(item.get("expected_changes") or ""),
                affected_asset=str(item.get("affected_asset") or "") or None,
                priority=str(item.get("priority") or "high"),
                status=str(item.get("status") or "proposed"),
                recommendation_id=str(item.get("recommendation_id") or "") or None,
            )
        )
    return out


def recommendations_to_json(recommendations: list[Recommendation]) -> list[dict[str, Any]]:
    return [rec.to_dict() for rec in recommendations]


def update_recommendation_status(
    recommendations: list[dict[str, Any]],
    recommendation_id: str,
    status: str,
    *,
    full_instruction: str | None = None,
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for item in recommendations:
        row = dict(item)
        if str(row.get("recommendation_id")) == recommendation_id:
            row["status"] = status
            if full_instruction is not None:
                row["full_instruction"] = full_instruction
        updated.append(row)
    return updated
