"""CarouselRenderer family — multi-frame still sequences."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from renderers.primitives import (
    canvas_from_assets,
    draw_text_block,
    next_output_version,
    resolve_media_path,
    validate_outputs,
    write_render_manifest,
)
from src.common import OUTPUTS_DIR, BettyOSError
from src.persistence import atomic_write_text
from src.templates.registry import get_template

CAROUSEL_READY = {
    "editorial_carousel",
    "product_detail_carousel",
    "story_sequence",
    "letter_carousel",
}


def render_carousel_template(
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
    if template_id not in CAROUSEL_READY and template.renderer_status != "ready":
        raise BettyOSError(
            f"Carousel template `{template_id}` is not ready ({template.renderer_status})."
        )

    copy_fields = copy_fields or {}
    paths = [resolve_media_path(rel) for rel in source_assets]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise BettyOSError("Carousel render requires at least one source asset on disk.")

    if campaign_dir is None:
        campaign_dir = OUTPUTS_DIR / "studio_renders"
        campaign_dir.mkdir(parents=True, exist_ok=True)
    out_dir = campaign_dir / template_id / content_piece_id
    out_dir.mkdir(parents=True, exist_ok=True)

    aspect = "9:16" if template_id == "story_sequence" else "4:5"
    # Build 3 frames — reuse assets cyclically when fewer than 3.
    frame_sources = [paths[i % len(paths)] for i in range(3)]
    version = next_output_version(out_dir, f"{template_id}_slide1", "png")
    outputs: list[Path] = []
    headlines = [
        copy_fields.get("headline") or copy_fields.get("hook_text") or "The Reading Hour",
        copy_fields.get("supporting_text") or "A quieter kind of attention.",
        copy_fields.get("cta_text") or "Join the waitlist",
    ]
    for index, source in enumerate(frame_sources, start=1):
        image = canvas_from_assets([source], aspect=aspect, mode="single")
        draw_text_block(image, lines=[headlines[index - 1]], y_ratio=0.78, font_size=46)
        path = out_dir / f"{template_id}_slide{index}_v{version}.png"
        image.save(path, format="PNG", optimize=True)
        outputs.append(path)

    caption_path = out_dir / f"caption_v{version}.md"
    atomic_write_text(
        caption_path,
        f"# {template.display_name}\n\n"
        + "\n\n".join(f"## Slide {i}\n\n{text}" for i, text in enumerate(headlines, start=1))
        + "\n",
    )
    outputs.append(caption_path)
    validate_outputs(outputs)
    write_render_manifest(
        out_dir,
        template_id=template_id,
        content_piece_id=content_piece_id,
        version=version,
        outputs=[p.name for p in outputs],
        source_assets=source_assets,
        config=config or {"aspect": aspect, "slides": 3},
        parent_version=version - 1 if version > 1 else None,
    )
    return {
        "ok": True,
        "template_id": template_id,
        "content_piece_id": content_piece_id,
        "version": version,
        "output_dir": str(out_dir),
        "outputs": [str(p) for p in outputs],
    }
