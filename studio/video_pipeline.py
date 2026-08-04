"""Video finishing via FFmpeg — real filters only, no claimed AI features."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from studio.brand_assets import (
    default_asset_for_role,
    get_asset,
    is_suitable_transparent_mark,
    resolve_asset_path,
)
from studio.image_pipeline import SIZE_MODE_PERCENT, logo_box, rasterize_logo
from studio.luts import get_lut, resolve_lut_path
from studio.models import FinishConfiguration, PLATFORM_EXPORT_PRESETS
from studio.overlay_diagnostics import OverlayEvent, record_overlay


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def ffmpeg_available() -> bool:
    return bool(ffmpeg_bin() and ffprobe_bin())


def probe_video(path: Path) -> dict[str, Any]:
    probe = ffprobe_bin()
    if not probe:
        raise RuntimeError("ffprobe is not available.")
    cmd = [
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=width,height,codec_type,avg_frame_rate,codec_name",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Could not read video metadata: {proc.stderr.strip() or 'ffprobe failed'}")
    data = json.loads(proc.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    width = height = None
    fps = None
    has_audio = False
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video":
            width = int(stream.get("width") or 0) or width
            height = int(stream.get("height") or 0) or height
            rate = stream.get("avg_frame_rate") or "0/1"
            if "/" in str(rate):
                num, den = str(rate).split("/", 1)
                try:
                    fps = float(num) / float(den) if float(den) else None
                except ValueError:
                    fps = None
        elif stream.get("codec_type") == "audio":
            has_audio = True
    if not width or not height or duration <= 0:
        raise RuntimeError("Video dimensions or duration could not be detected.")
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio": has_audio,
        "size": int((data.get("format") or {}).get("size") or 0),
    }


def ffmpeg_supports_lut3d() -> bool:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return False
    proc = subprocess.run([ffmpeg, "-filters"], capture_output=True, text=True, check=False)
    return "lut3d" in (proc.stdout or "")


def _eq_filter(cfg: FinishConfiguration) -> str | None:
    v = cfg.video
    # Map Studio video adjustments onto FFmpeg eq
    brightness = v.brightness / 100.0  # -1..1-ish from -100..100
    contrast = max(0.01, v.contrast if v.contrast > 0 else 1.0 + v.contrast / 100.0)
    # Allow contrast as absolute (default 1.0) or relative from UI
    if 0.2 <= v.contrast <= 3.0:
        contrast = v.contrast
    else:
        contrast = max(0.01, 1.0 + (v.contrast / 100.0))
    saturation = v.saturation if 0.0 <= v.saturation <= 3.0 else max(0.0, 1.0 + v.saturation / 100.0)
    gamma = max(0.1, v.gamma)
    parts = [
        f"brightness={brightness:.4f}",
        f"contrast={contrast:.4f}",
        f"saturation={saturation:.4f}",
        f"gamma={gamma:.4f}",
    ]
    return "eq=" + ":".join(parts)


def _temperature_filter(amount: float) -> str | None:
    """Honest approximation via colorbalance — not true white-balance science."""
    if abs(amount) < 0.5:
        return None
    t = amount / 200.0
    # Warm: more rs, less bs
    return f"colorbalance=rs={t:.4f}:gs=0:bs={-t:.4f}"


def build_video_filter_chain(
    cfg: FinishConfiguration,
    *,
    brand_id: str,
    meta: dict[str, Any],
    logo_png: Path | None,
) -> tuple[list[str], list[str]]:
    """Return (filter_complex parts related inputs already assumed), input_extra_args not used.

    Builds a filter_complex string and returns (inputs_to_add, filter_complex, maps).
    Actually returns filter_complex and notes.
    """
    filters: list[str] = []
    current = "[0:v]"
    idx = 0

    def push(expr: str) -> str:
        nonlocal idx, current
        out = f"[v{idx}]"
        filters.append(f"{current}{expr}{out}")
        current = out
        idx += 1
        return current

    eq = _eq_filter(cfg)
    if eq:
        push(eq)
    temp = _temperature_filter(cfg.video.temperature)
    if temp:
        push(temp)
    if cfg.video.fade > 0.5:
        # Lift blacks approximately
        lift = cfg.video.fade / 400.0
        push(f"curves=all='0/{lift:.4f} 1/1'")
    if cfg.video.sharpen > 0.5:
        # unsharp luma matrix
        push(f"unsharp=5:5:{cfg.video.sharpen / 50.0}:5:5:0.0")
    if cfg.video.grain > 0.5:
        push(f"noise=alls={min(50, int(cfg.video.grain / 2))}:allf=t")
    if cfg.video.vignette > 0.5:
        # vignette angle — higher = stronger
        angle = 0.5 + (cfg.video.vignette / 200.0)
        push(f"vignette=angle={angle:.3f}")

    if cfg.lut.lut_id:
        record = get_lut(cfg.lut.lut_id, brand_id)
        if record and record.status == "Ready" and ffmpeg_supports_lut3d():
            lut_path = resolve_lut_path(record)
            # Escape path for filtergraph
            escaped = str(lut_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            push(f"lut3d=file='{escaped}'")

    # Scale / pad for platform presets
    geo = cfg.geometry
    preset = PLATFORM_EXPORT_PRESETS.get(geo.platform_preset)
    if preset and preset.get("width") and preset.get("height"):
        tw, th = int(preset["width"]), int(preset["height"])
        if geo.fit_mode == "fit":
            push(
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=0xFAF7F1"
            )
        else:
            push(f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}")

    # Logo overlay
    if logo_png is not None and logo_png.is_file():
        # Will be input 1
        opacity = float(cfg.logo.opacity)
        enable = _logo_enable_expr(cfg, meta["duration"])
        # Position evaluated later with known sizes — use overlay with computed xy via filter
        # We bake position into overlay x/y from meta logo_xy
        x, y = meta.get("logo_xy", (24, 24))
        filters.append(
            f"{current}[1:v]overlay=x={int(x)}:y={int(y)}:format=auto:alpha=straight"
            + (f":enable='{enable}'" if enable else "")
            + f"[vout]"
        )
        current = "[vout]"
    else:
        filters.append(f"{current}null[vout]")
        current = "[vout]"

    # Fade in/out on video
    fade_in = cfg.export.fade_in_seconds
    fade_out = cfg.export.fade_out_seconds
    duration = float(meta["duration"])
    fade_parts = []
    if fade_in > 0:
        fade_parts.append(f"fade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0 and duration > fade_out:
        fade_parts.append(f"fade=t=out:st={duration - fade_out:.3f}:d={fade_out:.3f}")
    if fade_parts:
        filters.append(f"{current}{','.join(fade_parts)}[vfinal]")
        current = "[vfinal]"
    else:
        filters.append(f"{current}null[vfinal]")
        current = "[vfinal]"

    return filters, current


def _logo_enable_expr(cfg: FinishConfiguration, duration: float) -> str | None:
    mode = cfg.logo.timing_mode
    if mode == "full":
        return None
    if mode == "opening":
        end = min(3.0, duration)
        return f"between(t,0,{end:.3f})"
    if mode == "closing":
        start = max(0.0, duration - 3.0)
        return f"gte(t,{start:.3f})"
    start = float(cfg.logo.start_seconds or 0)
    end = float(cfg.logo.end_seconds if cfg.logo.end_seconds is not None else duration)
    start = max(0.0, min(start, duration))
    end = max(start, min(end, duration))
    return f"between(t,{start:.3f},{end:.3f})"


def prepare_logo_overlay(
    cfg: FinishConfiguration,
    *,
    brand_id: str,
    canvas_w: int,
    canvas_h: int,
    work_dir: Path,
) -> tuple[Path | None, tuple[int, int] | None]:
    logo_cfg = cfg.logo
    if logo_cfg.role in {"", "none"} and not logo_cfg.asset_id:
        record_overlay(
            OverlayEvent(
                source_function="studio.video_pipeline.prepare_logo_overlay",
                kind="skipped_logo",
                reason="Logo omitted by configuration (role=none).",
                applied=False,
            )
        )
        return None, None
    asset = None
    if logo_cfg.asset_id:
        asset = get_asset(logo_cfg.asset_id, brand_id)
    elif logo_cfg.role not in {"", "none"}:
        asset = default_asset_for_role(logo_cfg.role, brand_id)
    if asset is None:
        record_overlay(
            OverlayEvent(
                source_function="studio.video_pipeline.prepare_logo_overlay",
                kind="skipped_logo",
                reason="Logo asset could not be resolved.",
                applied=False,
            )
        )
        return None, None

    asset_path = resolve_asset_path(asset)
    if not is_suitable_transparent_mark(asset):
        record_overlay(
            OverlayEvent(
                source_function="studio.video_pipeline.prepare_logo_overlay",
                kind="skipped_logo",
                asset_path=str(asset_path),
                asset_id=asset.asset_id,
                reason=(
                    "Blocked solid-color rectangular badge / unsuitable mark from "
                    "being written as a video overlay."
                ),
                applied=False,
                extra={"role": asset.role},
            )
        )
        return None, None

    logo = rasterize_logo(asset_path)
    percent = SIZE_MODE_PERCENT.get(logo_cfg.size_mode, logo_cfg.size_percent)
    if logo_cfg.size_mode == "custom":
        percent = logo_cfg.size_percent
    target_w = max(1, int(canvas_w * (percent / 100.0)))
    aspect = logo.height / max(1, logo.width)
    target_h = max(1, int(target_w * aspect))
    logo = logo.resize((target_w, target_h), resample=1)
    if logo_cfg.opacity < 0.999:
        alpha = logo.getchannel("A")
        alpha = alpha.point(lambda p: int(p * max(0.1, min(1.0, logo_cfg.opacity))))
        logo.putalpha(alpha)
    margin = float(asset.default_safe_margin)
    if logo_cfg.safe_margin_mode == "pixels":
        margin = logo_cfg.safe_margin_value
    elif logo_cfg.safe_margin_mode == "percent":
        margin = canvas_w * (logo_cfg.safe_margin_value / 100.0)
    x, y = logo_box((canvas_w, canvas_h), logo.size, logo_cfg, safe_margin_px=margin)
    out = work_dir / "logo_overlay.png"
    logo.save(out, format="PNG")
    record_overlay(
        OverlayEvent(
            source_function="studio.video_pipeline.prepare_logo_overlay",
            kind="logo",
            asset_path=str(asset_path),
            asset_id=asset.asset_id,
            position=(x, y),
            dimensions=logo.size,
            opacity=float(logo_cfg.opacity),
            reason="Prepared suitable transparent mark for FFmpeg overlay.",
            applied=True,
            extra={"overlay_file": str(out), "safe_margin_px": margin},
        )
    )
    return out, (x, y)


def process_video(
    source: Path,
    config: FinishConfiguration,
    *,
    brand_id: str,
    output_path: Path,
    preview_path: Path | None = None,
    work_dir: Path,
) -> dict[str, Any]:
    from studio.overlay_diagnostics import reset_overlay_diagnostics, write_overlay_diagnostics

    if not ffmpeg_available():
        return {"ok": False, "error": "FFmpeg or ffprobe is not available on this machine."}

    reset_overlay_diagnostics()
    try:
        meta = probe_video(source)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}

    logo_png, logo_xy = prepare_logo_overlay(
        config,
        brand_id=brand_id,
        canvas_w=meta["width"],
        canvas_h=meta["height"],
        work_dir=work_dir,
    )
    meta["logo_xy"] = logo_xy or (24, 24)

    filter_parts, _ = build_video_filter_chain(
        config, brand_id=brand_id, meta=meta, logo_png=logo_png
    )
    filter_complex = ";".join(filter_parts)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [ffmpeg_bin() or "ffmpeg", "-y", "-i", str(source)]
    if logo_png is not None:
        cmd.extend(["-i", str(logo_png)])
    cmd.extend(["-filter_complex", filter_complex, "-map", "[vfinal]"])

    if meta.get("has_audio"):
        cmd.extend(["-map", "0:a?"])
        if config.export.audio_normalize:
            # loudnorm is slow but honest; use a lighter alternative when possible
            cmd.extend(["-af", "dynaudnorm=f=150:g=15"])
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.append("-an")

    fps = config.export.fps or meta.get("fps")
    if fps:
        cmd.extend(["-r", f"{float(fps):.3f}"])

    cmd.extend(
        [
            "-c:v",
            config.export.codec or "libx264",
            "-preset",
            config.export.quality_preset or "medium",
            "-b:v",
            config.export.bitrate or "8M",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if config.export.faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(str(output_path))

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "FFmpeg failed to process the video.",
            "ffmpeg_command": cmd,
            "stderr": (proc.stderr or "")[-4000:],
        }

    if not output_path.is_file() or output_path.stat().st_size <= 0:
        return {"ok": False, "error": "Video output file is missing or empty.", "ffmpeg_command": cmd}

    try:
        out_meta = probe_video(output_path)
    except RuntimeError as exc:
        return {"ok": False, "error": f"Output video could not be decoded: {exc}", "ffmpeg_command": cmd}

    # Duration plausibility (±15% or 0.5s)
    if abs(out_meta["duration"] - meta["duration"]) > max(0.5, meta["duration"] * 0.15):
        return {
            "ok": False,
            "error": (
                f"Output duration {out_meta['duration']:.2f}s is not plausible "
                f"for source {meta['duration']:.2f}s."
            ),
            "ffmpeg_command": cmd,
        }

    preview_files: list[Path] = []
    if preview_path is not None:
        # Extract a mid-frame preview image
        preview_path = Path(preview_path)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        t = meta["duration"] / 2.0
        pcmd = [
            ffmpeg_bin() or "ffmpeg",
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(output_path),
            "-frames:v",
            "1",
            str(preview_path),
        ]
        pproc = subprocess.run(pcmd, capture_output=True, text=True, check=False)
        if pproc.returncode == 0 and preview_path.is_file():
            preview_files.append(preview_path)

    diagnostics_path = write_overlay_diagnostics(work_dir)

    return {
        "ok": True,
        "output_files": [output_path],
        "preview_files": preview_files,
        "ffmpeg_command": cmd,
        "validation": {
            "outcome": "pass",
            "items": [
                {"code": "video_decode", "outcome": "pass", "message": "Output decodes."},
                {
                    "code": "duration",
                    "outcome": "pass",
                    "message": f"Duration {out_meta['duration']:.2f}s is plausible.",
                },
            ],
        },
        "technical_notes": {
            "source_meta": meta,
            "output_meta": out_meta,
            "stderr_tail": (proc.stderr or "")[-1500:],
            "lut3d_supported": ffmpeg_supports_lut3d(),
            "overlay_diagnostics": str(diagnostics_path) if diagnostics_path else None,
        },
    }
