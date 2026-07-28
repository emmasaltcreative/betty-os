"""Template classifier — assign one primary template_id per content piece."""

from __future__ import annotations

import re
from typing import Any

from src.templates.models import ClassificationResult, ContentPieceRecord
from src.templates.registry import get_template, list_templates


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _asset_kinds(paths: list[str]) -> dict[str, int]:
    video = image = 0
    for path in paths:
        lower = path.lower()
        if lower.endswith((".mov", ".mp4", ".m4v")):
            video += 1
        elif lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
            image += 1
        elif "still" in lower or "frame" in lower:
            image += 1
            video += 1  # often a video path annotated as still
        else:
            # default: treat as media path
            if "assets/" in lower:
                video += 1
    return {"video": video, "image": image, "total": len(paths)}


def _platform_hint(platform: str, fmt: str) -> str:
    blob = _norm(f"{platform} {fmt}")
    if "pinterest" in blob:
        return "pinterest"
    if "email" in blob:
        return "email"
    if "story" in blob or "stories" in blob:
        return "story"
    if "carousel" in blob:
        return "carousel"
    if "reel" in blob or "9:16" in blob:
        return "reels"
    if "feed" in blob or "4:5" in blob:
        return "feed"
    return "general"


def classify_content_piece(piece: ContentPieceRecord | dict[str, Any]) -> ClassificationResult:
    """Assign exactly one primary template_id using format/platform/assets/objective."""
    if isinstance(piece, dict):
        piece = ContentPieceRecord.model_validate(piece)

    platform = _platform_hint(piece.platform, piece.format)
    kinds = _asset_kinds(piece.source_assets)
    blob = _norm(
        f"{piece.title} {piece.objective} {piece.platform} {piece.format} {piece.body_markdown[:800]}"
    )
    ready_ids = {t.template_id for t in list_templates(status="ready")}

    candidates: list[tuple[str, float, str]] = []

    # Copy-only signals
    if any(k in blob for k in ("email", "newsletter", "letter from")):
        candidates.append(("email_letter", 0.86, "Piece reads as email/letter copy."))
        candidates.append(("launch_email", 0.7, "Launch-oriented email alternative."))
    if "caption" in blob and "pinterest" in blob and kinds["total"] == 0:
        candidates.append(
            ("pinterest_caption_metadata", 0.88, "Pinterest caption/metadata requested.")
        )
    if platform == "reels" or "reel" in blob:
        if kinds["video"] >= 2 or "multi" in blob or "clip" in blob:
            candidates.append(
                (
                    "cinematic_multi_clip_reel",
                    0.9,
                    "Vertical reel with multiple motion sources.",
                )
            )
        else:
            candidates.append(
                (
                    "single_clip_atmospheric_loop",
                    0.84,
                    "Vertical reel that can run from one atmospheric clip.",
                )
            )
        candidates.append(("instagram_caption", 0.55, "Companion Instagram caption."))
    if platform == "pinterest" or "pin" in blob or "2:3" in blob:
        if "collage" in blob or kinds["total"] >= 2:
            candidates.append(
                ("pinterest_collage_pin", 0.82, "Pinterest pin with multi-asset collage cues.")
            )
        elif "text" in blob and "static" not in blob:
            candidates.append(
                ("text_led_editorial_pin", 0.8, "Text-led editorial pin.")
            )
        else:
            candidates.append(
                ("editorial_static_pin", 0.9, "Static editorial Pinterest pin.")
            )
        if "caption" in blob or "description" in blob:
            candidates.append(
                ("pinterest_caption_metadata", 0.55, "Companion pin description.")
            )
    if platform == "feed" or "static" in blob or "still" in blob:
        if "product" in blob:
            candidates.append(("product_feature_pin", 0.78, "Product-forward static."))
        else:
            candidates.append(("editorial_static_pin", 0.8, "Static editorial feed still."))
    if "carousel" in blob or "multi-frame" in blob or "slides" in blob:
        if "product" in blob:
            candidates.append(("product_detail_carousel", 0.84, "Product detail carousel."))
        elif "story" in blob:
            candidates.append(("story_sequence", 0.82, "Story sequence multi-frame."))
        else:
            candidates.append(("editorial_carousel", 0.86, "Editorial carousel."))
    if "waitlist" in blob and ("announce" in blob or "launch" in blob):
        candidates.append(("waitlist_announcement", 0.83, "Waitlist announcement creative."))
    if "reveal" in blob:
        candidates.append(("product_reveal", 0.8, "Product reveal creative."))
    if "bundle" in blob:
        candidates.append(("bundle_overview", 0.8, "Bundle overview creative."))
    if "cta" in blob and ("set" in blob or "variants" in blob):
        candidates.append(("short_form_cta_set", 0.75, "Short-form CTA set."))

    # Fallbacks by asset shape
    if not candidates:
        if kinds["video"] >= 2:
            candidates.append(
                ("cinematic_multi_clip_reel", 0.65, "Fallback: multiple video assets.")
            )
        elif kinds["video"] == 1:
            candidates.append(
                ("single_clip_atmospheric_loop", 0.62, "Fallback: single video asset.")
            )
        elif platform == "pinterest":
            candidates.append(("editorial_static_pin", 0.6, "Fallback: Pinterest static."))
        else:
            candidates.append(("instagram_caption", 0.55, "Fallback: copy-only package piece."))

    # Prefer ready templates; demote non-ready.
    scored: list[tuple[str, float, str]] = []
    for tid, conf, reason in candidates:
        template = get_template(tid)
        if template is None:
            continue
        adj = conf
        if tid not in ready_ids:
            adj *= 0.55
        scored.append((tid, adj, reason))
    scored.sort(key=lambda row: row[1], reverse=True)

    primary_id, confidence, rationale = scored[0]
    alternatives = [tid for tid, _, _ in scored[1:4] if tid != primary_id]

    missing = _missing_for(primary_id, piece)
    return ClassificationResult(
        primary_template_id=primary_id,
        confidence=round(min(confidence, 0.99), 2),
        rationale=rationale,
        alternative_template_ids=alternatives,
        missing_requirements=missing,
    )


def _missing_for(template_id: str, piece: ContentPieceRecord) -> list[str]:
    template = get_template(template_id)
    if template is None:
        return [f"Unknown template: {template_id}"]
    missing: list[str] = []
    required = set(template.required_inputs)
    if "source_video_clips" in required or "source_videos" in required:
        videos = [
            p
            for p in piece.source_assets
            if p.lower().endswith((".mov", ".mp4", ".m4v")) or "assets/" in p
        ]
        if not videos:
            missing.append("source video clips")
    if "source_image" in required or "source_images" in required:
        if not piece.source_assets:
            missing.append("source image(s)")
    if "hook_text" in required and not re.search(r"hook", piece.body_markdown, re.I):
        # soft — body may still contain hook elsewhere
        pass
    if template.renderer_status not in {"ready", "partial"}:
        missing.append(f"renderer not ready ({template.renderer_status})")
    return missing
