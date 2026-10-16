"""Canonical media resolution for Decide and previews.

Poster/preview stills must never replace a finished video deliverable.
Media type is derived from the actual file (and finish media_type), not labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class DecideMedia:
    """What Decide should show and whether approval is allowed."""

    canonical: Path | None
    poster: Path | None
    expects_video: bool
    kind: str  # "video" | "image" | "missing" | "unknown"
    blocking_message: str | None = None

    @property
    def can_approve(self) -> bool:
        if self.blocking_message:
            return False
        if self.expects_video:
            return bool(
                self.canonical
                and self.canonical.is_file()
                and self.canonical.suffix.lower() in VIDEO_SUFFIXES
            )
        return bool(self.canonical and self.canonical.is_file())


def is_video_path(path: Path | None) -> bool:
    return bool(path and path.suffix.lower() in VIDEO_SUFFIXES)


def is_image_path(path: Path | None) -> bool:
    return bool(path and path.suffix.lower() in IMAGE_SUFFIXES)


def expects_video_deliverable(version: Any, active: Any | None = None) -> bool:
    """Infer video expectation from finish/record metadata and file type — not labels."""
    if active is not None:
        media_type = str(getattr(active, "media_type", "") or "").lower()
        if media_type in {"video", "reel", "loop", "motion"}:
            return True
        if media_type in {"static", "image", "pin", "carousel"}:
            return False
    kind = str(getattr(version, "kind", "") or "").lower()
    if kind == "video":
        return True
    if kind == "image":
        return False
    template = str(getattr(version, "template_id", "") or "").lower()
    if any(token in template for token in ("reel", "video", "loop", "clip")):
        return True
    primary = getattr(version, "primary_path", None)
    if is_video_path(primary):
        return True
    return False


def resolve_canonical_finish_media(
    version: Any, active: Any | None
) -> tuple[Path | None, Path | None]:
    """Return (canonical deliverable, optional poster). Prefer outputs over previews."""
    canonical: Path | None = None
    poster: Path | None = None

    if active is not None:
        from studio.versions import resolve_finish_output, resolve_finish_outputs, resolve_finish_preview

        declared = list(getattr(active, "output_files", None) or [])
        outputs = resolve_finish_outputs(version.folder, active)
        # Prefer an actual video when present, else first finished output.
        videos = [p for p in outputs if is_video_path(p)]
        images = [p for p in outputs if is_image_path(p)]
        if videos:
            canonical = videos[0]
        elif images:
            canonical = images[0]
        else:
            canonical = resolve_finish_output(version.folder, active)

        poster_candidate = resolve_finish_preview(version.folder, active)
        if poster_candidate and is_image_path(poster_candidate):
            # Never treat the poster as the canonical deliverable.
            if canonical is None or poster_candidate.resolve() != Path(canonical).resolve():
                poster = poster_candidate

        # Only scan the outputs folder when metadata listed no usable paths.
        if canonical is None and not declared:
            from studio.paths import finish_version_dir

            folder = finish_version_dir(version.folder, active.finish_version_id)
            out_dir = folder / "outputs"
            if out_dir.is_dir():
                candidates = [
                    p
                    for p in sorted(out_dir.iterdir())
                    if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES | IMAGE_SUFFIXES
                ]
                finished = [p for p in candidates if p.name.startswith("finished")]
                pool = finished or candidates
                videos = [p for p in pool if is_video_path(p)]
                canonical = videos[0] if videos else (pool[0] if pool else None)

        # Do not fall back to the render primary when a finish was selected but
        # its declared outputs are missing — that hides a broken finish.
        if canonical is None and declared:
            return None, poster

    if canonical is None:
        primary = getattr(version, "primary_path", None)
        if primary is not None and Path(primary).is_file():
            canonical = Path(primary)

    return canonical, poster


def resolve_decide_media(version: Any, active: Any | None = None) -> DecideMedia:
    expects_video = expects_video_deliverable(version, active)
    canonical, poster = resolve_canonical_finish_media(version, active)

    if expects_video:
        if canonical is None or not Path(canonical).is_file():
            return DecideMedia(
                canonical=None,
                poster=poster if poster and Path(poster).is_file() else None,
                expects_video=True,
                kind="missing",
                blocking_message="Video output is missing. Recreate this deliverable.",
            )
        if not is_video_path(canonical):
            # Poster/still must not stand in for the reel.
            return DecideMedia(
                canonical=None,
                poster=canonical if is_image_path(canonical) else poster,
                expects_video=True,
                kind="missing",
                blocking_message="Video output is missing. Recreate this deliverable.",
            )
        return DecideMedia(
            canonical=Path(canonical),
            poster=poster if poster and Path(poster).is_file() else None,
            expects_video=True,
            kind="video",
        )

    if canonical is None or not Path(canonical).is_file():
        return DecideMedia(
            canonical=None,
            poster=None,
            expects_video=False,
            kind="missing",
            blocking_message="Preview unavailable. The deliverable file is no longer on disk.",
        )

    path = Path(canonical)
    if is_video_path(path):
        return DecideMedia(canonical=path, poster=poster, expects_video=False, kind="video")
    if is_image_path(path):
        return DecideMedia(canonical=path, poster=None, expects_video=False, kind="image")
    return DecideMedia(canonical=path, poster=None, expects_video=False, kind="unknown")
