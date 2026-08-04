"""Package publishable campaign assets into a downloadable archive.

Default mode builds a decisive Publishing Package: one canonical final
deliverable per content piece and platform destination. Archive mode remains
available for historical dumps. Export never modifies, moves, or deletes
renders or Studio finishes on disk.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from src.common import timestamp_stamp
from ui.campaign_state import (
    CampaignState,
    RenderVersion,
    approved_finish_records_for_version,
    finish_records_for_version,
)
from ui.capability import exports_dir
from ui.publishing_validation import (
    COPY_SUFFIXES,
    IMAGE_SUFFIXES,
    MEDIA_SUFFIXES,
    VIDEO_SUFFIXES,
    file_sha256,
    probe_media_meta,
    validate_carousel_slides,
    validate_copy_text,
    validate_media_file,
    validate_pinterest_metadata_text,
)

# Publishing is the default. "approved" is retained as an alias so existing
# callers (Deliver stage, older UI state) keep working.
PUBLISHING_MODE = "publishing"
ARCHIVE_MODE = "archive"
LEGACY_APPROVED = "approved"

MODES: tuple[tuple[str, str, str], ...] = (
    (
        PUBLISHING_MODE,
        "Publishing Package",
        "One canonical final version per content piece. No history, no duplicates, "
        "no incomplete deliverables.",
    ),
    (
        ARCHIVE_MODE,
        "Archive Package",
        "Historical dump of versions and technical files. Not a publishing package.",
    ),
)

MODE_LABELS = {key: label for key, label, _ in MODES}
MODE_LABELS[LEGACY_APPROVED] = MODE_LABELS[PUBLISHING_MODE]

TEMPLATE_PLATFORM: dict[str, str] = {
    "cinematic_multi_clip_reel": "instagram",
    "single_clip_atmospheric_loop": "instagram",
    "instagram_caption": "instagram",
    "text_led_editorial_pin": "pinterest",
    "pinterest_collage_pin": "pinterest",
    "editorial_static_pin": "pinterest",
    "pinterest_caption_metadata": "pinterest",
    "editorial_carousel": "carousel",
    "product_detail_carousel": "carousel",
}

PIN_TEMPLATES = {
    "text_led_editorial_pin",
    "pinterest_collage_pin",
    "editorial_static_pin",
}
METADATA_TEMPLATES = {"pinterest_caption_metadata"}
COPY_ONLY_TEMPLATES = {"instagram_caption", "email_sequence", "product_copy"}
CAROUSEL_TEMPLATES = {"editorial_carousel", "product_detail_carousel"}


@dataclass
class PackageFile:
    source: Path
    archive_name: str
    role: str  # media | slide | caption | metadata | support
    file_hash: str = ""
    file_size: int = 0


@dataclass
class DuplicateRecord:
    kept: str
    removed: str
    file_hash: str
    reason: str = "byte-identical"


@dataclass
class ExportItem:
    label: str
    file_count: int
    total_bytes: int
    display_name: str = ""
    platform: str = ""
    content_type: str = ""
    content_piece_id: str | None = None
    media_type: str = ""
    approval_status: str = "approved"
    approved_at: str | None = None
    render_version_id: str | None = None
    finish_version_id: str | None = None
    parent_render_version_id: str | None = None
    package_files: list[PackageFile] = field(default_factory=list)
    paired_caption: str = ""
    paired_metadata: str = ""
    file_hash: str = ""
    dimensions: str = ""
    duration: float | None = None
    destination_url: str = ""
    tracking_parameters: str = ""
    summary_kind: str = ""
    slide_count: int = 0
    warnings: list[str] = field(default_factory=list)
    # Legacy fields retained for archive-mode / older UI paths.
    version: RenderVersion | None = None
    finish_files: list[tuple[str, Path]] = field(default_factory=list)


@dataclass
class ExportExclusion:
    label: str
    reason: str
    category: str = "excluded"  # superseded | duplicate | incomplete | rejected | other
    content_piece_id: str | None = None


@dataclass
class PackageSummary:
    included_lines: list[str] = field(default_factory=list)
    excluded_lines: list[str] = field(default_factory=list)
    warning_lines: list[str] = field(default_factory=list)
    reel_count: int = 0
    pin_count: int = 0
    carousel_count: int = 0
    carousel_slides: int = 0
    caption_count: int = 0
    metadata_count: int = 0
    superseded_count: int = 0
    duplicate_count: int = 0
    incomplete_count: int = 0


@dataclass
class ExportPlan:
    mode: str
    included: list[ExportItem] = field(default_factory=list)
    excluded: list[ExportExclusion] = field(default_factory=list)
    duplicates_removed: list[DuplicateRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    validation_status: str = "ready"  # ready | ready_with_warnings | blocked
    include_metadata: bool = False
    summary: PackageSummary = field(default_factory=PackageSummary)
    root_folder: str = ""
    created_at_iso: str = ""

    @property
    def file_count(self) -> int:
        return sum(item.file_count for item in self.included)

    @property
    def total_bytes(self) -> int:
        return sum(item.total_bytes for item in self.included)

    @property
    def is_empty(self) -> bool:
        return not self.included

    @property
    def is_blocked(self) -> bool:
        return self.validation_status == "blocked" or bool(self.blockers)


@dataclass
class ExportResult:
    ok: bool
    message: str
    path: Path | None = None
    file_count: int = 0
    total_bytes: int = 0
    included: list[str] = field(default_factory=list)
    excluded: list[ExportExclusion] = field(default_factory=list)
    created_at: str = ""
    detail: str | None = None
    validation_status: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: PackageSummary | None = None


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def normalize_mode(mode: str) -> str:
    if mode in {LEGACY_APPROVED, "publishing_package"}:
        return PUBLISHING_MODE
    if mode in {"full_archive", "archive_package"}:
        return ARCHIVE_MODE
    return mode


def _piece_label(state: CampaignState, version: RenderVersion) -> str:
    return state.describe(version)


def _slug(text: str, *, fallback: str = "asset") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return cleaned[:80] or fallback


def _campaign_slug(state: CampaignState) -> str:
    if state.path:
        return _slug(state.path.name, fallback="campaign")
    return _slug(state.name, fallback="campaign")


def _platform_for(template_id: str) -> str:
    return TEMPLATE_PLATFORM.get(template_id, "other")


def _content_type_for(template_id: str, display_name: str) -> str:
    return display_name or template_id.replace("_", " ").title()


def _group_key(version: RenderVersion) -> str:
    piece = version.piece_id or f"_template_{version.template_id}"
    return f"{piece}::{version.template_id}"


def _finish_sort_key(record) -> tuple:
    match = re.search(r"(\d+)$", record.finish_version_id or "")
    number = int(match.group(1)) if match else 0
    return (number, record.updated_at or "", record.finish_version_id or "")


def _render_version_token(version: int) -> str:
    return f"render_v{version:03d}"


def _ordered_carousel_slides(media: list[Path]) -> list[Path]:
    images = [p for p in media if p.suffix.lower() in IMAGE_SUFFIXES]

    def sort_key(path: Path) -> tuple:
        name = path.name.lower()
        match = re.search(r"slide[_\s-]?(\d+)", name)
        if match:
            return (0, int(match.group(1)), name)
        match = re.search(r"(?:^|[_\-])(\d{1,2})(?:\.|[_\-])", name)
        if match:
            return (0, int(match.group(1)), name)
        return (1, 0, name)

    return sorted(images, key=sort_key)


def _support_docs(version: RenderVersion) -> list[Path]:
    return [p for p in version.support_files if p.is_file()]


def _caption_docs(docs: list[Path]) -> list[Path]:
    return [p for p in docs if "caption" in p.name.lower() or p.suffix.lower() in COPY_SUFFIXES]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_metadata_doc(path: Path, template_id: str) -> bool:
    if template_id in METADATA_TEMPLATES:
        return True
    text = _read_text(path)[:400].lower()
    return "pinterest pin description" in text


def _piece_title(state: CampaignState, version: RenderVersion) -> str:
    title = state.piece_title(version)
    if title:
        return title
    return version.display_name


def _has_paired_pin(state: CampaignState, piece_id: str | None, included_pins: set[str]) -> bool:
    if not piece_id:
        return False
    if piece_id in included_pins:
        return True
    for version in state.versions:
        if version.piece_id != piece_id:
            continue
        if version.template_id not in PIN_TEMPLATES:
            continue
        if version.approval_status == "approved" and any(p.is_file() for p in version.media_files):
            return True
        for record in approved_finish_records_for_version(version):
            from studio.versions import resolve_finish_outputs

            if resolve_finish_outputs(version.folder, record):
                return True
    return False


# --- Publishing selection ----------------------------------------------------

def _collect_approved_finishes(
    versions: list[RenderVersion],
) -> list[tuple[RenderVersion, object]]:
    pairs: list[tuple[RenderVersion, object]] = []
    for version in versions:
        for record in approved_finish_records_for_version(version):
            pairs.append((version, record))
    pairs.sort(key=lambda pair: _finish_sort_key(pair[1]), reverse=True)
    return pairs


def _select_canonical(
    state: CampaignState,
    versions: list[RenderVersion],
) -> tuple[str, RenderVersion | None, object | None, str | None]:
    """Return (kind, version, finish_record|None, exclusion_reason|None).

    kind: finish | render | copy | none
    """
    approved_versions = [v for v in versions if v.approval_status == "approved"]
    finish_pairs = _collect_approved_finishes(versions)

    if finish_pairs:
        version, record = finish_pairs[0]
        return "finish", version, record, None

    if approved_versions:
        latest = max(approved_versions, key=lambda v: v.version)
        if latest.kind == "copy" or latest.template_id in COPY_ONLY_TEMPLATES | METADATA_TEMPLATES:
            return "copy", latest, None, None
        if latest.media_files or latest.support_files:
            return "render", latest, None, None
        return "none", latest, None, "No files found on disk"

    # No approved render and no approved finish.
    statuses = {v.approval_status for v in versions}
    if statuses & {"needs_revision"}:
        return "none", None, None, "Marked as needing revision"
    if statuses & {"rejected"}:
        return "none", None, None, "Rejected"
    if versions:
        return "none", None, None, "Not approved"
    return "none", None, None, "No render versions found"


def _package_basename(state: CampaignState, version: RenderVersion) -> str:
    title = _piece_title(state, version)
    base = _slug(title, fallback=_slug(version.display_name, fallback=version.template_id))
    # Avoid colliding unrelated templates that share a piece title.
    platform = _platform_for(version.template_id)
    if platform == "instagram" and version.kind == "video":
        return f"{base}-reel" if "reel" not in base else base
    if platform == "pinterest" and version.template_id in PIN_TEMPLATES:
        return f"{base}-pin" if "pin" not in base else base
    if platform == "carousel":
        return f"{base}-carousel" if "carousel" not in base else base
    if version.template_id == "instagram_caption":
        return f"{base}-caption"
    if version.template_id in METADATA_TEMPLATES:
        return f"{base}-metadata"
    return base


def _ext_for(path: Path) -> str:
    return path.suffix.lower() or ""


def _build_finish_item(
    state: CampaignState,
    version: RenderVersion,
    record,
    *,
    root: str,
) -> tuple[ExportItem | None, list[ExportExclusion]]:
    from studio.versions import resolve_finish_outputs

    exclusions: list[ExportExclusion] = []
    outputs = resolve_finish_outputs(version.folder, record)
    if not outputs:
        return None, [
            ExportExclusion(
                f"{_piece_label(state, version)} (Studio {record.finish_version_id})",
                "Approved Studio finish has no output file on disk",
                category="incomplete",
                content_piece_id=version.piece_id,
            )
        ]

    media_outputs = [p for p in outputs if p.suffix.lower() in MEDIA_SUFFIXES]
    if not media_outputs:
        media_outputs = outputs

    primary = media_outputs[0]
    expect = "video" if primary.suffix.lower() in VIDEO_SUFFIXES else "image"
    if version.template_id in CAROUSEL_TEMPLATES:
        media_check = validate_carousel_slides(media_outputs)
    else:
        media_check = validate_media_file(primary, expect=expect)
    if not media_check.ok:
        reason = media_check.blockers[0].message if media_check.blockers else "Invalid media"
        return None, [
            ExportExclusion(
                f"{_piece_label(state, version)} (Studio {record.finish_version_id})",
                reason,
                category="incomplete",
                content_piece_id=version.piece_id,
            )
        ]

    base = _package_basename(state, version)
    platform = _platform_for(version.template_id)
    files: list[PackageFile] = []
    warnings = [i.message for i in media_check.warnings]

    if version.template_id in CAROUSEL_TEMPLATES:
        slides = _ordered_carousel_slides(media_outputs) or media_outputs
        folder = f"{root}/{platform}/{base}"
        for index, slide in enumerate(slides, start=1):
            digest = file_sha256(slide)
            files.append(
                PackageFile(
                    source=slide,
                    archive_name=f"{folder}/{index:02d}{_ext_for(slide)}",
                    role="slide",
                    file_hash=digest,
                    file_size=slide.stat().st_size,
                )
            )
        caption_path = ""
        for doc in _caption_docs(_support_docs(version)):
            copy_check = validate_copy_text(_read_text(doc), required=False, label="Caption")
            if not copy_check.ok:
                warnings.append(
                    "This asset is approved visually, but its publishing copy is incomplete."
                )
                continue
            digest = file_sha256(doc)
            archive_name = f"{folder}/caption.txt"
            files.append(
                PackageFile(
                    source=doc,
                    archive_name=archive_name,
                    role="caption",
                    file_hash=digest,
                    file_size=doc.stat().st_size,
                )
            )
            caption_path = archive_name
            break
        meta = probe_media_meta(slides[0]) if slides else {}
        item = ExportItem(
            label=f"{version.display_name} · {_piece_title(state, version)}",
            file_count=len(files),
            total_bytes=sum(f.file_size for f in files),
            display_name=_piece_title(state, version),
            platform=platform,
            content_type=_content_type_for(version.template_id, version.display_name),
            content_piece_id=version.piece_id,
            media_type="carousel",
            approval_status=record.approval_status,
            approved_at=getattr(record, "updated_at", None) or version.reviewed_at,
            render_version_id=_render_version_token(version.version),
            finish_version_id=record.finish_version_id,
            parent_render_version_id=record.parent_render_version_id,
            package_files=files,
            paired_caption=caption_path,
            file_hash=files[0].file_hash if files else "",
            dimensions=str(meta.get("dimensions") or ""),
            duration=meta.get("duration"),
            summary_kind="carousel",
            slide_count=len([f for f in files if f.role == "slide"]),
            warnings=warnings,
            version=version,
        )
        return item, exclusions

    # Single media finish
    digest = file_sha256(primary)
    archive_media = f"{root}/{platform}/{base}{_ext_for(primary)}"
    files.append(
        PackageFile(
            source=primary,
            archive_name=archive_media,
            role="media",
            file_hash=digest,
            file_size=primary.stat().st_size,
        )
    )
    caption_path = ""
    for doc in _caption_docs(_support_docs(version)):
        text = _read_text(doc)
        copy_check = validate_copy_text(text, required=False, label="Caption")
        if copy_has_blocking_copy(text):
            warnings.append(
                "This asset is approved visually, but its publishing copy is incomplete."
            )
            continue
        if not copy_check.ok:
            warnings.append(
                "This asset is approved visually, but its publishing copy is incomplete."
            )
            continue
        c_digest = file_sha256(doc)
        archive_name = f"{root}/{platform}/{base}_caption.txt"
        files.append(
            PackageFile(
                source=doc,
                archive_name=archive_name,
                role="caption",
                file_hash=c_digest,
                file_size=doc.stat().st_size,
            )
        )
        caption_path = archive_name
        break

    meta = probe_media_meta(primary)
    kind = "reel" if primary.suffix.lower() in VIDEO_SUFFIXES else "pin"
    item = ExportItem(
        label=f"{version.display_name} · {_piece_title(state, version)}",
        file_count=len(files),
        total_bytes=sum(f.file_size for f in files),
        display_name=_piece_title(state, version),
        platform=platform,
        content_type=_content_type_for(version.template_id, version.display_name),
        content_piece_id=version.piece_id,
        media_type="video" if kind == "reel" else "image",
        approval_status=record.approval_status,
        approved_at=getattr(record, "updated_at", None) or version.reviewed_at,
        render_version_id=_render_version_token(version.version),
        finish_version_id=record.finish_version_id,
        parent_render_version_id=record.parent_render_version_id,
        package_files=files,
        paired_caption=caption_path,
        file_hash=digest,
        dimensions=str(meta.get("dimensions") or ""),
        duration=meta.get("duration"),
        summary_kind=kind,
        warnings=warnings,
        version=version,
    )
    return item, exclusions


def copy_has_blocking_copy(text: str) -> bool:
    from ui.publishing_validation import copy_has_production_notes

    return bool(copy_has_production_notes(text))


def _build_render_item(
    state: CampaignState,
    version: RenderVersion,
    *,
    root: str,
) -> tuple[ExportItem | None, list[ExportExclusion]]:
    exclusions: list[ExportExclusion] = []
    label = _piece_label(state, version)
    platform = _platform_for(version.template_id)
    base = _package_basename(state, version)
    media = [p for p in version.media_files if p.is_file()]
    docs = _support_docs(version)

    if version.template_id in CAROUSEL_TEMPLATES:
        slides = _ordered_carousel_slides(media)
        check = validate_carousel_slides(slides)
        if not check.ok:
            reason = check.blockers[0].message if check.blockers else "Carousel incomplete"
            return None, [
                ExportExclusion(label, reason, category="incomplete", content_piece_id=version.piece_id)
            ]
        files: list[PackageFile] = []
        folder = f"{root}/{platform}/{base}"
        for index, slide in enumerate(slides, start=1):
            files.append(
                PackageFile(
                    source=slide,
                    archive_name=f"{folder}/{index:02d}{_ext_for(slide)}",
                    role="slide",
                    file_hash=file_sha256(slide),
                    file_size=slide.stat().st_size,
                )
            )
        caption_path = ""
        warnings = [i.message for i in check.warnings]
        for doc in _caption_docs(docs):
            text = _read_text(doc)
            copy_check = validate_copy_text(text, required=False, label="Caption")
            if not copy_check.ok or copy_has_blocking_copy(text):
                warnings.append(
                    "This asset is approved visually, but its publishing copy is incomplete."
                )
                continue
            archive_name = f"{folder}/caption.txt"
            files.append(
                PackageFile(
                    source=doc,
                    archive_name=archive_name,
                    role="caption",
                    file_hash=file_sha256(doc),
                    file_size=doc.stat().st_size,
                )
            )
            caption_path = archive_name
            break
        meta = probe_media_meta(slides[0]) if slides else {}
        return (
            ExportItem(
                label=label,
                file_count=len(files),
                total_bytes=sum(f.file_size for f in files),
                display_name=_piece_title(state, version),
                platform=platform,
                content_type=_content_type_for(version.template_id, version.display_name),
                content_piece_id=version.piece_id,
                media_type="carousel",
                approval_status=version.approval_status,
                approved_at=version.reviewed_at,
                render_version_id=_render_version_token(version.version),
                package_files=files,
                paired_caption=caption_path,
                file_hash=files[0].file_hash if files else "",
                dimensions=str(meta.get("dimensions") or ""),
                summary_kind="carousel",
                slide_count=len(slides),
                warnings=warnings,
                version=version,
            ),
            exclusions,
        )

    if not media:
        return None, [
            ExportExclusion(label, "No media file found on disk", category="incomplete", content_piece_id=version.piece_id)
        ]

    primary = version.primary_path if version.primary_path in media else media[0]
    expect = "video" if primary.suffix.lower() in VIDEO_SUFFIXES else "image"
    check = validate_media_file(primary, expect=expect)
    if not check.ok:
        reason = check.blockers[0].message if check.blockers else "Invalid media"
        return None, [
            ExportExclusion(label, reason, category="incomplete", content_piece_id=version.piece_id)
        ]

    files = [
        PackageFile(
            source=primary,
            archive_name=f"{root}/{platform}/{base}{_ext_for(primary)}",
            role="media",
            file_hash=file_sha256(primary),
            file_size=primary.stat().st_size,
        )
    ]
    warnings = [i.message for i in check.warnings]
    caption_path = ""
    for doc in _caption_docs(docs):
        text = _read_text(doc)
        copy_check = validate_copy_text(text, required=False, label="Caption")
        if not copy_check.ok or copy_has_blocking_copy(text):
            warnings.append(
                "This asset is approved visually, but its publishing copy is incomplete."
            )
            continue
        archive_name = f"{root}/{platform}/{base}_caption.txt"
        files.append(
            PackageFile(
                source=doc,
                archive_name=archive_name,
                role="caption",
                file_hash=file_sha256(doc),
                file_size=doc.stat().st_size,
            )
        )
        caption_path = archive_name
        break

    meta = probe_media_meta(primary)
    kind = "reel" if primary.suffix.lower() in VIDEO_SUFFIXES else "pin"
    return (
        ExportItem(
            label=label,
            file_count=len(files),
            total_bytes=sum(f.file_size for f in files),
            display_name=_piece_title(state, version),
            platform=platform,
            content_type=_content_type_for(version.template_id, version.display_name),
            content_piece_id=version.piece_id,
            media_type="video" if kind == "reel" else "image",
            approval_status=version.approval_status,
            approved_at=version.reviewed_at,
            render_version_id=_render_version_token(version.version),
            package_files=files,
            paired_caption=caption_path,
            file_hash=files[0].file_hash,
            dimensions=str(meta.get("dimensions") or ""),
            duration=meta.get("duration"),
            summary_kind=kind,
            warnings=warnings,
            version=version,
        ),
        exclusions,
    )


def _build_copy_item(
    state: CampaignState,
    version: RenderVersion,
    *,
    root: str,
    included_pin_pieces: set[str],
) -> tuple[ExportItem | None, list[ExportExclusion]]:
    label = _piece_label(state, version)
    docs = [p for p in version.all_files(include_metadata=False) if p.is_file()]
    if not docs:
        return None, [
            ExportExclusion(label, "No copy file found on disk", category="incomplete", content_piece_id=version.piece_id)
        ]
    primary = version.primary_path if version.primary_path in docs else docs[0]
    text = _read_text(primary)
    platform = _platform_for(version.template_id)
    base = _package_basename(state, version)

    if version.template_id in METADATA_TEMPLATES or _is_metadata_doc(primary, version.template_id):
        meta_check = validate_pinterest_metadata_text(text)
        if not meta_check.ok:
            reason = meta_check.blockers[0].message if meta_check.blockers else "Incomplete metadata"
            return None, [
                ExportExclusion(label, reason, category="incomplete", content_piece_id=version.piece_id)
            ]
        if not _has_paired_pin(state, version.piece_id, included_pin_pieces):
            return None, [
                ExportExclusion(
                    label,
                    "No matching final Pin image or video for this metadata",
                    category="incomplete",
                    content_piece_id=version.piece_id,
                )
            ]
        # Keep metadata human-readable; pairing IDs live in manifest.json.
        text_name = f"{root}/{platform}/{base}.txt"
        files = [
            PackageFile(
                source=primary,
                archive_name=text_name,
                role="metadata",
                file_hash=file_sha256(primary),
                file_size=primary.stat().st_size,
            )
        ]
        return (
            ExportItem(
                label=label,
                file_count=len(files),
                total_bytes=sum(f.file_size for f in files),
                display_name=_piece_title(state, version),
                platform=platform,
                content_type=_content_type_for(version.template_id, version.display_name),
                content_piece_id=version.piece_id,
                media_type="metadata",
                approval_status=version.approval_status,
                approved_at=version.reviewed_at,
                render_version_id=_render_version_token(version.version),
                package_files=files,
                paired_metadata=text_name,
                file_hash=files[0].file_hash,
                summary_kind="metadata",
                version=version,
            ),
            [],
        )

    # Genuine copy-only (e.g. Instagram caption)
    copy_check = validate_copy_text(text, required=True, label=version.display_name)
    if not copy_check.ok:
        reason = copy_check.blockers[0].message if copy_check.blockers else "Incomplete copy"
        return None, [
            ExportExclusion(label, reason, category="incomplete", content_piece_id=version.piece_id)
        ]
    if copy_has_blocking_copy(text):
        return None, [
            ExportExclusion(
                label,
                "Copy still contains internal production instructions",
                category="incomplete",
                content_piece_id=version.piece_id,
            )
        ]

    archive_name = f"{root}/{platform}/{base}.txt"
    files = [
        PackageFile(
            source=primary,
            archive_name=archive_name,
            role="caption",
            file_hash=file_sha256(primary),
            file_size=primary.stat().st_size,
        )
    ]
    return (
        ExportItem(
            label=label,
            file_count=len(files),
            total_bytes=sum(f.file_size for f in files),
            display_name=_piece_title(state, version),
            platform=platform,
            content_type=_content_type_for(version.template_id, version.display_name),
            content_piece_id=version.piece_id,
            media_type="copy",
            approval_status=version.approval_status,
            approved_at=version.reviewed_at,
            render_version_id=_render_version_token(version.version),
            package_files=files,
            paired_caption=archive_name,
            file_hash=files[0].file_hash,
            summary_kind="caption",
            version=version,
        ),
        [],
    )


def _dedupe_plan(
    included: list[ExportItem],
    excluded: list[ExportExclusion],
) -> tuple[list[ExportItem], list[ExportExclusion], list[DuplicateRecord]]:
    seen_hashes: dict[str, ExportItem] = {}
    kept: list[ExportItem] = []
    duplicates: list[DuplicateRecord] = []

    for item in included:
        media_files = [f for f in item.package_files if f.role in {"media", "slide"}]
        # Deduplicate whole deliverables when primary media hash collides.
        primary_hash = media_files[0].file_hash if media_files else item.file_hash
        if primary_hash and primary_hash in seen_hashes:
            prior = seen_hashes[primary_hash]
            duplicates.append(
                DuplicateRecord(
                    kept=prior.label,
                    removed=item.label,
                    file_hash=primary_hash,
                )
            )
            excluded.append(
                ExportExclusion(
                    item.label,
                    f"Duplicate of {prior.label} (identical file hash)",
                    category="duplicate",
                    content_piece_id=item.content_piece_id,
                )
            )
            continue
        # Also drop duplicate support files within the package by hash.
        filtered_files: list[PackageFile] = []
        file_hashes_in_item: set[str] = set()
        for pkg in item.package_files:
            if pkg.file_hash and pkg.file_hash in file_hashes_in_item:
                duplicates.append(
                    DuplicateRecord(
                        kept=filtered_files[-1].archive_name if filtered_files else item.label,
                        removed=pkg.archive_name,
                        file_hash=pkg.file_hash,
                    )
                )
                continue
            if pkg.file_hash:
                file_hashes_in_item.add(pkg.file_hash)
            filtered_files.append(pkg)
        item.package_files = filtered_files
        item.file_count = len(filtered_files)
        item.total_bytes = sum(f.file_size for f in filtered_files)
        if primary_hash:
            seen_hashes[primary_hash] = item
        kept.append(item)
    return kept, excluded, duplicates


def _summarize(plan: ExportPlan) -> PackageSummary:
    summary = PackageSummary()
    for item in plan.included:
        if item.summary_kind == "reel":
            summary.reel_count += 1
            summary.included_lines.append(f"1 final {item.content_type or 'Reel'}")
        elif item.summary_kind == "pin":
            summary.pin_count += 1
            summary.included_lines.append(f"1 final {item.content_type or 'Pin'}")
        elif item.summary_kind == "carousel":
            summary.carousel_count += 1
            summary.carousel_slides += item.slide_count
            summary.included_lines.append(
                f"1 carousel with {item.slide_count} slides"
                if item.slide_count
                else "1 final carousel"
            )
        elif item.summary_kind == "caption":
            summary.caption_count += 1
        elif item.summary_kind == "metadata":
            summary.metadata_count += 1
            summary.included_lines.append("1 Pinterest metadata record")
        else:
            summary.included_lines.append(item.label)
        if item.paired_caption and item.summary_kind in {"reel", "pin", "carousel"}:
            summary.caption_count += 1
        for warning in item.warnings:
            if warning not in summary.warning_lines:
                summary.warning_lines.append(warning)

    if summary.caption_count:
        n = summary.caption_count
        summary.included_lines.append(f"{n} final caption{'s' if n != 1 else ''}")
    if summary.metadata_count and not any(
        "metadata" in line.lower() for line in summary.included_lines
    ):
        n = summary.metadata_count
        summary.included_lines.append(
            f"{n} Pinterest metadata record{'s' if n != 1 else ''}"
        )

    for exclusion in plan.excluded:
        summary.excluded_lines.append(f"{exclusion.label} — {exclusion.reason}")
        if exclusion.category == "superseded":
            summary.superseded_count += 1
        elif exclusion.category == "duplicate":
            summary.duplicate_count += 1
        elif exclusion.category == "incomplete":
            summary.incomplete_count += 1

    summary.duplicate_count = max(summary.duplicate_count, len(plan.duplicates_removed))
    for warning in plan.warnings:
        if warning not in summary.warning_lines:
            summary.warning_lines.append(warning)
    return summary


def build_publishing_plan(state: CampaignState) -> ExportPlan:
    root = f"{_campaign_slug(state)}_publishing-package"
    plan = ExportPlan(mode=PUBLISHING_MODE, root_folder=root)
    groups: dict[str, list[RenderVersion]] = {}
    for version in state.versions:
        groups.setdefault(_group_key(version), []).append(version)

    # First pass: select media deliverables so metadata can pair against them.
    pending_copy: list[tuple[str, list[RenderVersion]]] = []
    included_pin_pieces: set[str] = set()

    for key, versions in sorted(groups.items()):
        template_id = versions[0].template_id
        if template_id in METADATA_TEMPLATES or (
            versions[0].kind == "copy" and template_id in COPY_ONLY_TEMPLATES | METADATA_TEMPLATES
        ):
            pending_copy.append((key, versions))
            continue

        kind, version, finish, reason = _select_canonical(state, versions)
        label_versions = versions
        if kind == "none":
            sample = versions[0]
            plan.excluded.append(
                ExportExclusion(
                    _piece_label(state, sample),
                    reason or "Excluded",
                    category="rejected"
                    if reason in {"Rejected", "Marked as needing revision", "Not approved"}
                    else "incomplete",
                    content_piece_id=sample.piece_id,
                )
            )
            continue

        assert version is not None
        # Record superseded approved versions / finishes in the same group.
        for other in label_versions:
            if other.key == version.key:
                continue
            if other.approval_status == "approved":
                plan.excluded.append(
                    ExportExclusion(
                        _piece_label(state, other),
                        "Superseded by the canonical final version",
                        category="superseded",
                        content_piece_id=other.piece_id,
                    )
                )
            elif other.approval_status in {"needs_revision", "rejected", "awaiting_review"}:
                status_reason = {
                    "needs_revision": "Marked as needing revision",
                    "rejected": "Rejected",
                    "awaiting_review": "Not approved yet",
                }[other.approval_status]
                plan.excluded.append(
                    ExportExclusion(
                        _piece_label(state, other),
                        status_reason,
                        category="rejected",
                        content_piece_id=other.piece_id,
                    )
                )

        if kind == "finish":
            # Also note other approved finishes that lost.
            for parent, record in _collect_approved_finishes(versions):
                if record.finish_version_id == finish.finish_version_id:
                    continue
                plan.excluded.append(
                    ExportExclusion(
                        f"{_piece_label(state, parent)} (Studio {record.finish_version_id})",
                        "Superseded by a newer approved Studio finish",
                        category="superseded",
                        content_piece_id=parent.piece_id,
                    )
                )
            item, extra = _build_finish_item(state, version, finish, root=root)
            plan.excluded.extend(extra)
            if item is None:
                continue
            # Parent render media is intentionally not packaged.
            if version.media_files:
                plan.excluded.append(
                    ExportExclusion(
                        f"{_piece_label(state, version)} (parent render media)",
                        "Replaced by approved Studio finish",
                        category="superseded",
                        content_piece_id=version.piece_id,
                    )
                )
            plan.included.append(item)
            if item.summary_kind == "pin" and item.content_piece_id:
                included_pin_pieces.add(item.content_piece_id)
        elif kind == "render":
            item, extra = _build_render_item(state, version, root=root)
            plan.excluded.extend(extra)
            if item is None:
                continue
            plan.included.append(item)
            if item.summary_kind == "pin" and item.content_piece_id:
                included_pin_pieces.add(item.content_piece_id)
        elif kind == "copy":
            pending_copy.append((key, versions))

    # Second pass: copy / metadata
    for key, versions in pending_copy:
        kind, version, finish, reason = _select_canonical(state, versions)
        if kind == "none" or version is None:
            sample = versions[0]
            plan.excluded.append(
                ExportExclusion(
                    _piece_label(state, sample),
                    reason or "Excluded",
                    category="incomplete",
                    content_piece_id=sample.piece_id,
                )
            )
            continue
        for other in versions:
            if other.key == version.key:
                continue
            if other.approval_status == "approved":
                plan.excluded.append(
                    ExportExclusion(
                        _piece_label(state, other),
                        "Superseded by the canonical final version",
                        category="superseded",
                        content_piece_id=other.piece_id,
                    )
                )
        item, extra = _build_copy_item(
            state, version, root=root, included_pin_pieces=included_pin_pieces
        )
        plan.excluded.extend(extra)
        if item is not None:
            plan.included.append(item)

    plan.included, plan.excluded, plan.duplicates_removed = _dedupe_plan(
        plan.included, plan.excluded
    )
    plan.summary = _summarize(plan)
    plan.warnings = list(plan.summary.warning_lines)

    if plan.is_empty:
        plan.validation_status = "blocked"
        plan.blockers.append("Package would contain no publishable items.")
    elif any(
        "publishing copy is incomplete" in w for item in plan.included for w in item.warnings
    ):
        # Incomplete paired copy is a warning with required acknowledgement, not a hard
        # block of the whole package — unless the only content is incomplete copy-only.
        plan.validation_status = "ready_with_warnings"
    else:
        plan.validation_status = "ready"
    return plan


# --- Archive mode (advanced) -------------------------------------------------

def _finish_files_archive(version: RenderVersion) -> list[tuple[str, Path]]:
    from studio.versions import resolve_finish_outputs

    files: list[tuple[str, Path]] = []
    for record in finish_records_for_version(version):
        for path in resolve_finish_outputs(version.folder, record):
            files.append((record.finish_version_id, path))
    return files


def build_archive_plan(state: CampaignState) -> ExportPlan:
    root = f"{_campaign_slug(state)}_archive-package"
    plan = ExportPlan(mode=ARCHIVE_MODE, include_metadata=True, root_folder=root)
    for version in state.versions:
        files = version.all_files(include_metadata=True)
        finish_files = _finish_files_archive(version)
        label = _piece_label(state, version)
        if not files and not finish_files:
            plan.excluded.append(ExportExclusion(label, "No files found on disk"))
            continue
        package_files: list[PackageFile] = []
        prefix = "/".join(
            [
                root,
                version.template_id,
                *([version.piece_id] if version.piece_id else []),
                f"v{version.version}",
            ]
        )
        for path in files:
            package_files.append(
                PackageFile(
                    source=path,
                    archive_name=f"{prefix}/{path.name}",
                    role="support" if path.suffix.lower() in COPY_SUFFIXES else "media",
                    file_hash=file_sha256(path) if path.is_file() else "",
                    file_size=path.stat().st_size if path.is_file() else 0,
                )
            )
        for finish_id, path in finish_files:
            package_files.append(
                PackageFile(
                    source=path,
                    archive_name=f"{prefix}/studio/{finish_id}/{path.name}",
                    role="media",
                    file_hash=file_sha256(path) if path.is_file() else "",
                    file_size=path.stat().st_size if path.is_file() else 0,
                )
            )
        plan.included.append(
            ExportItem(
                label=label,
                file_count=len(package_files),
                total_bytes=sum(f.file_size for f in package_files),
                display_name=_piece_title(state, version),
                platform=_platform_for(version.template_id),
                content_type=version.display_name,
                content_piece_id=version.piece_id,
                media_type=version.kind,
                approval_status=version.approval_status,
                approved_at=version.reviewed_at,
                render_version_id=_render_version_token(version.version),
                package_files=package_files,
                finish_files=finish_files,
                version=version,
                summary_kind=version.kind,
            )
        )
    plan.summary = _summarize(plan)
    if plan.is_empty:
        plan.validation_status = "blocked"
        plan.blockers.append("Archive would contain no files.")
    else:
        plan.validation_status = "ready"
        plan.warnings.append("This is an Archive Package, not a Publishing Package.")
    return plan


def build_plan(
    state: CampaignState,
    *,
    mode: str,
    selected_keys: set[str] | None = None,
) -> ExportPlan:
    """Decide what a package would contain, without writing anything."""
    resolved = normalize_mode(mode)
    if resolved == ARCHIVE_MODE:
        return build_archive_plan(state)
    if resolved == PUBLISHING_MODE:
        return build_publishing_plan(state)

    # Legacy latest / selected — keep functional for any residual callers, but
    # route through a thin approved-style filter without publishing validation.
    plan = ExportPlan(mode=resolved, include_metadata=False)
    selected_keys = selected_keys or set()
    latest_by_group: dict[tuple[str, str | None], RenderVersion] = {}
    for version in state.versions:
        group = (version.template_id, version.piece_id)
        current = latest_by_group.get(group)
        if current is None or version.version > current.version:
            latest_by_group[group] = version
    latest_keys = {v.key for v in latest_by_group.values()}

    for version in state.versions:
        label = _piece_label(state, version)
        if resolved == "selected" and version.key not in selected_keys:
            plan.excluded.append(ExportExclusion(label, "Not selected"))
            continue
        if resolved == "latest" and version.key not in latest_keys:
            plan.excluded.append(ExportExclusion(label, "Superseded by a newer version"))
            continue
        item, extra = _build_render_item(
            state, version, root=f"{_campaign_slug(state)}_export"
        ) if version.kind != "copy" else _build_copy_item(
            state,
            version,
            root=f"{_campaign_slug(state)}_export",
            included_pin_pieces=set(),
        )
        plan.excluded.extend(extra)
        if item is not None:
            plan.included.append(item)
        elif not extra:
            plan.excluded.append(ExportExclusion(label, "No files found on disk"))
    plan.summary = _summarize(plan)
    plan.validation_status = "blocked" if plan.is_empty else "ready"
    return plan


# --- Manifest / README / ZIP -------------------------------------------------

def _archive_name(state: CampaignState, mode: str) -> str:
    campaign = state.path.name if state.path else "campaign"
    resolved = normalize_mode(mode)
    return f"{campaign}_{timestamp_stamp()}_{resolved}.zip"


def _readme(state: CampaignState, plan: ExportPlan, created_at: str) -> str:
    lines = [
        f"Campaign: {state.name}",
        f"Export date: {created_at}",
        f"Package type: {MODE_LABELS.get(plan.mode, plan.mode)}",
        "",
        "Included",
        "",
    ]
    if plan.summary.included_lines:
        for line in plan.summary.included_lines:
            lines.append(f"- {line}")
    else:
        for item in plan.included:
            lines.append(f"- {item.label} ({item.platform})")
    lines.append("")
    lines.append("Excluded")
    lines.append("")
    if plan.excluded:
        for exclusion in plan.excluded:
            lines.append(f"- {exclusion.label} because {exclusion.reason}")
    else:
        lines.append("- Nothing excluded")
    if plan.warnings or plan.summary.warning_lines:
        lines.extend(["", "Warnings / manual steps", ""])
        for warning in plan.summary.warning_lines or plan.warnings:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "Notes",
            "",
            "- Historical versions remain in BettyOS and are not included in this package.",
            "- Use Archive Package if you need approved version history.",
            "",
        ]
    )
    return "\n".join(lines)


def _manifest_payload(state: CampaignState, plan: ExportPlan, created_at: str) -> dict:
    deliverables = []
    for item in plan.included:
        deliverables.append(
            {
                "content_piece_id": item.content_piece_id,
                "display_name": item.display_name or item.label,
                "platform": item.platform,
                "content_type": item.content_type,
                "exported_filenames": [f.archive_name for f in item.package_files],
                "media_type": item.media_type,
                "approval_status": item.approval_status,
                "approved_at": item.approved_at,
                "render_version_id": item.render_version_id,
                "finish_version_id": item.finish_version_id,
                "parent_render_version_id": item.parent_render_version_id,
                "file_hash": item.file_hash,
                "file_size": item.total_bytes,
                "dimensions": item.dimensions,
                "duration": item.duration,
                "paired_caption": item.paired_caption,
                "paired_metadata": item.paired_metadata,
                "destination_url": item.destination_url,
                "tracking_parameters": item.tracking_parameters,
                "warnings": item.warnings,
            }
        )
    return {
        "package_type": MODE_LABELS.get(plan.mode, plan.mode),
        "mode": plan.mode,
        "campaign": state.name,
        "goal": state.goal,
        "created_at": created_at,
        "validation_status": plan.validation_status,
        "warnings": plan.warnings,
        "blockers": plan.blockers,
        "summary": asdict(plan.summary),
        "deliverables": deliverables,
        "excluded": [
            {
                "label": e.label,
                "reason": e.reason,
                "category": e.category,
                "content_piece_id": e.content_piece_id,
            }
            for e in plan.excluded
        ],
        "duplicates_removed": [asdict(d) for d in plan.duplicates_removed],
        "technical": {
            "root_folder": plan.root_folder,
            "file_count": plan.file_count,
            "total_bytes": plan.total_bytes,
            "include_metadata": plan.include_metadata,
        },
    }


def create_export_package(
    state: CampaignState,
    *,
    mode: str,
    selected_keys: set[str] | None = None,
    acknowledge_warnings: bool = False,
) -> ExportResult:
    """Write the ZIP. Returns a result the UI can report honestly."""
    if state.path is None:
        return ExportResult(False, "No campaign is open.")

    plan = build_plan(state, mode=mode, selected_keys=selected_keys)
    if plan.is_empty or plan.is_blocked:
        return ExportResult(
            False,
            "Nothing to export." if plan.is_empty else "Publishing package is blocked.",
            excluded=plan.excluded,
            detail="; ".join(plan.blockers) or "No publishable deliverable matched.",
            validation_status=plan.validation_status,
            warnings=plan.warnings,
            summary=plan.summary,
        )

    if plan.validation_status == "ready_with_warnings" and not acknowledge_warnings:
        return ExportResult(
            False,
            "Publishing package has warnings that must be acknowledged.",
            excluded=plan.excluded,
            detail="Review exclusions and incomplete copy before creating the package.",
            validation_status=plan.validation_status,
            warnings=plan.warnings,
            summary=plan.summary,
        )

    created_at = datetime.now().strftime("%-d %b %Y, %H:%M")
    target_dir = exports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _archive_name(state, mode)

    written = 0
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in plan.included:
                for pkg in item.package_files:
                    if not pkg.source.is_file():
                        continue
                    archive.write(pkg.source, pkg.archive_name)
                    written += 1
            readme_name = f"{plan.root_folder}/README.txt"
            manifest_name = f"{plan.root_folder}/manifest.json"
            archive.writestr(readme_name, _readme(state, plan, created_at))
            archive.writestr(
                manifest_name,
                json.dumps(_manifest_payload(state, plan, created_at), indent=2) + "\n",
            )
            written += 2
    except (OSError, zipfile.BadZipFile) as exc:
        target.unlink(missing_ok=True)
        return ExportResult(
            False,
            "Could not create the export package.",
            excluded=plan.excluded,
            detail=str(exc),
            validation_status=plan.validation_status,
            warnings=plan.warnings,
            summary=plan.summary,
        )

    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return ExportResult(
            False,
            "The export package was empty after writing.",
            excluded=plan.excluded,
            validation_status=plan.validation_status,
            warnings=plan.warnings,
            summary=plan.summary,
        )

    return ExportResult(
        ok=True,
        message="Publishing package created."
        if normalize_mode(mode) == PUBLISHING_MODE
        else "Archive package created.",
        path=target,
        file_count=written,
        total_bytes=target.stat().st_size,
        included=[item.label for item in plan.included],
        excluded=plan.excluded,
        created_at=created_at,
        validation_status=plan.validation_status,
        warnings=plan.warnings,
        summary=plan.summary,
    )


def list_existing_packages(state: CampaignState) -> list[tuple[Path, str, str]]:
    """Previously created packages for this campaign: (path, created, size)."""
    folder = exports_dir()
    if not folder.is_dir() or state.path is None:
        return []
    rows: list[tuple[Path, str, str]] = []
    for path in sorted(folder.glob(f"{state.path.name}*.zip"), reverse=True):
        stat = path.stat()
        rows.append(
            (
                path,
                datetime.fromtimestamp(stat.st_mtime).strftime("%-d %b %Y, %H:%M"),
                human_size(stat.st_size),
            )
        )
    return rows
