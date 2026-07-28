"""VideoRenderer family — multi-clip reel and atmospheric loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from renderers.primitives import (
    next_output_version,
    resolve_media_path,
    validate_outputs,
    validate_required_inputs,
    write_render_manifest,
)
from src.common import OUTPUTS_DIR, BettyOSError
from src.templates.registry import get_template


VIDEO_TEMPLATES = {
    "cinematic_multi_clip_reel",
    "single_clip_atmospheric_loop",
    "product_detail_reel",
    "narrative_text_reel",
    "contrast_reel",
    "slideshow_reel",
}


def render_video_template(
    *,
    template_id: str,
    content_piece_id: str,
    source_assets: list[str],
    campaign_dir: Path | None = None,
    copy_fields: dict[str, str] | None = None,
    duration_seconds: float | None = None,
    cta_appear_at_seconds: float | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = get_template(template_id)
    if template is None:
        raise BettyOSError(f"Unknown template: {template_id}")
    if template.renderer_status not in {"ready", "partial"}:
        raise BettyOSError(
            f"Template `{template_id}` is {template.renderer_status}, not executable."
        )
    if template_id not in {"cinematic_multi_clip_reel", "single_clip_atmospheric_loop"} and template.renderer_status != "ready":
        raise BettyOSError(
            f"Video template `{template_id}` is not fully implemented yet "
            f"({template.renderer_status})."
        )

    missing = validate_required_inputs(
        template_id=template_id,
        required=template.required_inputs,
        source_assets=source_assets,
        copy_fields=copy_fields,
    )
    # Soft-required copy fields should not block video if assets exist.
    missing = [m for m in missing if "not found" in m or m.startswith("at least")]
    if not source_assets:
        missing.append("source_video_clips")
    if missing:
        raise BettyOSError(
            "Missing required inputs for video render: " + "; ".join(missing)
        )

    from main import run_create_page_turn_loop, run_create_ritual_reel

    if campaign_dir is None:
        campaign_dir = OUTPUTS_DIR / "studio_renders"
        campaign_dir.mkdir(parents=True, exist_ok=True)

    folder_name = {
        "cinematic_multi_clip_reel": "cinematic_multi_clip_reel",
        "single_clip_atmospheric_loop": "single_clip_atmospheric_loop",
    }.get(template_id, template_id)
    # Keep legacy folders for migrated campaigns when rendering those IDs into old dirs.
    out_dir = campaign_dir / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)

    if template_id == "cinematic_multi_clip_reel":
        version = next_output_version(out_dir, "cinematic_multi_clip_reel", "mp4")
        # Also accept legacy ritual folder naming for first migrate compatibility.
        source_overrides = []
        for rel in source_assets:
            path = resolve_media_path(rel)
            if not path.exists():
                raise BettyOSError(f"Source asset not found: {rel}")
            source_overrides.append(
                {
                    "relative_path": rel if not Path(rel).is_absolute() else str(path.relative_to(path.anchor)),
                    "target_duration_seconds": float(duration_seconds or 15) / max(len(source_assets), 1),
                }
            )
        # Prefer relative-to-ROOT paths expected by ritual reel.
        from src.common import ROOT

        normalized = []
        for rel in source_assets:
            path = resolve_media_path(rel)
            try:
                normalized.append(
                    {
                        "relative_path": path.resolve().relative_to(ROOT).as_posix(),
                        "target_duration_seconds": float(duration_seconds or 15)
                        / max(len(source_assets), 1),
                    }
                )
            except ValueError as exc:
                raise BettyOSError(f"Asset must live under project root: {rel}") from exc

        output_name = f"cinematic_multi_clip_reel_v{version}.mp4"
        run_create_ritual_reel(
            out_dir=out_dir,
            source_overrides=normalized,
            target_duration_seconds=float(duration_seconds or 15),
            cta_appear_at_seconds=cta_appear_at_seconds,
            caption_override=(copy_fields or {}).get("caption"),
            output_filename=output_name,
            preserve_existing=True,
            versioning={
                "version": version,
                "parent_version": version - 1 if version > 1 else None,
                "revision_request_ids": [],
                "addressed_recommendation_ids": [],
            },
        )
        video_path = out_dir / output_name
        validate_outputs([video_path])
        write_render_manifest(
            out_dir,
            template_id=template_id,
            content_piece_id=content_piece_id,
            version=version,
            outputs=[video_path.name, "caption.md"],
            source_assets=source_assets,
            config=config or {},
            parent_version=version - 1 if version > 1 else None,
        )
        return {
            "ok": True,
            "template_id": template_id,
            "content_piece_id": content_piece_id,
            "version": version,
            "output_dir": str(out_dir),
            "outputs": [str(video_path)],
        }

    if template_id == "single_clip_atmospheric_loop":
        version = next_output_version(out_dir, "single_clip_atmospheric_loop", "mp4")
        output_name = f"single_clip_atmospheric_loop_v{version}.mp4"
        # Page turn loop currently uses fixed template source; render into out_dir.
        result_dir = run_create_page_turn_loop(out_dir=out_dir)
        # Rename draft to versioned immutable output without deleting draft if present.
        draft = result_dir / "page_turn_loop_draft.mp4"
        target = result_dir / output_name
        if draft.is_file():
            if not target.exists():
                target.write_bytes(draft.read_bytes())
        validate_outputs([target if target.exists() else draft])
        final = target if target.exists() else draft
        write_render_manifest(
            out_dir,
            template_id=template_id,
            content_piece_id=content_piece_id,
            version=version,
            outputs=[final.name, "caption.md"],
            source_assets=source_assets,
            config=config or {},
            parent_version=version - 1 if version > 1 else None,
        )
        return {
            "ok": True,
            "template_id": template_id,
            "content_piece_id": content_piece_id,
            "version": version,
            "output_dir": str(out_dir),
            "outputs": [str(final)],
        }

    raise BettyOSError(
        f"Video template `{template_id}` cannot be rendered yet. "
        f"Status: {template.renderer_status}."
    )
