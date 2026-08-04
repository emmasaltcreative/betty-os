"""Studio capability status with persisted test evidence."""

from __future__ import annotations

from typing import Any

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.models import CAPABILITY_STATUSES, utc_now_iso
from studio.paths import capabilities_path
from studio.video_pipeline import ffmpeg_available, ffmpeg_supports_lut3d

STUDIO_CAPABILITIES = [
    "Automatic Best Edit",
    "Brand Asset Upload",
    "SVG Logo Preview",
    "Static Logo Placement",
    "Video Logo Placement",
    "Static Lighting Adjustments",
    "Static Color Adjustments",
    "Static Grain",
    "Static Vignette",
    "Static Sharpening",
    "Crop and Resize",
    "Color Recipes",
    "Static .cube LUT",
    "Video .cube LUT",
    "Video Color Adjustment",
    "Video Grain",
    "Video Vignette",
    "Video Sharpening",
    "Video Audio Normalization",
    "Before-and-After Static Preview",
    "Before-and-After Video Preview",
    "Finished-Version Persistence",
    "Static Downloads",
    "Video Downloads",
    "Studio Package Download",
]


def _defaults() -> dict[str, dict[str, Any]]:
    notes = {
        "Automatic Best Edit": (
            "Brand Guide + Production Rules drive one recommended finish with a structured "
            "decision and execution report.",
            "Selective AI cleanup requires a configured provider and is reported honestly when unavailable.",
        ),
        "Brand Asset Upload": ("Persistent upload under brands/*/studio/assets.", ""),
        "SVG Logo Preview": (
            "SVG stored and previewed when rsvg-convert or cairosvg is available.",
            "Without a rasterizer, upload transparent PNG for compositing.",
        ),
        "Static Logo Placement": ("Pillow alpha compositing on static images.", ""),
        "Video Logo Placement": ("FFmpeg overlay with timing enable expressions.", "Requires FFmpeg."),
        "Static Lighting Adjustments": ("Exposure/brightness/contrast/highlights/shadows/whites/blacks/gamma.", ""),
        "Static Color Adjustments": ("Temperature/tint/sat/vibrance/fade/lift/RGB balance.", ""),
        "Static Grain": ("Seeded numpy grain at final resolution.", ""),
        "Static Vignette": ("Soft radial vignette with feather/midpoint.", ""),
        "Static Sharpening": ("Pillow sharpness enhance.", ""),
        "Crop and Resize": ("Crop, rotate, straighten, aspect fit/fill/pad.", ""),
        "Color Recipes": ("Persistent brand recipes with version history.", ""),
        "Static .cube LUT": ("Parsed .cube applied with trilinear blend + intensity.", ""),
        "Video .cube LUT": ("FFmpeg lut3d when filter is present.", "Intensity blend not available in FFmpeg path."),
        "Video Color Adjustment": ("FFmpeg eq + colorbalance approximation.", ""),
        "Video Grain": ("FFmpeg noise filter.", ""),
        "Video Vignette": ("FFmpeg vignette filter.", ""),
        "Video Sharpening": ("FFmpeg unsharp.", ""),
        "Video Audio Normalization": ("dynaudnorm when audio exists.", ""),
        "Before-and-After Static Preview": ("Original vs processed proxy preview.", "Proxy may differ slightly from full-res."),
        "Before-and-After Video Preview": ("Separate original/processed previews.", "Synchronized scrub not implemented."),
        "Finished-Version Persistence": ("Immutable finish_vNNN directories with atomic move.", ""),
        "Static Downloads": ("Download finished PNG/JPG/WebP when file validates.", ""),
        "Video Downloads": ("Download finished MP4 when file validates.", ""),
        "Studio Package Download": ("ZIP of output, preview, config, validation, metadata.", ""),
    }
    out: dict[str, dict[str, Any]] = {}
    for name in STUDIO_CAPABILITIES:
        impl, limitation = notes.get(name, ("", ""))
        status = "Planned"
        # Environment-aware initial honesty
        if name.startswith("Video") and not ffmpeg_available():
            status = "Setup Required"
            limitation = (limitation + " FFmpeg/ffprobe missing.").strip()
        elif name == "Video .cube LUT" and ffmpeg_available() and not ffmpeg_supports_lut3d():
            status = "Unavailable"
            limitation = "FFmpeg build lacks lut3d filter."
        elif name == "SVG Logo Preview":
            from shutil import which

            if which("rsvg-convert"):
                status = "Partial"
            else:
                try:
                    import cairosvg  # noqa: F401

                    status = "Partial"
                except Exception:
                    status = "Partial"
                    limitation = "No SVG rasterizer detected; PNG logos required for placement."
        out[name] = {
            "name": name,
            "status": status,
            "implementation_note": impl,
            "known_limitation": limitation,
            "last_successful_test": None,
            "last_failure": None,
        }
    return out


def load_capabilities(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, dict[str, Any]]:
    path = capabilities_path(brand_id)
    data = load_json(path, default=None)
    base = _defaults()
    if not isinstance(data, dict) or not data.get("capabilities"):
        payload = {"brand_id": brand_id, "updated_at": utc_now_iso(), "capabilities": base}
        atomic_write_json(path, payload)
        return base
    stored = data["capabilities"]
    # Merge new capability keys without wiping evidence
    for name, default in base.items():
        if name not in stored:
            stored[name] = default
        else:
            # Keep evidence; refresh notes if empty
            for key in ("implementation_note", "known_limitation"):
                if not stored[name].get(key):
                    stored[name][key] = default[key]
    return stored


def save_capabilities(caps: dict[str, dict[str, Any]], brand_id: str = DEFAULT_BRAND_ID) -> None:
    atomic_write_json(
        capabilities_path(brand_id),
        {"brand_id": brand_id, "updated_at": utc_now_iso(), "capabilities": caps},
    )


def record_success(name: str, note: str = "", brand_id: str = DEFAULT_BRAND_ID) -> None:
    caps = load_capabilities(brand_id)
    row = caps.setdefault(name, _defaults().get(name, {"name": name}))
    row["status"] = "Ready"
    row["last_successful_test"] = {"at": utc_now_iso(), "note": note}
    save_capabilities(caps, brand_id)


def record_failure(name: str, note: str, brand_id: str = DEFAULT_BRAND_ID) -> None:
    caps = load_capabilities(brand_id)
    row = caps.setdefault(name, _defaults().get(name, {"name": name}))
    if row.get("status") != "Ready":
        # Don't invent Ready; may leave Partial/Setup Required
        pass
    row["last_failure"] = {"at": utc_now_iso(), "note": note}
    save_capabilities(caps, brand_id)


def mark_partial(name: str, limitation: str, brand_id: str = DEFAULT_BRAND_ID) -> None:
    caps = load_capabilities(brand_id)
    row = caps.setdefault(name, _defaults().get(name, {"name": name}))
    if row.get("status") != "Ready":
        row["status"] = "Partial"
    row["known_limitation"] = limitation
    save_capabilities(caps, brand_id)


def capability_rows(brand_id: str = DEFAULT_BRAND_ID) -> list[dict[str, Any]]:
    caps = load_capabilities(brand_id)
    rows = []
    for name in STUDIO_CAPABILITIES:
        row = caps.get(name) or _defaults()[name]
        status = row.get("status") or "Planned"
        if status not in CAPABILITY_STATUSES:
            status = "Planned"
        rows.append({**row, "status": status})
    return rows
