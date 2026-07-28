"""Production Brain loader — shared visual/render configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.common import (
    PAGE_TURN_TEMPLATE_PATH,
    PRODUCTION_DIR,
    ROOT,
    BettyOSError,
    relative_to_root,
)


class ProductionConfigError(Exception):
    """Raised when a required production configuration value is missing or invalid."""


def _require(data: dict[str, Any], key: str, path: str) -> Any:
    if key not in data:
        raise ProductionConfigError(f"Missing required production config value: {path}.{key}")
    return data[key]


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProductionConfigError(f"Missing production config file: {relative_to_root(path)}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductionConfigError(f"Invalid JSON in {relative_to_root(path)}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProductionConfigError(
            f"Production config must be a JSON object: {relative_to_root(path)}"
        )
    return data


def resolve_safe_margins(
    safe_zones: dict[str, Any],
    platforms: list[str],
    minimum_margins: dict[str, Any],
) -> dict[str, int]:
    """Use the strictest margins across requested platforms and layout minimums."""
    sides = ("top", "bottom", "left", "right")
    resolved = {side: int(minimum_margins[side]) for side in sides}
    for platform in platforms:
        if platform not in safe_zones or platform == "default_platform":
            raise ProductionConfigError(
                f"Unknown safe-zone platform '{platform}'. "
                "Use: instagram, pinterest, tiktok, youtube_shorts, threads."
            )
        zone = safe_zones[platform]
        for side in sides:
            resolved[side] = max(resolved[side], int(zone[side]))
    return resolved


def load_production_brain(template_path: Path | None = None) -> dict[str, Any]:
    """Load global Production Brain files first, then the template. Validate required fields."""
    template_path = template_path or PAGE_TURN_TEMPLATE_PATH

    global_defaults = _load_json_file(PRODUCTION_DIR / "global_defaults.json")
    typography = _load_json_file(PRODUCTION_DIR / "typography.json")
    colors = _load_json_file(PRODUCTION_DIR / "colors.json")
    layout = _load_json_file(PRODUCTION_DIR / "layout.json")
    animation = _load_json_file(PRODUCTION_DIR / "animation.json")
    exports = _load_json_file(PRODUCTION_DIR / "exports.json")
    safe_zones = _load_json_file(PRODUCTION_DIR / "safe_zones.json")
    template = _load_json_file(template_path)
    template_label = relative_to_root(template_path)

    for key in (
        "maximum_words_per_screen",
        "preferred_pacing",
        "default_clip_overlap_seconds",
        "transition_style",
        "default_fade_duration_seconds",
        "preferred_crop_strategy",
        "opaque_rectangular_backgrounds",
        "black_title_card",
        "looping",
    ):
        _require(global_defaults, key, "global_defaults")
    _require(global_defaults["looping"], "enabled_when_source_shorter", "global_defaults.looping")
    _require(
        global_defaults["looping"],
        "prefer_middle_segment_when_longer",
        "global_defaults.looping",
    )

    for key in (
        "primary_font",
        "secondary_font",
        "hook",
        "footer",
        "cta",
        "line_spacing",
        "max_line_width",
        "default_alignment",
        "font_scaling",
    ):
        _require(typography, key, "typography")
    _require(typography["primary_font"], "path", "typography.primary_font")
    _require(typography["secondary_font"], "path", "typography.secondary_font")
    _require(typography["hook"], "size", "typography.hook")
    _require(typography["footer"], "size", "typography.footer")
    _require(typography["cta"], "size", "typography.cta")
    for key in ("min_size", "max_size", "shrink_to_fit"):
        _require(typography["font_scaling"], key, "typography.font_scaling")

    for key in (
        "primary_text_color",
        "secondary_text_color",
        "text_opacity",
        "shadow",
        "overlay_opacity",
        "background_wash",
    ):
        _require(colors, key, "colors")
    _require(colors["shadow"], "enabled", "colors.shadow")
    _require(colors["background_wash"], "enabled", "colors.background_wash")

    for key in (
        "hook_region",
        "footer_region",
        "cta_region",
        "minimum_margins",
        "maximum_text_width",
        "alignment",
    ):
        _require(layout, key, "layout")
    for region in ("hook_region", "footer_region", "cta_region"):
        _require(layout[region], "x", f"layout.{region}")
        _require(layout[region], "y_ratio", f"layout.{region}")
    for key in ("top", "bottom", "left", "right"):
        _require(layout["minimum_margins"], key, "layout.minimum_margins")

    for key in (
        "opening_fade_seconds",
        "closing_fade_seconds",
        "text_fade_seconds",
        "default_transition",
        "cta_appear_from_end_seconds",
        "hook_appear_at_seconds",
        "footer_appear_at_seconds",
        "intro_behavior",
    ):
        _require(animation, key, "animation")

    for key in ("width", "height", "fps", "codec", "bitrate", "audio", "compression"):
        _require(exports, key, "exports")
    _require(exports["audio"], "behavior", "exports.audio")
    _require(exports["compression"], "preset", "exports.compression")
    _require(exports["compression"], "crf", "exports.compression")

    _require(safe_zones, "default_platform", "safe_zones")
    for platform in ("instagram", "pinterest", "tiktok", "youtube_shorts", "threads"):
        zone = _require(safe_zones, platform, "safe_zones")
        if not isinstance(zone, dict):
            raise ProductionConfigError(f"safe_zones.{platform} must be an object.")
        for key in ("top", "bottom", "left", "right"):
            _require(zone, key, f"safe_zones.{platform}")

    for key in (
        "piece_id",
        "target_duration_seconds",
        "safe_zone_platforms",
        "hook",
        "footer",
        "cta",
    ):
        _require(template, key, template_label)
    _require(template["hook"], "lines", f"{template_label}.hook")
    _require(template["footer"], "lines", f"{template_label}.footer")
    _require(template["cta"], "text", f"{template_label}.cta")
    if not isinstance(template["safe_zone_platforms"], list) or not template["safe_zone_platforms"]:
        raise ProductionConfigError(
            f"{template_label}.safe_zone_platforms must be a non-empty list."
        )

    has_single = "source_relative_path" in template
    has_multi = "sources" in template
    if not has_single and not has_multi:
        raise ProductionConfigError(
            f"{template_label} must define source_relative_path or sources."
        )
    if has_multi:
        sources = template["sources"]
        if not isinstance(sources, list) or not sources:
            raise ProductionConfigError(
                f"{template_label}.sources must be a non-empty list."
            )
        for index, entry in enumerate(sources):
            if not isinstance(entry, dict):
                raise ProductionConfigError(
                    f"{template_label}.sources[{index}] must be an object."
                )
            _require(entry, "relative_path", f"{template_label}.sources[{index}]")
    if "supporting" in template:
        _require(template["supporting"], "lines", f"{template_label}.supporting")

    if float(animation["opening_fade_seconds"]) > 0.25:
        raise ProductionConfigError(
            "animation.opening_fade_seconds must be 0.25 or less (no long black opens)."
        )
    if global_defaults.get("black_title_card") is True:
        raise ProductionConfigError("global_defaults.black_title_card must be false.")
    if global_defaults.get("opaque_rectangular_backgrounds") is True:
        raise ProductionConfigError(
            "global_defaults.opaque_rectangular_backgrounds must be false."
        )
    if animation.get("intro_behavior") != "immediate_footage":
        raise ProductionConfigError(
            "animation.intro_behavior must be 'immediate_footage'."
        )

    style_guide = PRODUCTION_DIR / "style_guide.md"
    if not style_guide.exists():
        raise ProductionConfigError("Missing production config file: production/style_guide.md")

    safe_margins = resolve_safe_margins(
        safe_zones,
        list(template["safe_zone_platforms"]),
        layout["minimum_margins"],
    )
    looping = template.get("looping") or global_defaults["looping"]
    crop_strategy = (
        template.get("crop_strategy") or global_defaults["preferred_crop_strategy"]
    )

    return {
        "global_defaults": global_defaults,
        "typography": typography,
        "colors": colors,
        "layout": layout,
        "animation": animation,
        "exports": exports,
        "safe_zones": safe_zones,
        "template": template,
        "style_guide": style_guide.relative_to(ROOT).as_posix(),
        "resolved": {
            "crop_strategy": crop_strategy,
            "looping": looping,
            "safe_margins": safe_margins,
            "safe_zone_platforms": list(template["safe_zone_platforms"]),
        },
    }


def load_production_context_for_review() -> str:
    """Read-only Production Brain snapshot for critique (does not change render config)."""
    style_path = PRODUCTION_DIR / "style_guide.md"
    if not style_path.is_file():
        raise BettyOSError(
            "Missing production/style_guide.md",
            hint="Production Brain files live under production/.",
        )

    sections = [
        style_path.read_text(encoding="utf-8").strip(),
        "",
        "Production Brain configuration (read-only):",
    ]
    for name in (
        "global_defaults",
        "typography",
        "colors",
        "layout",
        "animation",
        "exports",
    ):
        path = PRODUCTION_DIR / f"{name}.json"
        if not path.is_file():
            raise BettyOSError(
                f"Missing production config: {relative_to_root(path)}",
                hint="Restore the Production Brain JSON files under production/.",
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        sections.append(f"### {name}.json\n{json.dumps(data, indent=2)}")
    return "\n\n".join(sections)
