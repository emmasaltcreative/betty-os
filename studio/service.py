"""Orchestrate Studio preview and finished-version creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from studio import SUPPORTED_STATIC, SUPPORTED_VIDEO
from studio.capabilities import record_failure, record_success
from studio.image_pipeline import process_preview_proxy, process_static_image
from studio.models import FinishConfiguration
from studio.package import build_studio_package
from studio.validation import (
    summarize,
    validate_config,
    validate_output_file,
    validate_source,
    warnings_need_ack,
)
from studio.versions import create_finished_version, update_finish_status
from studio.video_pipeline import process_video, probe_video


ProgressCb = Callable[[str], None]

# Colour fields inside VideoAdjustments; grain, sharpen and vignette are
# reported as their own capabilities.
_VIDEO_COLOR_FIELDS = ("brightness", "contrast", "saturation", "gamma", "temperature", "fade")


def _touched(config_section: Any, *, only: tuple[str, ...] | None = None) -> bool:
    """True when a settings group has been moved off its defaults."""
    from dataclasses import fields

    reference = type(config_section)()
    names = only or tuple(f.name for f in fields(config_section))
    return any(
        getattr(config_section, name) != getattr(reference, name) for name in names
    )


def detect_media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_STATIC:
        return "static"
    if suffix in SUPPORTED_VIDEO:
        return "video"
    return None


def source_entry_validation(path: Path) -> dict[str, Any]:
    items = validate_source(path)
    summary = summarize(items)
    media = detect_media_type(path) if summary["outcome"] != "fail" else None
    meta: dict[str, Any] = {}
    if media == "static" and summary["outcome"] != "fail":
        from studio.image_pipeline import load_source_image

        img = load_source_image(path)
        meta = {"width": img.width, "height": img.height}
    elif media == "video" and summary["outcome"] != "fail":
        meta = probe_video(path)
    return {"validation": summary, "media_type": media, "meta": meta}


def run_preview(
    source: Path,
    config: FinishConfiguration,
    *,
    brand_id: str,
    preview_out: Path,
) -> dict[str, Any]:
    media = detect_media_type(source)
    if media == "static":
        img = process_preview_proxy(source, config, brand_id=brand_id)
        preview_out.parent.mkdir(parents=True, exist_ok=True)
        if img.mode == "RGBA":
            img.save(preview_out, format="PNG")
        else:
            img.convert("RGB").save(preview_out, format="JPEG", quality=88)
        record_success("Before-and-After Static Preview", "Proxy preview generated", brand_id)
        return {"ok": True, "preview": preview_out, "media_type": "static"}
    if media == "video":
        work = preview_out.parent / "_video_preview_work"
        work.mkdir(parents=True, exist_ok=True)
        out_vid = work / "preview.mp4"
        result = process_video(
            source,
            config,
            brand_id=brand_id,
            output_path=out_vid,
            preview_path=preview_out,
            work_dir=work,
        )
        if not result.get("ok"):
            record_failure("Before-and-After Video Preview", str(result.get("error")), brand_id)
            return result
        record_success("Before-and-After Video Preview", "Processed preview frame", brand_id)
        return {
            "ok": True,
            "preview": preview_out if preview_out.is_file() else None,
            "preview_video": out_vid,
            "media_type": "video",
        }
    return {"ok": False, "error": "Unsupported media type."}


def create_finish(
    *,
    render_folder: Path,
    campaign_id: str,
    content_piece_id: str | None,
    template_id: str,
    parent_render_version_id: str,
    parent_finish_version_id: str | None,
    source_file: Path,
    config: FinishConfiguration,
    brand_id: str,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    def report(msg: str) -> None:
        if progress:
            progress(msg)

    report("Validating source")
    source_items = validate_source(source_file)
    media = detect_media_type(source_file)
    if media is None or any(i.outcome == "fail" for i in source_items):
        return {"ok": False, "error": "Source validation failed.", "validation": summarize(source_items)}

    canvas = None
    duration = None
    if media == "static":
        from studio.image_pipeline import load_source_image

        img = load_source_image(source_file)
        canvas = img.size
    else:
        meta = probe_video(source_file)
        canvas = (meta["width"], meta["height"])
        duration = meta["duration"]

    report("Validating configuration")
    cfg_items = validate_config(
        config,
        source=source_file,
        brand_id=brand_id,
        media_type=media,
        canvas_size=canvas,
        duration=duration,
    )
    summary = summarize(source_items + cfg_items)
    if summary["outcome"] == "fail":
        return {"ok": False, "error": "Validation failed.", "validation": summary}

    pending = warnings_need_ack(source_items + cfg_items, config.acknowledged_warnings)
    if pending:
        return {
            "ok": False,
            "error": "Warnings must be acknowledged before creating a finished version.",
            "validation": summary,
            "needs_ack": [p.code for p in pending],
        }

    def process_fn(tmp_parent: Path, work_outputs: Path, work_previews: Path) -> dict[str, Any]:
        report("Rendering full-resolution output")
        if media == "static":
            ext = {"png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp"}.get(
                (config.export.format or "png").lower(), ".png"
            )
            out = work_outputs / f"finished{ext}"
            prev = work_previews / "preview.jpg"
            try:
                result = process_static_image(
                    source_file,
                    config,
                    brand_id=brand_id,
                    output_path=out,
                    preview_path=prev,
                )
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
            report("Validating output")
            out_items = validate_output_file(out, media_type="static", expected_ext=ext)
            validation = summarize(source_items + cfg_items + out_items)
            if validation["outcome"] == "fail":
                return {"ok": False, "error": "Output validation failed.", "validation": validation}
            result["validation"] = validation
            return result

        out = work_outputs / "finished.mp4"
        prev = work_previews / "preview.jpg"
        result = process_video(
            source_file,
            config,
            brand_id=brand_id,
            output_path=out,
            preview_path=prev,
            work_dir=tmp_parent,
        )
        if not result.get("ok"):
            return result
        report("Validating output")
        from studio.models import ValidationItem

        out_items = validate_output_file(out, media_type="video", expected_ext=".mp4")
        extra = [
            ValidationItem(**i) if isinstance(i, dict) else i
            for i in ((result.get("validation") or {}).get("items") or [])
        ]
        validation = summarize(source_items + cfg_items + out_items + extra)
        if validation["outcome"] == "fail":
            return {"ok": False, "error": "Output validation failed.", "validation": validation}
        result["validation"] = validation
        return result

    report("Saving finished version")
    try:
        record = create_finished_version(
            render_folder=render_folder,
            campaign_id=campaign_id,
            content_piece_id=content_piece_id,
            template_id=template_id,
            parent_render_version_id=parent_render_version_id,
            parent_finish_version_id=parent_finish_version_id,
            source_file=source_file,
            media_type=media,
            config=config,
            process_fn=process_fn,
        )
    except Exception as exc:  # noqa: BLE001
        record_failure("Finished-Version Persistence", str(exc), brand_id)
        return {"ok": False, "error": str(exc)}

    # Capability evidence. A control is only claimed to work once it has
    # actually been moved off its default and survived a real finish, so the
    # capability list never reports something this install has not done.
    record_success("Finished-Version Persistence", record.finish_version_id, brand_id)
    if media == "static":
        if _touched(config.lighting):
            record_success("Static Lighting Adjustments", record.finish_version_id, brand_id)
        if _touched(config.color):
            record_success("Static Color Adjustments", record.finish_version_id, brand_id)
        if config.texture.grain_amount > 0:
            record_success("Static Grain", record.finish_version_id, brand_id)
        if config.texture.vignette_amount > 0:
            record_success("Static Vignette", record.finish_version_id, brand_id)
        if config.texture.sharpening > 0:
            record_success("Static Sharpening", record.finish_version_id, brand_id)
        if config.logo.role not in {"", "none"} or config.logo.asset_id:
            record_success("Static Logo Placement", record.finish_version_id, brand_id)
        if config.lut.lut_id:
            record_success("Static .cube LUT", record.finish_version_id, brand_id)
        if _touched(config.geometry):
            record_success("Crop and Resize", record.finish_version_id, brand_id)
        record_success("Static Downloads", record.finish_version_id, brand_id)
    else:
        if config.logo.role not in {"", "none"} or config.logo.asset_id:
            record_success("Video Logo Placement", record.finish_version_id, brand_id)
        if _touched(config.video, only=_VIDEO_COLOR_FIELDS):
            record_success("Video Color Adjustment", record.finish_version_id, brand_id)
        if config.video.grain > 0:
            record_success("Video Grain", record.finish_version_id, brand_id)
        if config.video.vignette > 0:
            record_success("Video Vignette", record.finish_version_id, brand_id)
        if config.video.sharpen > 0:
            record_success("Video Sharpening", record.finish_version_id, brand_id)
        if config.lut.lut_id:
            record_success("Video .cube LUT", record.finish_version_id, brand_id)
        record_success("Video Downloads", record.finish_version_id, brand_id)
        if config.export.audio_normalize:
            record_success("Video Audio Normalization", record.finish_version_id, brand_id)
    if config.recipe_id:
        record_success("Color Recipes", config.recipe_id, brand_id)

    report("Complete")
    return {"ok": True, "record": record, "validation": record.validation_results}


def send_to_review(render_folder: Path, finish_version_id: str) -> dict[str, Any]:
    from studio.versions import load_finish_record, resolve_finish_output

    record = load_finish_record(render_folder, finish_version_id)
    if record is None:
        return {"ok": False, "error": "Finished version not found."}
    output = resolve_finish_output(render_folder, record)
    if output is None:
        return {"ok": False, "error": "Finished output file is missing; cannot send to Review."}
    updated = update_finish_status(
        render_folder,
        finish_version_id,
        status="ready_for_review",
        approval_status="awaiting_review",
    )
    # Link into campaign review index
    _write_review_link(render_folder, updated)
    return {"ok": True, "record": updated}


def _write_review_link(render_folder: Path, record) -> None:
    from src.persistence import atomic_write_json, load_json
    from studio.paths import render_studio_root

    index = render_studio_root(render_folder) / "review_links.json"
    data = load_json(index, default={"links": []}) or {"links": []}
    links = [x for x in data.get("links") or [] if x.get("finish_version_id") != record.finish_version_id]
    links.append(
        {
            "finish_version_id": record.finish_version_id,
            "status": record.status,
            "approval_status": record.approval_status,
            "output_files": record.output_files,
            "parent_render_version_id": record.parent_render_version_id,
            "updated_at": record.updated_at,
        }
    )
    data["links"] = links
    atomic_write_json(index, data)


def make_studio_package(render_folder: Path, record, brand_id: str) -> Path:
    folder = Path(render_folder) / "studio" / record.finish_version_id
    dest = folder / "studio_package.zip"
    build_studio_package(render_folder, record, dest=dest)
    record_success("Studio Package Download", record.finish_version_id, brand_id)
    return dest
