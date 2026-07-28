"""Shared rendering primitives for BettyOS template families."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from src.common import ROOT, BettyOSError
from src.persistence import atomic_write_json

ASPECT_PIXELS = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "2:3": (1000, 1500),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def resolve_media_path(relative: str) -> Path:
    cleaned = relative.strip().strip("`")
    cleaned = re.split(r"\s+[—\-]\s+", cleaned, maxsplit=1)[0].strip()
    path = Path(cleaned)
    if not path.is_absolute():
        path = ROOT / cleaned
    return path


def validate_required_inputs(
    *,
    template_id: str,
    required: list[str],
    source_assets: list[str],
    copy_fields: dict[str, str] | None = None,
) -> list[str]:
    missing: list[str] = []
    copy_fields = copy_fields or {}
    existing = []
    for rel in source_assets:
        path = resolve_media_path(rel)
        if path.exists():
            existing.append(path)
        else:
            missing.append(f"source asset not found: {rel}")

    needs_media = any(
        key in required
        for key in (
            "source_video_clips",
            "source_videos",
            "source_image",
            "source_images",
            "source_assets",
        )
    )
    if needs_media and not existing and not any("not found" in m for m in missing):
        missing.append("at least one source asset")

    for key in ("hook_text", "cta_text", "caption", "body_text", "headline"):
        if key in required and not str(copy_fields.get(key) or "").strip():
            missing.append(key)
    return missing


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise BettyOSError("ffmpeg/ffprobe not found on PATH.")


def extract_frame(source: Path, output: Path, *, at_seconds: float = 1.0) -> Path:
    ensure_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if not output.is_file() or output.stat().st_size < 100:
        raise BettyOSError(f"Frame extraction failed for {source.name}")
    return output


def load_image(path: Path) -> Image.Image:
    if path.suffix.lower() in {".mov", ".mp4", ".m4v"}:
        tmp = path.parent / f".frame_{path.stem}.jpg"
        extract_frame(path, tmp)
        image = Image.open(tmp).convert("RGB")
        tmp.unlink(missing_ok=True)
        return image
    return Image.open(path).convert("RGB")


def cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def resolve_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/Library/Fonts/Georgia.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "Georgia.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_text_block(
    image: Image.Image,
    *,
    lines: list[str],
    y_ratio: float,
    font_size: int = 54,
    fill: tuple[int, int, int] = (255, 255, 255),
    max_width_ratio: float = 0.78,
) -> None:
    draw = ImageDraw.Draw(image)
    font = resolve_font(font_size)
    max_width = int(image.width * max_width_ratio)
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(wrap_text(draw, line, font, max_width) or [""])
    y = int(image.height * y_ratio)
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (image.width - tw) // 2
        # subtle shadow for legibility
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=fill)
        y += th + int(font_size * 0.35)


def canvas_from_assets(
    assets: list[Path],
    *,
    aspect: str,
    mode: str = "single",
) -> Image.Image:
    size = ASPECT_PIXELS.get(aspect, ASPECT_PIXELS["4:5"])
    if not assets:
        raise BettyOSError("Cannot create canvas without source assets.")
    if mode == "collage" and len(assets) >= 2:
        a = cover_resize(load_image(assets[0]), (size[0], size[1] // 2))
        b = cover_resize(load_image(assets[1]), (size[0], size[1] - a.height))
        canvas = Image.new("RGB", size, (246, 241, 232))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (0, a.height))
        return canvas
    return cover_resize(load_image(assets[0]), size)


def write_render_manifest(
    out_dir: Path,
    *,
    template_id: str,
    content_piece_id: str,
    version: int,
    outputs: list[str],
    source_assets: list[str],
    config: dict[str, Any],
    parent_version: int | None = None,
) -> Path:
    payload = {
        "template_id": template_id,
        "content_piece_id": content_piece_id,
        "version": version,
        "parent_version": parent_version,
        "created_at": now_iso(),
        "review_status": "awaiting_review",
        "source_assets": source_assets,
        "outputs": outputs,
        "config": config,
    }
    return atomic_write_json(out_dir / f"render_manifest_v{version}.json", payload)


def next_output_version(out_dir: Path, stem: str, suffix: str) -> int:
    highest = 0
    for path in out_dir.glob(f"{stem}_v*.{suffix.lstrip('.')}"):
        match = re.search(r"_v(\d+)\.", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def validate_outputs(paths: list[Path]) -> None:
    for path in paths:
        if not path.is_file() or path.stat().st_size < 20:
            raise BettyOSError(f"Render output missing or empty: {path.name}")
