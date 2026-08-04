"""Studio validation — file, logo, adjustment, and product-safety checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageStat

from studio import SUPPORTED_STATIC, SUPPORTED_VIDEO
from studio.brand_assets import (
    analyze_mark_pixels,
    auto_logo_safe_margin_px,
    get_asset,
    resolve_asset_path,
)
from studio.image_pipeline import SIZE_MODE_PERCENT, load_source_image, logo_box, rasterize_logo
from studio.luts import get_lut, parse_cube, resolve_lut_path
from studio.models import FinishConfiguration, ValidationItem
from studio.video_pipeline import ffmpeg_available, probe_video


def _item(code: str, outcome: str, message: str, details: str = "") -> ValidationItem:
    return ValidationItem(code=code, outcome=outcome, message=message, details=details)


def summarize(items: list[ValidationItem]) -> dict[str, Any]:
    if any(i.outcome == "fail" for i in items):
        outcome = "fail"
    elif any(i.outcome == "warning" for i in items):
        outcome = "warning"
    else:
        outcome = "pass"
    return {
        "outcome": outcome,
        "items": [i.to_dict() for i in items],
        "product_guardrails_verification": "Not Automatically Verified",
    }


def validate_source(path: Path) -> list[ValidationItem]:
    items: list[ValidationItem] = []
    path = Path(path)
    if not path.is_file():
        return [_item("source_exists", "fail", "Source file does not exist.")]
    if path.stat().st_size <= 0:
        return [_item("source_size", "fail", "Source file is empty.")]
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_STATIC:
        try:
            img = load_source_image(path)
            items.append(
                _item(
                    "source_decode",
                    "pass",
                    f"Static source decoded ({img.width}×{img.height}).",
                )
            )
        except Exception as exc:  # noqa: BLE001
            items.append(_item("source_decode", "fail", "Source image could not be read.", str(exc)))
    elif suffix in SUPPORTED_VIDEO:
        if not ffmpeg_available():
            items.append(
                _item(
                    "ffmpeg",
                    "fail",
                    "FFmpeg is required for video but is not available.",
                )
            )
        else:
            try:
                meta = probe_video(path)
                items.append(
                    _item(
                        "source_decode",
                        "pass",
                        f"Video source readable ({meta['width']}×{meta['height']}, "
                        f"{meta['duration']:.2f}s).",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                items.append(
                    _item("source_decode", "fail", "Source video could not be read.", str(exc))
                )
    else:
        items.append(
            _item(
                "source_type",
                "fail",
                "Unavailable — This file type is not currently supported in Studio.",
                f"Extension: {suffix}",
            )
        )
    return items


def validate_config(
    config: FinishConfiguration,
    *,
    source: Path,
    brand_id: str,
    media_type: str,
    canvas_size: tuple[int, int] | None = None,
    duration: float | None = None,
) -> list[ValidationItem]:
    items: list[ValidationItem] = []
    geo = config.geometry
    if geo.crop_right <= geo.crop_left or geo.crop_bottom <= geo.crop_top:
        items.append(_item("crop", "fail", "Crop region is invalid (zero or negative area)."))
    else:
        items.append(_item("crop", "pass", "Crop region is valid."))

    if abs(geo.straighten_degrees) > 15:
        items.append(_item("straighten", "fail", "Straighten must stay within ±15 degrees."))

    # Extreme adjustments — technical thresholds, not semantic detection
    light = config.lighting
    color = config.color
    tex = config.texture
    if abs(light.exposure) > 2.5 or abs(light.brightness) > 80:
        items.append(
            _item(
                "clipping_risk",
                "warning",
                "Exposure/brightness is extreme enough to risk clipped channels "
                "(technical threshold — not semantic analysis).",
            )
        )
    if abs(color.temperature) > 60 or abs(color.saturation) > 50:
        items.append(
            _item(
                "color_cast_risk",
                "warning",
                "Color adjustments are strong enough to risk unnatural casts or muddy neutrals.",
            )
        )
    if tex.grain_amount > 40:
        items.append(_item("grain", "warning", "Grain amount exceeds the restrained threshold."))
    if tex.grain_amount > 80:
        items.append(_item("grain", "fail", "Grain amount is excessively high."))
    if tex.sharpening > 60:
        items.append(
            _item("sharpen", "warning", "Sharpening is high enough to risk halos.")
        )
    if tex.sharpening > 90:
        items.append(_item("sharpen", "fail", "Sharpening exceeds the safe threshold."))

    # Clean Product recipe guardrail — conservative color threshold
    if config.recipe_id == "obj_clean_product":
        strong = (
            abs(color.temperature) > 12
            or abs(color.tint) > 10
            or abs(color.saturation) > 15
            or abs(color.red_balance) > 8
            or abs(color.green_balance) > 8
            or abs(color.blue_balance) > 8
            or color.fade > 10
        )
        if strong:
            items.append(
                _item(
                    "product_color_risk",
                    "warning",
                    "OBJ Clean Product: color changes exceed a conservative threshold that may "
                    "risk inaccurate jade or cream rendering. Not a calibrated perceptual match.",
                )
            )

    # LUT
    if config.lut.lut_id:
        record = get_lut(config.lut.lut_id, brand_id)
        if record is None:
            items.append(_item("lut", "fail", "Selected LUT was not found."))
        elif record.status != "Ready":
            items.append(_item("lut", "fail", f"LUT is not Ready ({record.status})."))
        else:
            try:
                parse_cube(resolve_lut_path(record))
                items.append(_item("lut", "pass", "LUT parses successfully."))
            except ValueError as exc:
                items.append(_item("lut", "fail", "LUT file is invalid.", str(exc)))

    # Logo
    items.extend(
        validate_logo(
            config,
            brand_id=brand_id,
            canvas_size=canvas_size,
            duration=duration,
            media_type=media_type,
            source=source,
        )
    )
    return items


def validate_logo(
    config: FinishConfiguration,
    *,
    brand_id: str,
    canvas_size: tuple[int, int] | None,
    duration: float | None,
    media_type: str,
    source: Path,
) -> list[ValidationItem]:
    items: list[ValidationItem] = []
    logo = config.logo
    if logo.role in {"", "none"} and not logo.asset_id:
        items.append(_item("logo", "pass", "No logo applied."))
        return items

    asset = get_asset(logo.asset_id, brand_id) if logo.asset_id else None
    if asset is None and logo.role not in {"", "none"}:
        from studio.brand_assets import default_asset_for_role

        asset = default_asset_for_role(logo.role, brand_id)
    if asset is None:
        items.append(_item("logo_asset", "fail", "Logo asset could not be resolved."))
        return items

    items.extend(brand_guardian_logo_asset_checks(asset))

    try:
        mark = rasterize_logo(resolve_asset_path(asset))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("logo_raster", "fail", "Logo could not be prepared for placement.", str(exc)))
        return items

    if canvas_size is None:
        if source.suffix.lower() in SUPPORTED_STATIC:
            img = load_source_image(source)
            canvas_size = img.size
        else:
            items.append(
                _item(
                    "logo_canvas",
                    "warning",
                    "Canvas size unavailable for full logo geometry checks.",
                )
            )
            return items

    cw, ch = canvas_size
    percent = SIZE_MODE_PERCENT.get(logo.size_mode, logo.size_percent)
    if logo.size_mode == "custom":
        percent = logo.size_percent
    lw = max(1, int(cw * (percent / 100.0)))
    lh = max(1, int(lw * (mark.height / max(1, mark.width))))

    min_readable = max(int(asset.minimum_display_width or 0), 72)
    if lw > cw or lh > ch:
        items.append(_item("logo_size", "fail", "Logo is larger than the canvas."))
    elif lw < min_readable:
        items.append(
            _item(
                "brand_guardian_unreadable_logo",
                "fail",
                f"Logo width {lw}px is below the minimum readable size ({min_readable}px).",
            )
        )
    else:
        items.append(_item("logo_size", "pass", "Logo size is within canvas bounds."))

    if logo.safe_margin_mode == "percent":
        margin = cw * (logo.safe_margin_value / 100.0)
    elif logo.safe_margin_mode == "pixels":
        margin = logo.safe_margin_value
    else:
        margin = float(asset.default_safe_margin)

    min_margin = auto_logo_safe_margin_px(cw)
    if margin + 0.5 < min_margin:
        items.append(
            _item(
                "brand_guardian_logo_edge",
                "fail",
                f"Logo safe margin ({margin:.0f}px) is too close to the edge; "
                f"need at least {min_margin:.0f}px.",
            )
        )

    x, y = logo_box((cw, ch), (lw, lh), logo, safe_margin_px=margin)
    if x < -1 or y < -1 or x + lw > cw + 1 or y + lh > ch + 1:
        items.append(_item("logo_bounds", "fail", "Logo extends outside the canvas."))
    elif x < margin - 1 or y < margin - 1 or x + lw > cw - margin + 1 or y + lh > ch - margin + 1:
        items.append(
            _item(
                "logo_margin",
                "fail",
                "Logo does not respect the configured safe margin.",
            )
        )
    elif x < min_margin - 1 or y < min_margin - 1 or x + lw > cw - min_margin + 1 or y + lh > ch - min_margin + 1:
        items.append(
            _item(
                "brand_guardian_logo_edge",
                "fail",
                "Logo placement sits too close to the frame edge.",
            )
        )
    else:
        items.append(_item("logo_margin", "pass", "Logo respects safe margin."))

    # Contrast against placement region — technical luminance check only
    if source.suffix.lower() in SUPPORTED_STATIC:
        try:
            img = load_source_image(source).convert("RGB")
            region = img.crop(
                (
                    max(0, x),
                    max(0, y),
                    min(cw, x + lw),
                    min(ch, y + lh),
                )
            )
            if region.width > 0 and region.height > 0:
                stat = ImageStat.Stat(region.convert("L"))
                bg = stat.mean[0] / 255.0
                logo_resized = mark.resize((max(1, region.width), max(1, region.height)))
                rgb = np.asarray(logo_resized.convert("RGBA")).astype(np.float32)
                alpha = rgb[..., 3] / 255.0
                if alpha.mean() > 0.05:
                    lum = (
                        0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
                    ) / 255.0
                    logo_lum = float((lum * alpha).sum() / max(alpha.sum(), 1e-6))
                    if abs(logo_lum - bg) < 0.18:
                        items.append(
                            _item(
                                "logo_contrast",
                                "warning",
                                "Logo placement region may have low contrast "
                                "(luminance check only — not object detection).",
                            )
                        )
                    else:
                        items.append(_item("logo_contrast", "pass", "Placement contrast looks sufficient."))
        except Exception:  # noqa: BLE001
            items.append(
                _item("logo_contrast", "warning", "Could not evaluate placement contrast.")
            )

    items.append(
        _item(
            "logo_semantics",
            "pass",
            "Brand Guardian logo checks cover readability, edge spacing, "
            "badge-like fills, and transparency — not semantic object detection.",
        )
    )

    if media_type == "video" and duration is not None:
        if logo.timing_mode == "custom":
            start = float(logo.start_seconds or 0)
            end = float(logo.end_seconds if logo.end_seconds is not None else duration)
            if start < 0 or end > duration + 0.05 or end <= start:
                items.append(
                    _item(
                        "logo_timing",
                        "fail",
                        "Logo timing is outside the video duration or inverted.",
                    )
                )
            else:
                items.append(_item("logo_timing", "pass", "Logo timing is within duration."))
        else:
            items.append(_item("logo_timing", "pass", f"Logo timing mode: {logo.timing_mode}."))

    return items


def brand_guardian_logo_asset_checks(asset) -> list[ValidationItem]:
    """Brand Guardian: block badge-like / opaque marks that read as UI chrome."""
    from studio.brand_assets import resolve_asset_path as _resolve

    items: list[ValidationItem] = []
    path = _resolve(asset)
    analysis = analyze_mark_pixels(path)

    if not asset.has_transparency and path.suffix.lower() not in {".svg"}:
        items.append(
            _item(
                "brand_guardian_logo_no_transparency",
                "fail",
                "Logo asset lacks transparency; prefer a transparent PNG/SVG wordmark.",
            )
        )
    elif analysis.get("looks_like_solid_rectangle"):
        items.append(
            _item(
                "brand_guardian_logo_badge",
                "fail",
                "Logo appears as a colored rectangular badge rather than a brand mark.",
                analysis.get("reason") or "",
            )
        )
    elif not analysis.get("suitable_transparent_mark"):
        items.append(
            _item(
                "brand_guardian_logo_no_transparency",
                "fail",
                analysis.get("reason") or "Logo asset is not a suitable transparent mark.",
            )
        )
    else:
        items.append(
            _item(
                "brand_guardian_logo_asset",
                "pass",
                "Logo asset is a suitable transparent mark.",
            )
        )
    return items


def validate_output_file(path: Path, *, media_type: str, expected_ext: str | None = None) -> list[ValidationItem]:
    items: list[ValidationItem] = []
    path = Path(path)
    if not path.is_file():
        return [_item("output_exists", "fail", "Output file does not exist.")]
    if path.stat().st_size <= 0:
        return [_item("output_size", "fail", "Output file is empty.")]
    items.append(_item("output_size", "pass", f"Output size {path.stat().st_size} bytes."))
    if expected_ext and path.suffix.lower() != expected_ext.lower():
        items.append(
            _item(
                "output_ext",
                "fail",
                f"Output extension {path.suffix} does not match {expected_ext}.",
            )
        )
    if media_type == "static":
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                if img.width < 1 or img.height < 1:
                    items.append(_item("output_dims", "fail", "Output dimensions are invalid."))
                else:
                    items.append(
                        _item("output_dims", "pass", f"Output {img.width}×{img.height}.")
                    )
        except Exception as exc:  # noqa: BLE001
            items.append(_item("output_decode", "fail", "Output image could not be decoded.", str(exc)))
    else:
        try:
            meta = probe_video(path)
            items.append(
                _item(
                    "output_decode",
                    "pass",
                    f"Output video {meta['width']}×{meta['height']}, {meta['duration']:.2f}s.",
                )
            )
        except Exception as exc:  # noqa: BLE001
            items.append(_item("output_decode", "fail", "Output video could not be decoded.", str(exc)))
    return items


def warnings_need_ack(items: list[ValidationItem], acknowledged: list[str]) -> list[ValidationItem]:
    return [i for i in items if i.outcome == "warning" and i.code not in acknowledged]
