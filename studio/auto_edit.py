"""Opinionated automatic edit engine — one best finish from Brand Guide + Production Rules."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.brand import BRAND_BRAIN_FILES, load_brand_brain
from src.common import DEFAULT_BRAND_ID, PRODUCTION_DIR, ROOT
from src.persistence import load_json
from studio.apply_recipe import apply_recipe_to_config
from studio.brand_assets import default_asset_for_role, list_assets
from studio.edit_decision import (
    AppliedAction,
    CleanupRecommendation,
    DecisionField,
    EditDecision,
    ExecutionReport,
    NotAppliedAction,
)
from studio.learning import list_creative_findings, list_performance_findings
from studio.models import (
    PLATFORM_EXPORT_PRESETS,
    ExportConfiguration,
    FinishConfiguration,
    LogoConfiguration,
    VideoAdjustments,
)
from studio.recipes import ColorRecipe, ensure_default_recipes, get_recipe, list_recipes


# Potential selective-cleanup categories — never claimed applied without a provider.
CLEANUP_CATEGORIES = (
    "flyaway hair",
    "chipped nail polish",
    "temporary skin blemishes",
    "clothing lint",
    "clothing wrinkles",
    "fingerprints",
    "product dust",
    "loose fibers",
    "small distracting background objects",
    "minor reflections",
    "uneven localized lighting",
)

# Recipe scoring cues derived from Brand Guide + piece/platform context.
_RECIPE_HINTS: dict[str, tuple[str, ...]] = {
    "obj_editorial_lifestyle": ("editorial", "lifestyle", "reel", "instagram", "ritual"),
    "obj_rainy_reading": ("rain", "reading", "cozy", "interior", "window"),
    "obj_morning_window": ("morning", "window", "light", "daylight"),
    "obj_product_flatlay": ("product", "flatlay", "still", "detail"),
    "obj_pinterest_editorial": ("pinterest", "pin", "editorial", "2:3", "4:5"),
    "obj_email_hero": ("email", "hero", "newsletter"),
    "obj_clean_product": ("clean", "product", "catalog", "white"),
    "obj_autumn_reading": ("autumn", "fall", "reading", "seasonal"),
    "obj_winter_ritual": ("winter", "ritual", "candle", "evening"),
    "obj_vintage_film": ("vintage", "film", "nostalgic", "grain"),
}


def ai_cleanup_provider_configured() -> bool:
    """BettyOS has no generative cleanup provider in this sprint."""
    return False


def load_production_rules_raw() -> dict[str, Any]:
    """Load Production Rules JSON files used for technical execution."""
    names = (
        "exports.json",
        "layout.json",
        "typography.json",
        "colors.json",
        "animation.json",
        "global_defaults.json",
        "safe_zones.json",
    )
    rules: dict[str, Any] = {}
    for name in names:
        path = PRODUCTION_DIR / name
        data = load_json(path, default=None)
        if isinstance(data, dict):
            rules[name.replace(".json", "")] = data
    return rules


def brand_guide_sections(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, str]:
    brand_dir = ROOT / "brands" / brand_id
    sections: dict[str, str] = {}
    for name in BRAND_BRAIN_FILES:
        path = brand_dir / name
        if path.is_file():
            sections[name.replace(".md", "")] = path.read_text(encoding="utf-8")
    return sections


def _infer_content_type(
    *,
    template_id: str,
    platform: str,
    piece_format: str,
    piece_objective: str,
    media_type: str,
) -> str:
    blob = " ".join(
        [template_id, platform, piece_format, piece_objective, media_type]
    ).lower()
    if "email" in blob:
        return "email_hero"
    if "pinterest" in blob or "pin" in blob:
        return "editorial_pin"
    if "product" in blob or "flatlay" in blob:
        return "product"
    if "reel" in blob or "tiktok" in blob or "story" in blob:
        return "lifestyle_reel"
    if media_type == "video":
        return "lifestyle_reel"
    return "editorial_static"


def _platform_export_key(platform: str, content_type: str, media_type: str) -> str:
    blob = f"{platform} {content_type}".lower()
    if "email" in blob:
        return "email_hero"
    if "pinterest" in blob or "pin" in blob:
        return "pinterest_pin"
    if "story" in blob:
        return "story"
    if "reel" in blob or "tiktok" in blob:
        return "instagram_reel"
    if "feed" in blob or "instagram" in blob:
        return "instagram_feed" if media_type == "static" else "instagram_reel"
    return "original"


def _score_recipe(
    recipe: ColorRecipe,
    *,
    media_type: str,
    platform: str,
    content_type: str,
    context_blob: str,
    brand_text: str,
) -> float:
    score = 0.0
    if media_type in (recipe.suitable_media_types or []) or not recipe.suitable_media_types:
        score += 2.0
    plat = platform.lower()
    for tag in recipe.suitable_platforms or []:
        if tag.lower() in plat or plat in tag.lower():
            score += 2.0
    for tag in recipe.suitable_content_types or []:
        if tag.lower() in content_type or tag.lower() in context_blob:
            score += 1.5
    hints = _RECIPE_HINTS.get(recipe.recipe_id, ())
    haystack = f"{context_blob} {brand_text[:2000]}".lower()
    for hint in hints:
        if hint in haystack:
            score += 1.0
    # Prefer editorial lifestyle as restrained default for OBJ
    if recipe.recipe_id == "obj_editorial_lifestyle":
        score += 0.5
    # Brand Guide rejects heavy color grading / novelty filters
    if recipe.recipe_id == "obj_vintage_film" and "vintage" not in context_blob:
        score -= 2.0
    if "product" in content_type and "product" in recipe.recipe_id:
        score += 3.0
    if "email" in content_type and "email" in recipe.recipe_id:
        score += 3.0
    if "pin" in content_type and "pinterest" in recipe.recipe_id:
        score += 3.0
    if "reel" in content_type and "lifestyle" in recipe.recipe_id:
        score += 2.0
    return score


def select_best_recipe(
    *,
    brand_id: str,
    media_type: str,
    platform: str,
    content_type: str,
    campaign_goal: str,
    piece_objective: str,
    template_id: str,
    brand_text: str,
) -> tuple[ColorRecipe, str]:
    ensure_default_recipes(brand_id)
    recipes = list_recipes(brand_id)
    if not recipes:
        raise RuntimeError("No Color Recipes available for this brand.")
    context_blob = " ".join(
        [platform, content_type, campaign_goal, piece_objective, template_id]
    ).lower()
    ranked = sorted(
        recipes,
        key=lambda r: _score_recipe(
            r,
            media_type=media_type,
            platform=platform,
            content_type=content_type,
            context_blob=context_blob,
            brand_text=brand_text,
        ),
        reverse=True,
    )
    best = ranked[0]
    reason = (
        f"Selected {best.display_name} as the single best match for "
        f"{content_type} on {platform or 'this platform'}."
    )
    return best, reason


def decide_logo(
    *,
    brand_id: str,
    platform: str,
    content_type: str,
    campaign_goal: str,
    piece_objective: str,
    overlay_mentions_brand: bool,
    findings: list[Any],
) -> tuple[str, str, str, LogoConfiguration]:
    """Return (choice, reason, source, logo_config). choice: required|optional|omit."""
    blob = f"{platform} {content_type} {campaign_goal} {piece_objective}".lower()

    # Preference findings can inform but do not override explicit product/email needs
    prefer_omit = any(
        "logo" in (f.finding or "").lower() and "avoid" in (f.finding or "").lower()
        for f in findings
    )

    if "email" in blob or "product" in content_type:
        choice = "required"
        reason = "Product and email surfaces need a clear brand mark for recognition."
        source = "Brand Guide, platform requirement"
    elif overlay_mentions_brand or "lifestyle_reel" in content_type:
        choice = "omit"
        reason = (
            "Lifestyle reel already carries brand presence through atmosphere and copy; "
            "a persistent logo would compete with visual hierarchy."
        )
        source = "Brand Guide, prior approval feedback" if prefer_omit else "Brand Guide"
    elif "pinterest" in blob or "pin" in content_type:
        choice = "optional"
        reason = "Editorial pins can carry a subtle mark; omit when composition is dense."
        source = "Brand Guide"
        # Default to subtle logo for pins unless findings say omit
        if prefer_omit:
            choice = "omit"
            reason = "Prior approvals favor omitting logos on lifestyle/editorial social."
            source = "prior approval feedback"
    else:
        choice = "omit"
        reason = "Default: omit logo unless platform or product context requires it."
        source = "Brand Guide"

    if prefer_omit and choice != "required":
        choice = "omit"
        reason = (
            "Creative-preference findings and Brand Guide both favor omitting "
            "persistent logo overlays for this content type."
        )
        source = "prior approval feedback, Brand Guide"

    logo = LogoConfiguration(role="none")
    if choice in {"required", "optional"} and choice == "required":
        asset = default_asset_for_role("primary", brand_id) or (
            list_assets(brand_id)[0] if list_assets(brand_id) else None
        )
        if asset:
            logo = LogoConfiguration(
                role=asset.role,
                asset_id=asset.asset_id,
                placement="bottom_right",
                size_mode="subtle",
                opacity=0.75,
                timing_mode="closing" if "reel" in content_type else "full",
            )
        else:
            # No asset — treat as omit with honest note
            choice = "omit"
            reason = "Logo was preferred but no brand logo asset is configured."
            source = "asset analysis"
    return choice, reason, source, logo


def _map_static_to_video(config: FinishConfiguration) -> VideoAdjustments:
    """Map recipe static grade into video adjustments when finishing video."""
    light = config.lighting
    color = config.color
    tex = config.texture
    return VideoAdjustments(
        brightness=max(-1.0, min(1.0, (light.brightness or 0.0) / 100.0)),
        contrast=max(0.5, min(2.0, 1.0 + (light.contrast or 0.0) / 200.0)),
        saturation=max(0.0, min(2.0, 1.0 + (color.saturation or 0.0) / 100.0)),
        gamma=float(light.gamma or 1.0),
        temperature=float(color.temperature or 0.0),
        fade=float(color.fade or 0.0),
        grain=float(tex.grain_amount or 0.0),
        sharpen=float(tex.sharpening or 0.0),
        vignette=float(tex.vignette_amount or 0.0),
    )


def _apply_production_export(
    config: FinishConfiguration,
    *,
    media_type: str,
    platform_key: str,
    rules: dict[str, Any],
) -> tuple[FinishConfiguration, str]:
    exports = rules.get("exports") or {}
    geo = config.geometry
    preset = PLATFORM_EXPORT_PRESETS.get(platform_key) or PLATFORM_EXPORT_PRESETS["original"]
    geo.platform_preset = platform_key
    if preset.get("width"):
        geo.output_width = preset["width"]
        geo.output_height = preset["height"]
        geo.aspect_preset = {
            "instagram_reel": "9:16",
            "story": "9:16",
            "instagram_feed": "4:5",
            "pinterest_pin": "2:3",
            "email_hero": "original",
        }.get(platform_key, geo.aspect_preset)
        if platform_key != "original":
            geo.crop_mode = "fill"
            geo.fit_mode = "fill"
    config.geometry = geo

    export = config.export
    if media_type == "video":
        export.format = "mp4"
        export.fps = float(exports.get("fps") or export.fps or 30)
        export.codec = str(exports.get("codec") or export.codec or "libx264")
        export.bitrate = str(exports.get("bitrate") or export.bitrate or "8M")
        compression = exports.get("compression") or {}
        export.quality_preset = str(compression.get("preset") or export.quality_preset)
        # Production Rules default audio behavior is remove; keep normalize off claim honest
        audio_behavior = (exports.get("audio") or {}).get("behavior")
        export.audio_normalize = audio_behavior != "remove"
        export.fade_in_seconds = 0.0
        export.fade_out_seconds = min(0.25, float(export.fade_out_seconds or 0.0) or 0.15)
    else:
        if export.format not in {"png", "jpg", "webp"}:
            export.format = "png"
        export.quality = max(export.quality, 90)
    config.export = export
    reason = f"Applied Production Rules export defaults and platform preset {platform_key}."
    return config, reason


def _selective_cleanup_recommendations() -> list[CleanupRecommendation]:
    if ai_cleanup_provider_configured():
        # Future: run real detection. Not available now.
        return []
    return [
        CleanupRecommendation(
            issue=issue,
            classification="ai_provider_required",
            reason="No AI image-editing provider is configured; selective cleanup was not performed.",
            detected=False,
        )
        for issue in CLEANUP_CATEGORIES
    ]


def _heuristic_review_score(config: FinishConfiguration, logo_choice: str) -> float:
    """Lightweight creative-review score — not a model grade."""
    score = 78.0
    # Restraint rewards
    if abs(config.color.saturation) <= 15:
        score += 4
    if config.texture.grain_amount <= 16:
        score += 3
    if logo_choice == "omit":
        score += 3
    if config.color.temperature > 25:
        score -= 6
    if config.texture.grain_amount > 20:
        score -= 4
    return max(40.0, min(96.0, score))


def build_edit_decision(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    campaign_id: str,
    content_piece_id: str | None,
    template_id: str,
    platform: str,
    campaign_goal: str,
    piece_objective: str,
    piece_format: str = "",
    media_type: str,
    source_file: Path,
    parent_render_version_id: str,
    parent_finish_version_id: str | None = None,
    overlay_copy: str = "",
    cta_copy: str = "",
    duration_seconds: float | None = None,
    revision_note: str | None = None,
    revision_of: str | None = None,
    base_config: FinishConfiguration | None = None,
) -> tuple[EditDecision, FinishConfiguration]:
    """Produce one structured EditDecision and the FinishConfiguration to apply it."""
    conflicts: list[str] = []
    brand_loaded = False
    brand_text = ""
    try:
        brand_text = load_brand_brain(brand_id)
        brand_loaded = True
    except Exception as exc:  # noqa: BLE001
        brand_text = str(exc)
        brand_loaded = False

    rules = load_production_rules_raw()
    rules_loaded = bool(rules)

    content_type = _infer_content_type(
        template_id=template_id,
        platform=platform,
        piece_format=piece_format,
        piece_objective=piece_objective,
        media_type=media_type,
    )
    findings = list_creative_findings(brand_id)
    perf_findings = list_performance_findings(brand_id)

    recipe, recipe_reason = select_best_recipe(
        brand_id=brand_id,
        media_type=media_type,
        platform=platform,
        content_type=content_type,
        campaign_goal=campaign_goal,
        piece_objective=piece_objective,
        template_id=template_id,
        brand_text=brand_text,
    )

    config = apply_recipe_to_config(recipe, base_config or FinishConfiguration())

    overlay_mentions_brand = bool(
        re.search(r"oh\s*betty|jaletti|obj\b", overlay_copy or "", re.I)
    )
    logo_choice, logo_reason, logo_source, logo_cfg = decide_logo(
        brand_id=brand_id,
        platform=platform,
        content_type=content_type,
        campaign_goal=campaign_goal,
        piece_objective=piece_objective,
        overlay_mentions_brand=overlay_mentions_brand,
        findings=findings,
    )
    # Recipe may want a logo; Brand Guide / findings win for lifestyle
    if logo_choice == "omit":
        if (config.logo.role not in {"", "none"}) or config.logo.asset_id:
            conflicts.append(
                "Color Recipe suggested a logo; Brand Guide / preference findings omit it."
            )
        config.logo = LogoConfiguration(role="none")
    else:
        # Merge recipe logo placement with decided asset
        merged = {**config.logo.to_dict(), **logo_cfg.to_dict()}
        # Keep recipe subtle defaults when present
        if recipe.logo_defaults:
            for key in ("placement", "size_mode", "opacity"):
                if key in recipe.logo_defaults and logo_choice != "omit":
                    merged[key] = recipe.logo_defaults[key]
        config.logo = LogoConfiguration.from_dict(merged)

    platform_key = _platform_export_key(platform, content_type, media_type)
    config, export_reason = _apply_production_export(
        config, media_type=media_type, platform_key=platform_key, rules=rules
    )

    if media_type == "video":
        config.video = _map_static_to_video(config)
        config.export.format = "mp4"

    # Apply revision note adjustments when revising
    if revision_note:
        logo_choice_ref: list[str] = []
        config = apply_revision_note_to_config(config, revision_note, logo_choice_ref)
        if logo_choice_ref:
            logo_choice = logo_choice_ref[0]
            logo_reason = f"Revision feedback: {revision_note}"
            logo_source = "prior approval feedback"
            if logo_choice == "omit":
                config.logo = LogoConfiguration(role="none")

    cleanup = _selective_cleanup_recommendations()
    unsupported_summary = [
        "Selective AI cleanup (flyaways, blemishes, lint, dust, etc.) — AI provider not configured"
    ]

    # Overlay / CTA / pacing fields: Studio finish does not rewrite rendered overlays;
    # decisions record intent for transparency.
    pacing_value = "unhurried" if media_type == "video" else "n/a"
    transitions_value = "subtle fades ≤0.25s" if media_type == "video" else "none"

    major: list[str] = []
    major.append(f"Color recipe: {recipe.display_name}")
    if logo_choice == "omit":
        major.append("Logo omitted to protect visual hierarchy")
    elif logo_choice == "required":
        major.append(f"Logo placed ({config.logo.placement})")
    else:
        major.append("Logo optional — applied subtly" if config.logo.asset_id else "Logo optional — omitted")
    if platform_key != "original":
        major.append(f"Framed for {PLATFORM_EXPORT_PRESETS[platform_key]['label']}")
    else:
        major.append(
            f"Restrained grade: grain {config.texture.grain_amount:.0f}, "
            f"warmth {config.color.temperature:.0f}"
        )
    major = major[:3]

    confidence = 0.72
    if brand_loaded and rules_loaded:
        confidence += 0.1
    if findings:
        confidence += 0.05
    if perf_findings:
        confidence += 0.03
    confidence = min(0.95, confidence)

    score = _heuristic_review_score(config, logo_choice)

    def df(value: Any, reason: str, source: str, *, applied: bool = True, unsupported: str | None = None) -> DecisionField:
        return DecisionField(
            value=value,
            reason=reason,
            source=source,
            applied=applied,
            unsupported_reason=unsupported,
        )

    decision = EditDecision(
        decision_id=f"ed_{uuid4().hex[:12]}",
        brand_id=brand_id,
        campaign_id=campaign_id,
        content_piece_id=content_piece_id,
        template_id=template_id,
        platform=platform,
        campaign_goal=campaign_goal,
        piece_objective=piece_objective,
        media_type=media_type,
        source_file=str(source_file),
        parent_render_version_id=parent_render_version_id,
        parent_finish_version_id=parent_finish_version_id,
        selected_source_assets=df(
            [source_file.name],
            "Use the current render output as the finishing source.",
            "asset analysis",
        ),
        clip_order=df(
            [source_file.name],
            "Single-source finish; clip order unchanged from the render.",
            "template assignment",
            applied=media_type == "video",
        ),
        trim_points=df(
            {"start": 0.0, "end": duration_seconds},
            "Keep the rendered duration; trim is owned by the template render.",
            "template assignment",
            applied=False,
            unsupported="Trim editing is not part of Studio finish in this sprint.",
        ),
        target_duration=df(
            duration_seconds,
            "Preserve rendered duration.",
            "template assignment",
        ),
        crop_strategy=df(
            {
                "platform_preset": config.geometry.platform_preset,
                "crop_mode": config.geometry.crop_mode,
                "aspect_preset": config.geometry.aspect_preset,
            },
            "Crop/fit to platform delivery from Production Rules and Brand Guide ratios.",
            "Production Rules, Brand Guide",
        ),
        pacing=df(
            pacing_value,
            "Brand Guide asks for unhurried pacing; finish does not retime clips.",
            "Brand Guide",
            applied=False,
            unsupported="Pacing changes require template re-render.",
        ),
        transitions=df(
            transitions_value,
            "Subtle fades only; no decorative transitions.",
            "Brand Guide, Production Rules",
            applied=media_type == "video" and (config.export.fade_out_seconds or 0) > 0,
        ),
        overlay_copy=df(
            overlay_copy or None,
            "Overlay copy remains as rendered; Studio finish does not rewrite text.",
            "template assignment",
            applied=False,
            unsupported="Overlay rewrite requires a revision re-render.",
        ),
        overlay_timing=df(
            None,
            "Overlay timing owned by the template render.",
            "template assignment",
            applied=False,
            unsupported="Overlay timing changes require a revision re-render.",
        ),
        cta_copy=df(
            cta_copy or None,
            "CTA copy remains as rendered.",
            "campaign objective",
            applied=False,
            unsupported="CTA rewrite requires a revision re-render.",
        ),
        cta_timing=df(
            None,
            "CTA timing owned by the template render.",
            "campaign objective",
            applied=False,
            unsupported="CTA timing changes require a revision re-render.",
        ),
        logo_decision=df(logo_choice, logo_reason, logo_source),
        logo_placement=df(
            {
                "placement": config.logo.placement if logo_choice != "omit" else None,
                "role": config.logo.role,
                "size_mode": config.logo.size_mode,
                "opacity": config.logo.opacity,
            },
            logo_reason,
            logo_source,
            applied=logo_choice != "omit" and bool(config.logo.asset_id or config.logo.role not in {"", "none"}),
        ),
        lighting=df(
            config.lighting.to_dict(),
            "Soft natural window light; slight underexposure over catalog flatness.",
            "Brand Guide",
        ),
        color=df(
            config.color.to_dict() if media_type == "static" else config.video.to_dict(),
            "Warm neutrals, restrained saturation; avoid heavy novelty grading.",
            "Brand Guide",
        ),
        color_recipe=df(
            {"recipe_id": recipe.recipe_id, "display_name": recipe.display_name, "version": recipe.version},
            recipe_reason,
            "Brand Guide, template assignment",
        ),
        grain=df(
            config.texture.grain_amount if media_type == "static" else config.video.grain,
            "Light grain for lived-in texture; never heavy novelty film stock.",
            "Brand Guide",
        ),
        sharpening=df(
            config.texture.sharpening if media_type == "static" else config.video.sharpen,
            "Gentle sharpening for clarity without plastic edges.",
            "Brand Guide",
        ),
        vignette=df(
            config.texture.vignette_amount if media_type == "static" else config.video.vignette,
            "Soft vignette to hold attention without cinematic pastiche.",
            "Brand Guide",
        ),
        audio=df(
            {
                "normalize": config.export.audio_normalize,
                "production_behavior": (rules.get("exports") or {}).get("audio"),
            },
            export_reason,
            "Production Rules",
            applied=media_type == "video",
        ),
        export_settings=df(
            config.export.to_dict(),
            export_reason,
            "Production Rules, platform requirement",
        ),
        selective_cleanup=cleanup,
        rationale=(
            f"One best finish for {content_type} using {recipe.display_name}, "
            f"guided by the Brand Guide and Production Rules"
            + (f", revised from feedback: {revision_note}" if revision_note else "")
            + "."
        ),
        confidence=confidence,
        unsupported_actions=unsupported_summary,
        major_decisions=major,
        creative_review_score=score,
        brand_guide_loaded=brand_loaded,
        production_rules_loaded=rules_loaded,
        guidance_conflict_resolutions=conflicts,
        revision_of=revision_of,
        revision_note=revision_note,
    )
    return decision, config


def apply_revision_note_to_config(
    config: FinishConfiguration,
    note: str,
    logo_choice_out: list[str] | None = None,
) -> FinishConfiguration:
    """Translate natural-language revision feedback into supported finish changes."""
    text = (note or "").lower()
    if not text:
        return config

    # Color too warm → cool temperature
    if "warm" in text or "too orange" in text or "too yellow" in text:
        config.color.temperature = max(-40.0, float(config.color.temperature) - 18.0)
        config.video.temperature = max(-40.0, float(config.video.temperature) - 18.0)
        config.color.red_balance = max(-20.0, float(config.color.red_balance) - 4.0)

    if "cool" in text or "too blue" in text or "cold" in text:
        config.color.temperature = min(40.0, float(config.color.temperature) + 14.0)
        config.video.temperature = min(40.0, float(config.video.temperature) + 14.0)

    if "logo" in text and any(
        w in text for w in ("distract", "remove", "omit", "too big", "smaller", "less")
    ):
        config.logo = LogoConfiguration(role="none")
        if logo_choice_out is not None:
            logo_choice_out.append("omit")

    if "grain" in text and any(w in text for w in ("too much", "heavy", "less", "reduce")):
        config.texture.grain_amount = max(0.0, float(config.texture.grain_amount) * 0.4)
        config.video.grain = max(0.0, float(config.video.grain) * 0.4)

    if "dark" in text or "underexposed" in text or "too dim" in text:
        config.lighting.exposure = min(1.0, float(config.lighting.exposure) + 0.25)
        config.lighting.brightness = min(40.0, float(config.lighting.brightness) + 10.0)
        config.video.brightness = min(0.4, float(config.video.brightness) + 0.1)

    if "bright" in text or "overexposed" in text or "too light" in text:
        config.lighting.exposure = max(-1.0, float(config.lighting.exposure) - 0.2)
        config.lighting.highlights = max(-40.0, float(config.lighting.highlights) - 10.0)
        config.video.brightness = max(-0.4, float(config.video.brightness) - 0.08)

    if "contrast" in text and any(w in text for w in ("too much", "harsh", "less")):
        config.lighting.contrast = max(-30.0, float(config.lighting.contrast) - 10.0)
        config.video.contrast = max(0.7, float(config.video.contrast) - 0.1)

    if "vignette" in text and any(w in text for w in ("too much", "heavy", "less", "remove")):
        config.texture.vignette_amount = max(0.0, float(config.texture.vignette_amount) * 0.3)
        config.video.vignette = max(0.0, float(config.video.vignette) * 0.3)

    # Pacing / text / ending feedback — unsupported in finish; left for honesty layer
    return config


def build_execution_report(
    decision: EditDecision,
    config: FinishConfiguration,
    *,
    finish_ok: bool,
) -> ExecutionReport:
    applied: list[AppliedAction] = []
    not_applied: list[NotAppliedAction] = []

    if decision.color_recipe.applied:
        recipe = decision.color_recipe.value or {}
        name = recipe.get("display_name") if isinstance(recipe, dict) else recipe
        applied.append(AppliedAction("Color recipe", str(name or "")))
    if decision.lighting.applied:
        applied.append(AppliedAction("Lighting adjustments", "exposure / contrast / shadows"))
    if decision.color.applied:
        applied.append(AppliedAction("Color adjustments", "temperature / saturation / fade"))
    if decision.grain.applied and float(decision.grain.value or 0) > 0:
        applied.append(AppliedAction("Grain", str(decision.grain.value)))
    if decision.sharpening.applied and float(decision.sharpening.value or 0) > 0:
        applied.append(AppliedAction("Sharpening", str(decision.sharpening.value)))
    if decision.vignette.applied and float(decision.vignette.value or 0) > 0:
        applied.append(AppliedAction("Vignette", str(decision.vignette.value)))
    if decision.crop_strategy.applied:
        applied.append(AppliedAction("Crop / resize", json.dumps(decision.crop_strategy.value)))
    logo_val = decision.logo_decision.value
    if logo_val == "omit":
        applied.append(AppliedAction("Logo decision", "omitted"))
    elif decision.logo_placement.applied:
        applied.append(AppliedAction("Logo placement", str(decision.logo_placement.value)))
    if decision.export_settings.applied:
        applied.append(AppliedAction("Export settings", "Production Rules / platform"))
    if decision.audio.applied:
        applied.append(AppliedAction("Audio handling", str(decision.audio.value)))

    for action in decision.unsupported_actions:
        not_applied.append(NotAppliedAction(action.split("—")[0].strip(), action))

    field_labels = {
        "trim_points": "Trim points",
        "pacing": "Pacing",
        "overlay_copy": "Overlay copy",
        "overlay_timing": "Overlay timing",
        "cta_copy": "CTA copy",
        "cta_timing": "CTA timing",
    }
    for name, field in (
        ("trim_points", decision.trim_points),
        ("pacing", decision.pacing),
        ("overlay_copy", decision.overlay_copy),
        ("overlay_timing", decision.overlay_timing),
        ("cta_copy", decision.cta_copy),
        ("cta_timing", decision.cta_timing),
    ):
        if not field.applied and field.unsupported_reason:
            not_applied.append(
                NotAppliedAction(field_labels[name], field.unsupported_reason)
            )

    # Deduplicate not_applied by label
    seen: set[str] = set()
    unique_na: list[NotAppliedAction] = []
    for item in not_applied:
        key = item.label.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_na.append(item)

    if not finish_ok:
        state = "failed_action"
        summary = "Best Edit did not complete — finished version was not created."
    elif unique_na and any("cleanup" in a.label.lower() or "ai provider" in a.reason.lower() for a in unique_na):
        # Cleanup unsupported is expected; still fully applied for deterministic work
        critical = [
            a
            for a in unique_na
            if "cleanup" not in a.label.lower()
            and "ai provider" not in a.reason.lower()
            and "re-render" not in a.reason.lower()
            and "trim" not in a.reason.lower()
            and "pacing" not in a.reason.lower()
            and "overlay" not in a.reason.lower()
            and "cta" not in a.reason.lower()
        ]
        if critical:
            state = "edit_partially_applied"
            summary = "Best Edit partially applied — some planned changes could not run."
        else:
            state = "edit_fully_applied"
            summary = (
                "Best Edit complete for all supported deterministic finishes. "
                "Selective AI cleanup was not available."
            )
    else:
        state = "edit_fully_applied"
        summary = "Best Edit complete — recommended finish applied."

    return ExecutionReport(
        state=state,
        applied=applied,
        not_applied=unique_na,
        summary=summary,
    )


def parse_revision_request(note: str) -> dict[str, Any]:
    """Structure natural-language Needs Revision feedback."""
    text = (note or "").strip()
    lower = text.lower()
    intents: list[str] = []
    if any(w in lower for w in ("warm", "orange", "yellow")):
        intents.append("reduce_warmth")
    if any(w in lower for w in ("cool", "blue", "cold")):
        intents.append("increase_warmth")
    if "logo" in lower:
        intents.append("reduce_or_remove_logo")
    if "grain" in lower:
        intents.append("reduce_grain")
    if any(w in lower for w in ("pac", "rushed", "fast", "slow")):
        intents.append("adjust_pacing_rerender")
    if any(w in lower for w in ("text", "copy", "explanatory", "caption")):
        intents.append("adjust_copy_rerender")
    if "ending" in lower:
        intents.append("adjust_ending_rerender")
    return {
        "raw_note": text,
        "intents": intents,
        "supported_in_finish": [
            i
            for i in intents
            if i
            in {
                "reduce_warmth",
                "increase_warmth",
                "reduce_or_remove_logo",
                "reduce_grain",
            }
        ],
        "requires_rerender": [
            i
            for i in intents
            if i.endswith("_rerender")
        ],
    }
