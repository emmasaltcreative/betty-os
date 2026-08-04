"""Publishability checks for campaign export packages.

Validates media, copy, metadata pairing, and carousel completeness before a
deliverable enters the publishing ZIP. Does not rewrite content.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MEDIA_SUFFIXES = {".mp4", ".mov", ".png", ".jpg", ".jpeg"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
VIDEO_SUFFIXES = {".mp4", ".mov"}
COPY_SUFFIXES = {".md", ".txt"}

# Language that marks copy as unfinished planning, not publishable deliverable.
_BLOCKING_COPY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bextract\s+(a\s+|still\s+)?frame\b",
        r"\bcreate\s+this\s+later\b",
        r"\bexact\s+asset\s+file\s+paths?\b",
        r"\brecommended\s+shot\s+order\b",
        r"\bon[- ]screen\s+text\b.*\badd\b",
        r"\bTODO\b",
        r"\bTBD\b",
        r"\[placeholder\]",
        r"\blorem\s+ipsum\b",
        r"\bneeds?\s+revision\b",
        r"\bdraft\b",
        r"\bproposed\b",
        r"\bunresolved\b",
        r"\bfailed\s+generation\b",
        r"\bgeneration\s+failed\b",
        r"\braw\s+prompt\b",
        r"assets/[^\s]+\.(mov|mp4|png|jpg|jpeg)",
        r"`assets/",
        r"/Users/",
        r"/outputs/",
    )
)

@dataclass
class ValidationIssue:
    code: str
    message: str
    blocking: bool = True


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def blockers(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.blocking]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if not i.blocking]

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        issues = [*self.issues, *other.issues]
        return ValidationResult(ok=not any(i.blocking for i in issues), issues=issues)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_media_file(path: Path, *, expect: str = "any") -> ValidationResult:
    """expect: any | image | video."""
    issues: list[ValidationIssue] = []
    if not path.exists():
        return ValidationResult(
            False, [ValidationIssue("missing_file", f"Media file is missing: {path.name}")]
        )
    if not path.is_file():
        return ValidationResult(
            False, [ValidationIssue("not_a_file", f"Not a readable file: {path.name}")]
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        return ValidationResult(
            False, [ValidationIssue("unreadable", f"Cannot read {path.name}: {exc}")]
        )
    if size <= 0:
        issues.append(ValidationIssue("empty_file", f"File is empty: {path.name}"))

    suffix = path.suffix.lower()
    if expect == "image" and suffix not in IMAGE_SUFFIXES:
        issues.append(
            ValidationIssue("wrong_type", f"Expected an image, got {suffix or 'no extension'}")
        )
    if expect == "video" and suffix not in VIDEO_SUFFIXES:
        issues.append(
            ValidationIssue("wrong_type", f"Expected a video, got {suffix or 'no extension'}")
        )
    if suffix not in MEDIA_SUFFIXES:
        issues.append(
            ValidationIssue("unsupported_type", f"Unsupported media type: {suffix or path.name}")
        )

    if suffix in IMAGE_SUFFIXES and size > 0:
        issues.extend(_validate_image(path))
    if suffix in VIDEO_SUFFIXES and size > 0:
        issues.extend(_validate_video(path))

    return ValidationResult(ok=not any(i.blocking for i in issues), issues=issues)


def _validate_image(path: Path) -> list[ValidationIssue]:
    try:
        from PIL import Image
    except ImportError:
        return [
            ValidationIssue(
                "image_check_skipped",
                "Pillow unavailable; image dimensions were not verified.",
                blocking=False,
            )
        ]
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
        if width < 1 or height < 1:
            return [ValidationIssue("bad_dimensions", f"Invalid image dimensions for {path.name}")]
    except OSError as exc:
        return [ValidationIssue("corrupt_image", f"Image could not be opened: {exc}")]
    return []


def _validate_video(path: Path) -> list[ValidationIssue]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return [
            ValidationIssue(
                "video_check_skipped",
                "ffprobe unavailable; video decode was not verified.",
                blocking=False,
            )
        ]
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [ValidationIssue("video_probe_failed", f"Could not probe video: {exc}")]
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffprobe failed").strip()
        return [ValidationIssue("video_undecodable", f"Video does not decode: {detail[:200]}")]
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return [ValidationIssue("video_probe_failed", "ffprobe returned unreadable output")]
    streams = payload.get("streams") or []
    if not streams:
        return [ValidationIssue("video_no_stream", "Video has no video stream")]
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width < 1 or height < 1:
        return [ValidationIssue("bad_dimensions", f"Invalid video dimensions for {path.name}")]
    duration_raw = stream.get("duration") or (payload.get("format") or {}).get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return [
            ValidationIssue(
                "implausible_duration",
                f"Video duration is missing or zero for {path.name}",
            )
        ]
    if duration > 600:
        return [
            ValidationIssue(
                "implausible_duration",
                f"Video duration ({duration:.0f}s) looks implausible for a social deliverable",
                blocking=False,
            )
        ]
    return []


def validate_carousel_slides(paths: list[Path]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if not paths:
        return ValidationResult(
            False, [ValidationIssue("carousel_empty", "Carousel has no slides")]
        )
    dims: list[tuple[int, int]] = []
    for path in paths:
        media = validate_media_file(path, expect="image")
        issues.extend(media.issues)
        if not path.is_file():
            continue
        try:
            from PIL import Image

            with Image.open(path) as img:
                dims.append(img.size)
        except Exception:
            continue
    if len(dims) >= 2 and len({d for d in dims}) > 1:
        issues.append(
            ValidationIssue(
                "carousel_inconsistent_dims",
                "Carousel slides do not share consistent dimensions",
                blocking=False,
            )
        )
    return ValidationResult(ok=not any(i.blocking for i in issues), issues=issues)


def _is_blank(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    return text.lower() in {"", "n/a", "na", "none", "tbd", "todo", "placeholder", "—", "-"}


def copy_has_production_notes(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _BLOCKING_COPY_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern)
    return hits


def validate_copy_text(text: str, *, required: bool = True, label: str = "Copy") -> ValidationResult:
    issues: list[ValidationIssue] = []
    stripped = (text or "").strip()
    if required and _is_blank(stripped):
        issues.append(ValidationIssue("blank_copy", f"{label} is blank"))
        return ValidationResult(False, issues)
    if not stripped:
        return ValidationResult(True, issues)

    lower = stripped.lower()
    if any(token in lower for token in ("needs revision", "draft copy", "proposed copy")):
        issues.append(
            ValidationIssue("draft_label", f"{label} is still labeled draft or needs revision")
        )

    notes = copy_has_production_notes(stripped)
    if notes:
        issues.append(
            ValidationIssue(
                "production_notes",
                f"{label} still contains internal production instructions",
            )
        )
    return ValidationResult(ok=not any(i.blocking for i in issues), issues=issues)


def validate_pinterest_metadata_text(text: str) -> ValidationResult:
    """Pinterest metadata must have a real title and description, not planning notes."""
    from services.copy_documents import CopyDocument

    doc = CopyDocument.from_text(text)
    issues: list[ValidationIssue] = []
    title = doc.read("pinterest_title")
    description = doc.read("pinterest_description")
    if _is_blank(title):
        issues.append(ValidationIssue("blank_title", "Pinterest title is blank"))
    desc_result = validate_copy_text(description or "", required=True, label="Pinterest description")
    issues.extend(desc_result.issues)
    # Whole-document production notes (even outside Description)
    if copy_has_production_notes(text):
        if not any(i.code == "production_notes" for i in issues):
            issues.append(
                ValidationIssue(
                    "production_notes",
                    "Pinterest metadata still contains internal production instructions",
                )
            )
    return ValidationResult(ok=not any(i.blocking for i in issues), issues=issues)


def probe_media_meta(path: Path) -> dict:
    """Best-effort dimensions/duration for the manifest."""
    meta: dict = {"file_size": path.stat().st_size if path.is_file() else 0}
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        try:
            from PIL import Image

            with Image.open(path) as img:
                meta["width"], meta["height"] = img.size
                meta["dimensions"] = f"{img.size[0]}x{img.size[1]}"
        except Exception:
            pass
        return meta
    if suffix in VIDEO_SUFFIXES:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return meta
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,duration:format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            payload = json.loads(result.stdout or "{}")
            stream = (payload.get("streams") or [{}])[0]
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            if width and height:
                meta["width"] = width
                meta["height"] = height
                meta["dimensions"] = f"{width}x{height}"
            duration_raw = stream.get("duration") or (payload.get("format") or {}).get("duration")
            if duration_raw is not None:
                meta["duration"] = float(duration_raw)
        except Exception:
            pass
    return meta
