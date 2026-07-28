"""StaticRenderer family — pins, posts, commercial stills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from renderers.primitives import (
    canvas_from_assets,
    draw_text_block,
    next_output_version,
    resolve_media_path,
    validate_outputs,
    validate_required_inputs,
    write_render_manifest,
)
from src.common import OUTPUTS_DIR, BettyOSError
from src.persistence import atomic_write_text
from src.templates.registry import get_template

STATIC_READY = {
    "editorial_static_pin",
    "text_led_editorial_pin",
    "product_feature_pin",
    "pinterest_collage_pin",
    "waitlist_announcement",
    "product_reveal",
    "bundle_overview",
    "square_editorial_post",
    "story_frame",
    "launch_countdown",
    "testimonial_social_proof",
    "faq_creative",
}


def _aspect_for(template_id: str, template) -> str:
    ratios = template.supported_aspect_ratios or ["4:5"]
    if template_id in {"square_editorial_post"}:
        return "1:1"
    if template_id in {"story_frame"}:
        return "9:16"
    if "2:3" in ratios:
        return "2:3"
    if "4:5" in ratios:
        return "4:5"
    return ratios[0]


def render_static_template(
    *,
    template_id: str,
    content_piece_id: str,
    source_assets: list[str],
    campaign_dir: Path | None = None,
    copy_fields: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = get_template(template_id)
    if template is None:
        raise BettyOSError(f"Unknown template: {template_id}")
    if template.renderer_status == "planned":
        raise BettyOSError(f"Template `{template_id}` is planned only.")
    if template_id not in STATIC_READY and template.renderer_status != "ready":
        raise BettyOSError(
            f"Static template `{template_id}` is not ready ({template.renderer_status})."
        )

    copy_fields = copy_fields or {}
    missing = validate_required_inputs(
        template_id=template_id,
        required=["source_assets"],
        source_assets=source_assets,
        copy_fields=copy_fields,
    )
    if missing:
        raise BettyOSError("Missing required inputs: " + "; ".join(missing))

    paths = [resolve_media_path(rel) for rel in source_assets]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise BettyOSError("No usable source assets on disk.")

    if campaign_dir is None:
        campaign_dir = OUTPUTS_DIR / "studio_renders"
        campaign_dir.mkdir(parents=True, exist_ok=True)
    out_dir = campaign_dir / template_id / content_piece_id
    out_dir.mkdir(parents=True, exist_ok=True)

    aspect = _aspect_for(template_id, template)
    mode = "collage" if template_id == "pinterest_collage_pin" else "single"
    image = canvas_from_assets(paths, aspect=aspect, mode=mode)

    headline = (
        copy_fields.get("headline")
        or copy_fields.get("hook_text")
        or copy_fields.get("title")
        or "The Reading Hour"
    )
    supporting = copy_fields.get("supporting_text") or copy_fields.get("cta_text") or ""

    if template_id == "text_led_editorial_pin":
        draw_text_block(image, lines=[headline], y_ratio=0.18, font_size=64)
        if supporting:
            draw_text_block(image, lines=[supporting], y_ratio=0.78, font_size=40)
    elif template_id in {"waitlist_announcement", "product_reveal", "bundle_overview"}:
        draw_text_block(image, lines=[headline], y_ratio=0.2, font_size=58)
        cta = copy_fields.get("cta_text") or "Join the waitlist"
        draw_text_block(image, lines=[cta], y_ratio=0.8, font_size=42)
    else:
        draw_text_block(image, lines=[headline], y_ratio=0.78, font_size=48)
        if supporting:
            draw_text_block(image, lines=[supporting], y_ratio=0.88, font_size=34)

    version = next_output_version(out_dir, template_id, "png")
    output = out_dir / f"{template_id}_v{version}.png"
    image.save(output, format="PNG", optimize=True)
    caption = copy_fields.get("caption") or headline
    caption_path = out_dir / f"caption_v{version}.md"
    atomic_write_text(
        caption_path,
        f"# {template.display_name}\n\n## Caption\n\n{caption}\n",
    )
    validate_outputs([output, caption_path])
    write_render_manifest(
        out_dir,
        template_id=template_id,
        content_piece_id=content_piece_id,
        version=version,
        outputs=[output.name, caption_path.name],
        source_assets=source_assets,
        config=config or {"aspect": aspect},
        parent_version=version - 1 if version > 1 else None,
    )
    return {
        "ok": True,
        "template_id": template_id,
        "content_piece_id": content_piece_id,
        "version": version,
        "output_dir": str(out_dir),
        "outputs": [str(output), str(caption_path)],
    }
