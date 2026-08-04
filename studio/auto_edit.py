"""Automatic brand-informed Studio finishing decisions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.brand import BRAND_BRAIN_FILES, load_brand_brain
from src.common import DEFAULT_BRAND_ID, PRODUCTION_DIR
from src.persistence import load_json
from studio.apply_recipe import apply_recipe_to_config
from studio.brand_assets import default_asset_for_role
from studio.edit_decision import (
    AppliedAction,
    CleanupRecommendation,
    DecisionField,
    EditDecision,
    ExecutionReport,
    NotAppliedAction,
)
from studio.learning import list_creative_preferences
from studio.models import FinishConfiguration, PLATFORM_EXPORT_PRESETS
from studio.recipes import ColorRecipe, ensure_default_recipes, list_recipes

_AI_CLEANUP_ENV = (
    "BETTYOS_AI_CLEANUP_PROVIDER",
    "REPLICATE_API_TOKEN",
    "OPENAI_API_KEY",
)


def load_brand_guide(brand_id: str = DEFAULT_BRAND_ID) -> tuple[str, bool, list[str]]:
    try:
        return load_brand_brain(brand_id), True, list(BRAND_BRAIN_FILES)
    except Exception:  # noqa: BLE001
        return "", False, []


def load_production_rules() -> tuple[dict[str, Any], bool, list[str]]:
    rules: dict[str, Any] = {}
    files: list[str] = []
    if not PRODUCTION_DIR.is_dir():
        return rules, False, files
    for path in sorted(PRODUCTION_DIR.glob("*.json")):
        data = load_json(path, default=None)
        if isinstance(data, dict):
            rules[path.stem] = data
            files.append(path.name)
    return rules, bool(files), files


def ai_cleanup_provider_configured() -> bool:
    return any(os.getenv(name, "").strip() for name in _AI_CLEANUP_ENV)


def select_best_recipe(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    platform: str = "",
    content_type: str = "",
    brand_text: str = "",
    media_type: str = "static",
) -> ColorRecipe:
    recipes = list_recipes(brand_id)
    if not recipes:
        recipes = ensure_default_recipes(brand_id)
    platform_norm = _normalise_platform(platform)
    content_norm = _normalise_content_type(content_type, brand_text)
    text = f"{platform_norm} {content_norm} {brand_text}".lower()

    def score(recipe: ColorRecipe) -> tuple[int, str]:
        total = 0
        rid = recipe.recipe_id.lower()
        desc = f"{recipe.display_name} {recipe.description}".lower()
        if media_type in recipe.suitable_media_types:
            total += 5
        if platform_norm and any(platform_norm.startswith(p) or p in platform_norm for p in recipe.suitable_platforms):
            total += 4
        if content_norm in recipe.suitable_content_types:
            total += 4
        if "pinterest" in text and "pinterest" in rid:
            total += 10
        if "email" in text and "email" in rid:
            total += 10
        if "product" in content_norm and ("product" in rid or "product" in desc):
            total += 8
        if "lifestyle" in content_norm and ("lifestyle" in rid or "editorial" in rid):
            total += 8
        if any(word in text for word in ("rain", "rainy")) and "rainy" in rid:
            total += 6
        if "window" in text and "window" in rid:
            total += 5
        return total, recipe.recipe_id

    return max(recipes, key=score)


def decide_logo(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    platform: str = "",
    content_type: str = "",
    overlay_copy: str = "",
    media_type: str = "static",
) -> dict[str, Any]:
    platform_norm = _normalise_platform(platform)
    content_norm = _normalise_content_type(content_type, overlay_copy)
    text = overlay_copy.lower()
    brand_named = "oh betty" in text or "betty jaletti" in text or "obj" in text
    preference_omit = any(
        f.status == "promoted"
        and "avoid persistent logo overlays" in f.statement.lower()
        and "lifestyle" in content_norm
        and ("instagram" in platform_norm or "reel" in platform_norm)
        for f in list_creative_preferences(brand_id)
    )
    if preference_omit:
        return {
            "decision": "omit",
            "placement": "none",
            "timing_mode": "none",
            "reason": "Promoted Studio preference avoids persistent logo overlays on OBJ lifestyle reels.",
        }
    if content_norm == "lifestyle" and ("instagram" in platform_norm or "reel" in platform_norm):
        return {
            "decision": "omit",
            "placement": "none",
            "timing_mode": "none",
            "reason": "Lifestyle reels should feel editorial; persistent logo overlays distract from the scene.",
        }
    if brand_named:
        return {
            "decision": "omit",
            "placement": "none",
            "timing_mode": "none",
            "reason": "Brand is already named in copy, so a logo overlay would be redundant.",
        }
    if content_norm == "product":
        return {
            "decision": "optional",
            "placement": "bottom_right",
            "timing_mode": "full" if media_type == "static" else "closing",
            "reason": "Product work can carry a subtle mark when an approved brand asset exists.",
        }
    return {
        "decision": "optional",
        "placement": "bottom_right",
        "timing_mode": "closing" if media_type == "video" else "full",
        "reason": "Defaulting to subtle brand presence only when an asset is available.",
    }


def build_edit_decision(
    *,
    source_file: Path,
    brand_id: str = DEFAULT_BRAND_ID,
    platform: str = "",
    content_type: str = "",
    campaign_goal: str = "",
    template_id: str = "",
    overlay_copy: str = "",
    cta_copy: str = "",
    media_type: str | None = None,
) -> tuple[EditDecision, FinishConfiguration]:
    source_file = Path(source_file)
    media = media_type or _media_type_for(source_file)
    brand_text, brand_loaded, brand_files = load_brand_guide(brand_id)
    rules, rules_loaded, rule_files = load_production_rules()
    content_norm = _normalise_content_type(content_type or template_id, f"{campaign_goal} {overlay_copy}")
    platform_norm = _normalise_platform(platform)
    recipe = select_best_recipe(
        brand_id=brand_id,
        platform=platform_norm,
        content_type=content_norm,
        brand_text=f"{brand_text} {campaign_goal} {template_id}",
        media_type=media,
    )
    config = apply_recipe_to_config(recipe, FinishConfiguration())
    _apply_platform_export(config, platform_norm, media, rules)
    if media == "video":
        _map_static_grade_to_video(config)
    logo = decide_logo(
        brand_id=brand_id,
        platform=platform_norm,
        content_type=content_norm,
        overlay_copy=overlay_copy,
        media_type=media,
    )
    _apply_logo_decision(config, logo, brand_id)
    cleanup = _cleanup_recommendations(media)
    unsupported = [
        NotAppliedAction(
            action=f"selective_cleanup:{item.category}",
            reason=item.reason,
            unsupported_reason=item.unsupported_reason,
        )
        for item in cleanup
        if not item.applied
    ]
    major = [
        f"Recipe: {recipe.display_name}",
        "Logo omitted for editorial restraint" if logo["decision"] == "omit" else "Subtle logo only if brand asset exists",
        f"Export: {config.geometry.platform_preset or 'original'}",
    ]
    decision = EditDecision(
        selected_source_assets=DecisionField(
            value=[str(source_file)],
            reason="Use the render opened in Studio as the only source asset.",
            source="render_version",
        ),
        clip_order=DecisionField(
            value=[source_file.name],
            reason="Single best edit uses the current render only.",
            source="render_version",
        ),
        trim_points=DecisionField(
            value=None,
            reason="No automatic trim was applied without explicit shot boundary data.",
            source="production_rules",
            applied=False,
            unsupported_reason="shot_boundary_data_unavailable",
        ),
        target_duration=DecisionField(
            value=None,
            reason="Keep source duration unless a template render already set duration.",
            source="production_rules",
        ),
        crop_strategy=DecisionField(
            value=config.geometry.platform_preset or config.geometry.aspect_preset,
            reason="Match the chosen platform preset while preserving the render subject.",
            source="production_rules",
        ),
        pacing=DecisionField(
            value=(rules.get("global_defaults") or {}).get("preferred_pacing", "unhurried"),
            reason="Production rules prefer restrained pacing.",
            source="production/global_defaults.json",
        ),
        transitions=DecisionField(
            value=(rules.get("global_defaults") or {}).get("transition_style", "cut"),
            reason="Use simple cuts/fades rather than decorative transitions.",
            source="production/global_defaults.json",
        ),
        overlay_copy=DecisionField(
            value=overlay_copy,
            reason="No new overlay copy is invented in Studio finishing.",
            source="content_piece",
        ),
        overlay_timing=DecisionField(
            value=_overlay_timing(rules),
            reason="Use production timing defaults for existing overlays.",
            source="production/animation.json",
        ),
        cta_copy=DecisionField(
            value=cta_copy,
            reason="CTA copy is preserved from the content piece.",
            source="content_piece",
        ),
        cta_timing=DecisionField(
            value=(rules.get("animation") or {}).get("cta_appear_from_end_seconds", 2.5),
            reason="Use production CTA timing if the render contains a CTA.",
            source="production/animation.json",
        ),
        logo_decision=DecisionField(
            value=logo["decision"],
            reason=logo["reason"],
            source="brand_guide+creative_preferences",
            applied=True,
        ),
        logo_placement=DecisionField(
            value=logo["placement"],
            reason=logo["reason"],
            source="production_rules",
            applied=logo["decision"] != "omit",
            unsupported_reason=None if logo["decision"] != "omit" else "intentionally_omitted",
        ),
        lighting=DecisionField(
            value=config.lighting.to_dict(),
            reason=f"Loaded from recipe {recipe.display_name}.",
            source="color_recipe",
        ),
        color=DecisionField(
            value=config.color.to_dict(),
            reason=f"Loaded from recipe {recipe.display_name}.",
            source="color_recipe",
        ),
        color_recipe=DecisionField(
            value=recipe.recipe_id,
            reason="Best-scoring recipe for platform, content type, and brand guidance.",
            source="studio_recipes",
        ),
        grain=DecisionField(
            value=config.video.grain if media == "video" else config.texture.grain_amount,
            reason="Use restrained recipe texture.",
            source="color_recipe",
        ),
        sharpening=DecisionField(
            value=config.video.sharpen if media == "video" else config.texture.sharpening,
            reason="Preserve clarity without halo-prone sharpening.",
            source="color_recipe",
        ),
        vignette=DecisionField(
            value=config.video.vignette if media == "video" else config.texture.vignette_amount,
            reason="Subtle vignette only when recipe calls for it.",
            source="color_recipe",
        ),
        audio=DecisionField(
            value=config.export.audio_normalize if media == "video" else None,
            reason="Normalize audio on video exports; static assets have no audio.",
            source="production/exports.json",
        ),
        export_settings=DecisionField(
            value=config.export.to_dict(),
            reason="Platform export preset applied.",
            source="production/exports.json",
        ),
        selective_cleanup=cleanup,
        rationale=(
            "Generate one finished recommendation by combining Brand Guide, production rules, "
            "and the best matching OBJ Studio recipe."
        ),
        confidence=0.82 if brand_loaded and rules_loaded else 0.68,
        unsupported_actions=unsupported,
        major_decisions=major,
        creative_review_score=_creative_review_score(recipe, logo, cleanup, brand_loaded, rules_loaded),
        brand_guide_loaded=brand_loaded,
        production_rules_loaded=rules_loaded,
        brand_guide_files=brand_files,
        production_rule_files=rule_files,
        recipe_id=recipe.recipe_id,
        platform=platform_norm,
        content_type=content_norm,
    )
    return decision, config


def parse_revision_request(note: str) -> dict[str, Any]:
    text = (note or "").lower()
    request: dict[str, Any] = {"raw_note": note or ""}
    if any(phrase in text for phrase in ("too warm", "less warm", "cooler", "orange")):
        request["temperature_delta"] = -8.0
    if any(phrase in text for phrase in ("too cool", "too cold", "warmer")):
        request["temperature_delta"] = request.get("temperature_delta", 0.0) + 6.0
    if "logo" in text and any(word in text for word in ("distracting", "remove", "omit", "too big")):
        request["logo_decision"] = "omit"
    if any(phrase in text for phrase in ("too dark", "brighter")):
        request["brightness_delta"] = 4.0
    if any(phrase in text for phrase in ("too bright", "darker")):
        request["brightness_delta"] = request.get("brightness_delta", 0.0) - 4.0
    return request


def apply_revision_note_to_config(
    config: FinishConfiguration,
    revision_note: str,
) -> tuple[FinishConfiguration, list[AppliedAction]]:
    updated = FinishConfiguration.from_dict(config.to_dict())
    parsed = parse_revision_request(revision_note)
    actions: list[AppliedAction] = []
    temp_delta = parsed.get("temperature_delta")
    if isinstance(temp_delta, (int, float)):
        updated.color.temperature = float(updated.color.temperature) + float(temp_delta)
        updated.video.temperature = float(updated.video.temperature) + float(temp_delta)
        actions.append(
            AppliedAction(
                action="revision:temperature",
                value=temp_delta,
                reason="Natural-language revision requested a color-temperature change.",
            )
        )
    brightness_delta = parsed.get("brightness_delta")
    if isinstance(brightness_delta, (int, float)):
        updated.lighting.brightness = float(updated.lighting.brightness) + float(brightness_delta)
        updated.video.brightness = float(updated.video.brightness) + float(brightness_delta)
        actions.append(
            AppliedAction(
                action="revision:brightness",
                value=brightness_delta,
                reason="Natural-language revision requested a brightness change.",
            )
        )
    if parsed.get("logo_decision") == "omit":
        updated.logo.role = "none"
        updated.logo.asset_id = None
        updated.logo.timing_mode = "full"
        actions.append(
            AppliedAction(
                action="revision:logo_omit",
                value="omit",
                reason="Natural-language revision said the logo was distracting or should be removed.",
            )
        )
    return updated, actions


def build_execution_report(
    decision: EditDecision,
    config: FinishConfiguration,
    *,
    extra_applied: list[AppliedAction] | None = None,
    warnings_acknowledged: list[str] | None = None,
) -> ExecutionReport:
    applied = [
        AppliedAction("recipe", decision.recipe_id, decision.color_recipe.reason, "studio_recipes"),
        AppliedAction("lighting", config.lighting.to_dict(), decision.lighting.reason, "color_recipe"),
        AppliedAction("color", config.color.to_dict(), decision.color.reason, "color_recipe"),
        AppliedAction("export_settings", config.export.to_dict(), decision.export_settings.reason, "production_rules"),
    ]
    if config.logo.role not in {"", "none"} or config.logo.asset_id:
        applied.append(AppliedAction("logo", config.logo.to_dict(), decision.logo_decision.reason, "brand_assets"))
    else:
        applied.append(AppliedAction("logo_omitted", "omit", decision.logo_decision.reason, "brand_guide"))
    applied.extend(extra_applied or [])
    not_applied = list(decision.unsupported_actions)
    if decision.trim_points.unsupported_reason:
        not_applied.append(
            NotAppliedAction(
                action="trim_points",
                reason=decision.trim_points.reason,
                source=decision.trim_points.source,
                unsupported_reason=decision.trim_points.unsupported_reason,
            )
        )
    return ExecutionReport(
        applied_actions=applied,
        not_applied_actions=not_applied,
        warnings_acknowledged=list(warnings_acknowledged or []),
        notes=["Execution report reflects actual Studio controls; unsupported AI cleanup was not faked."],
    )


def _normalise_platform(platform: str) -> str:
    text = (platform or "").strip().lower().replace(" ", "_")
    if not text:
        return "instagram_reel"
    if text in {"instagram", "ig", "reels", "reel"}:
        return "instagram_reel"
    if text == "feed":
        return "instagram_feed"
    return text


def _normalise_content_type(content_type: str, text: str = "") -> str:
    raw = f"{content_type} {text}".lower()
    if any(word in raw for word in ("product", "flatlay", "commerce", "shop")):
        return "product"
    if any(word in raw for word in ("lifestyle", "ritual", "reel", "reading", "editorial")):
        return "lifestyle"
    return "editorial"


def _media_type_for(path: Path) -> str:
    return "video" if path.suffix.lower() in {".mp4", ".mov"} else "static"


def _platform_preset(platform: str, media_type: str) -> str:
    if platform in PLATFORM_EXPORT_PRESETS:
        return platform
    if "pinterest" in platform:
        return "pinterest_pin"
    if "email" in platform:
        return "email_hero"
    if "square" in platform:
        return "instagram_square"
    if "feed" in platform:
        return "instagram_feed"
    if media_type == "video":
        return "instagram_reel"
    return "instagram_feed"


def _apply_platform_export(
    config: FinishConfiguration,
    platform: str,
    media_type: str,
    rules: dict[str, Any],
) -> None:
    preset_key = _platform_preset(platform, media_type)
    preset = PLATFORM_EXPORT_PRESETS.get(preset_key) or {}
    config.geometry.platform_preset = preset_key
    if preset.get("width") and preset.get("height"):
        config.geometry.output_width = int(preset["width"])
        config.geometry.output_height = int(preset["height"])
        config.geometry.fit_mode = "fill" if preset_key != "email_hero" else "fit"
    export_rules = rules.get("exports") or {}
    if media_type == "video":
        config.export.format = "mp4"
        config.export.fps = float(export_rules.get("fps") or 30)
        config.export.codec = str(export_rules.get("codec") or config.export.codec)
        config.export.bitrate = str(export_rules.get("bitrate") or config.export.bitrate)
        compression = export_rules.get("compression") or {}
        config.export.quality_preset = str(compression.get("preset") or config.export.quality_preset)
        config.export.audio_normalize = True
    else:
        config.export.format = "jpg" if preset_key in {"email_hero", "instagram_feed"} else "png"
        config.export.quality = 88 if config.export.format == "jpg" else 92
        config.export.strip_metadata = True


def _apply_logo_decision(config: FinishConfiguration, logo: dict[str, Any], brand_id: str) -> None:
    if logo["decision"] == "omit":
        config.logo.role = "none"
        config.logo.asset_id = None
        return
    asset = default_asset_for_role("primary", brand_id)
    if asset is None:
        config.logo.role = "none"
        config.logo.asset_id = None
        return
    config.logo.role = "primary"
    config.logo.asset_id = asset.asset_id
    config.logo.placement = str(logo.get("placement") or "bottom_right")
    config.logo.size_mode = "subtle"
    config.logo.opacity = min(float(asset.default_opacity), 0.8)
    if logo.get("timing_mode") in {"full", "opening", "closing", "custom"}:
        config.logo.timing_mode = str(logo["timing_mode"])


def _map_static_grade_to_video(config: FinishConfiguration) -> None:
    config.video.brightness = float(config.lighting.brightness)
    config.video.contrast = max(0.2, 1.0 + float(config.lighting.contrast) / 100.0)
    config.video.saturation = max(0.0, 1.0 + float(config.color.saturation) / 100.0)
    config.video.gamma = max(0.1, float(config.lighting.gamma))
    config.video.temperature = float(config.color.temperature)
    config.video.fade = float(config.color.fade)
    config.video.grain = float(config.texture.grain_amount)
    config.video.sharpen = float(config.texture.sharpening)
    config.video.vignette = float(config.texture.vignette_amount)
    # The video path uses VideoAdjustments; leave static texture at recipe values
    # for the immutable config snapshot, but processing will read video fields.


def _cleanup_recommendations(media_type: str) -> list[CleanupRecommendation]:
    provider = ai_cleanup_provider_configured()
    categories = [
        ("dust", "Remove small dust/sensor specks only if a provider can verify pixels."),
        ("background_distraction", "Remove minor background distractions only with an AI cleanup provider."),
    ]
    if media_type == "video":
        categories.append(("motion_cleanup", "Stabilized object cleanup requires a video-capable provider."))
    return [
        CleanupRecommendation(
            category=category,
            recommendation=recommendation,
            reason="Selective cleanup cannot be truthfully generated by local Studio controls.",
            applied=False,
            unsupported_reason=None if provider else "ai_provider_required",
        )
        for category, recommendation in categories
    ]


def _overlay_timing(rules: dict[str, Any]) -> dict[str, Any]:
    animation = rules.get("animation") or {}
    return {
        "hook_appear_at_seconds": animation.get("hook_appear_at_seconds", 0.25),
        "footer_appear_at_seconds": animation.get("footer_appear_at_seconds", 0.6),
        "text_fade_seconds": animation.get("text_fade_seconds", 0.4),
    }


def _creative_review_score(
    recipe: ColorRecipe,
    logo: dict[str, Any],
    cleanup: list[CleanupRecommendation],
    brand_loaded: bool,
    rules_loaded: bool,
) -> float:
    score = 0.74
    if brand_loaded:
        score += 0.08
    if rules_loaded:
        score += 0.06
    if logo.get("decision") == "omit":
        score += 0.03
    if recipe.recipe_id:
        score += 0.04
    if any(item.unsupported_reason for item in cleanup):
        score -= 0.03
    return round(max(0.0, min(score, 0.98)), 2)
