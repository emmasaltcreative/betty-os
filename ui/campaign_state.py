"""One computed view of a campaign, shared by every page.

This module answers the questions the interface keeps asking: what stage is
this campaign in, which content pieces are blocked, which render versions exist,
what has been approved, and what should happen next. Pages read from here rather
than re-deriving state, so the sidebar, Home, and each workflow page always
agree.

Read-only. Nothing in this module writes to disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.common import OUTPUTS_DIR
from src.package_parse import extract_campaign_goal
from src.templates.models import ContentPieceRecord, TemplateRecord
from src.templates.registry import TEMPLATE_TO_LEGACY_FOLDER, templates_by_id
from ui.capability import (
    canonical_template_for_folder,
    last_export_at,
    last_review_at,
    parse_iso,
    renderability,
    version_in_filename,
)

MEDIA_SUFFIXES = {".mp4", ".mov", ".png", ".jpg", ".jpeg"}
SUPPORT_DOC_SUFFIXES = {".md", ".txt"}
METADATA_NAMES = {"versions.json", "migration_marker.json", "approvals.json"}

# Folders inside a campaign that are bookkeeping, not render output.
NON_RENDER_ENTRIES = {"approvals.json", "approval_summary.md", "migration_report.json",
                      "render_queue_summary.md", "exports", "studio"}


# --- Render versions --------------------------------------------------------

@dataclass
class RenderVersion:
    """One reviewable, approvable unit: a template output at a version."""

    template_id: str
    display_name: str
    folder: Path
    piece_id: str | None
    version: int
    kind: str  # "video" | "image" | "copy"
    primary_path: Path | None
    media_files: list[Path] = field(default_factory=list)
    support_files: list[Path] = field(default_factory=list)
    metadata_files: list[Path] = field(default_factory=list)
    draft_files: list[Path] = field(default_factory=list)
    caption: str = ""
    created_at: str = ""
    approval_status: str = "awaiting_review"
    approval_note: str = ""
    reviewed_at: str | None = None
    addressed_recommendation_ids: list[str] = field(default_factory=list)
    is_latest: bool = False

    @property
    def key(self) -> str:
        piece = self.piece_id or "-"
        return f"{self.template_id}|{piece}|v{self.version}"

    @property
    def label(self) -> str:
        return f"{self.display_name} — version {self.version}"

    def all_files(self, *, include_metadata: bool = False) -> list[Path]:
        """Files belonging to this version.

        Pre-versioning drafts and render metadata are held back unless the
        caller asks for everything, so an approved export never ships a draft
        beside the finished file.
        """
        files = [*self.media_files, *self.support_files]
        if include_metadata:
            files = [*files, *self.draft_files, *self.metadata_files]
        return [f for f in files if f.is_file()]

    def total_bytes(self, *, include_metadata: bool = False) -> int:
        return sum(f.stat().st_size for f in self.all_files(include_metadata=include_metadata))


@dataclass
class PieceState:
    record: ContentPieceRecord
    template_id: str
    template: TemplateRecord | None
    template_status: str
    can_render: bool
    blocked_reason: str
    missing_inputs: list[str]
    versions: list[RenderVersion]
    status_key: str
    assignment_is_override: bool = False

    @property
    def latest_version(self) -> RenderVersion | None:
        return self.versions[-1] if self.versions else None

    @property
    def template_name(self) -> str:
        return self.template.display_name if self.template else self.template_id


@dataclass
class NextStep:
    label: str
    destination: str
    reason: str
    tab: str | None = None
    actionable: bool = True


@dataclass
class WorkflowStep:
    key: str
    label: str
    state: str  # "complete" | "current" | "upcoming" | "blocked"


@dataclass
class CampaignState:
    path: Path | None
    name: str
    goal: str
    package_path: Path | None
    package_name: str
    platforms: list[str]
    pieces: list[PieceState]
    versions: list[RenderVersion]
    stage: str
    blockers: list[str]
    next_step: NextStep
    steps: list[WorkflowStep]
    activity: list[str]
    created_at: str
    updated_at: str
    revision_counts: dict[str, int]
    review_is_current: bool
    has_review: bool
    export_count: int

    @property
    def exists(self) -> bool:
        return self.path is not None

    @property
    def counts(self) -> dict[str, int]:
        by_status: dict[str, int] = {}
        for piece in self.pieces:
            by_status[piece.status_key] = by_status.get(piece.status_key, 0) + 1
        approvals = {"approved": 0, "needs_revision": 0, "rejected": 0, "awaiting_review": 0}
        for version in self.versions:
            approvals[version.approval_status] = approvals.get(version.approval_status, 0) + 1
        return {
            "pieces": len(self.pieces),
            "ready_to_render": by_status.get("ready_to_render", 0),
            "missing_inputs": by_status.get("missing_inputs", 0),
            "unsupported": by_status.get("unsupported", 0),
            "rendered": sum(1 for p in self.pieces if p.versions),
            "renders": len(self.versions),
            "needs_revision": approvals["needs_revision"],
            "awaiting_approval": approvals["awaiting_review"],
            "approved": approvals["approved"],
            "rejected": approvals["rejected"],
        }

    @property
    def approved_versions(self) -> list[RenderVersion]:
        return [v for v in self.versions if v.approval_status == "approved"]

    def piece_title(self, version: RenderVersion) -> str | None:
        """The content piece a render belongs to, by its readable title."""
        if not version.piece_id:
            return None
        for piece in self.pieces:
            if piece.record.piece_id == version.piece_id:
                return piece.record.title
        return None

    def describe(self, version: RenderVersion) -> str:
        """`Editorial Carousel — version 1 · Still life, reading hour`."""
        title = self.piece_title(version)
        return f"{version.label} · {title}" if title else version.label

    @property
    def progress_fraction(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.state == "complete")
        return done / len(self.steps)


# --- Campaign discovery -----------------------------------------------------

@dataclass
class CampaignSummary:
    path: Path
    name: str
    created_at: str
    updated_at: str


def _fmt_stamp(moment: datetime | None) -> str:
    return moment.strftime("%-d %b %Y, %H:%M") if moment else "—"


def _folder_stamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def _display_name_from_folder(name: str) -> str:
    """`2026-07-27_191825_campaign` reads as `Campaign — 27 Jul 2026, 19:18`."""
    stem = name.removesuffix("_campaign")
    date_part, _, time_part = stem.partition("_")
    # Pick the format by digit count: strptime would read "1916" as 19:01:06.
    fmt = {4: "%Y-%m-%d_%H%M", 6: "%Y-%m-%d_%H%M%S"}.get(len(time_part))
    if fmt:
        try:
            moment = datetime.strptime(stem, fmt)
        except ValueError:
            moment = None
        if moment is not None:
            return f"Campaign — {moment.strftime('%-d %b %Y, %H:%M')}"
    return name.replace("_", " ").title()


def list_campaigns() -> list[CampaignSummary]:
    if not OUTPUTS_DIR.is_dir():
        return []
    summaries: list[CampaignSummary] = []
    for path in sorted((p for p in OUTPUTS_DIR.glob("*_campaign") if p.is_dir()), reverse=True):
        if is_archived(path):
            continue
        summaries.append(
            CampaignSummary(
                path=path,
                name=_display_name_from_folder(path.name),
                created_at=_fmt_stamp(datetime.fromtimestamp(path.stat().st_ctime)),
                updated_at=_fmt_stamp(_folder_stamp(path)),
            )
        )
    return summaries


def archive_marker(campaign_dir: Path) -> Path:
    return campaign_dir / ".archived"


def is_archived(campaign_dir: Path) -> bool:
    return archive_marker(campaign_dir).exists()


def list_archived_campaigns() -> list[CampaignSummary]:
    if not OUTPUTS_DIR.is_dir():
        return []
    return [
        CampaignSummary(
            path=path,
            name=_display_name_from_folder(path.name),
            created_at=_fmt_stamp(datetime.fromtimestamp(path.stat().st_ctime)),
            updated_at=_fmt_stamp(_folder_stamp(path)),
        )
        for path in sorted((p for p in OUTPUTS_DIR.glob("*_campaign") if p.is_dir()), reverse=True)
        if is_archived(path)
    ]


def campaign_display_name(campaign_dir: Path | None) -> str:
    return _display_name_from_folder(campaign_dir.name) if campaign_dir else "No campaign"


def list_content_packages() -> list[Path]:
    return sorted(OUTPUTS_DIR.glob("*_content_package.md"), reverse=True)


def package_for_campaign(campaign_dir: Path | None) -> Path | None:
    """The package a campaign was rendered from, else the most recent one."""
    if campaign_dir is not None:
        for settings_path in sorted(campaign_dir.glob("*/render_settings.json")):
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            name = (settings or {}).get("content_package")
            if name:
                candidate = OUTPUTS_DIR / str(name)
                if candidate.is_file():
                    return candidate
    packages = list_content_packages()
    return packages[0] if packages else None


# --- Render version discovery -----------------------------------------------

def _classify_kind(module: str) -> str:
    if module == "video":
        return "video"
    if module == "copy":
        return "copy"
    return "image"


def _render_folders(campaign_dir: Path) -> list[tuple[str, Path]]:
    """Canonical (template_id, folder) pairs, hiding migration duplicates.

    Migration copies `ritual_reel` to `cinematic_multi_clip_reel` rather than
    moving it, so both folders hold the same files. The legacy folder must stay
    on disk — revision execution reads it — but it is not shown twice.
    """
    present = {p.name for p in campaign_dir.iterdir() if p.is_dir()}
    pairs: list[tuple[str, Path]] = []
    for name in sorted(present):
        if name in NON_RENDER_ENTRIES or name.startswith("."):
            continue
        template_id = canonical_template_for_folder(name)
        legacy_twin = TEMPLATE_TO_LEGACY_FOLDER.get(template_id)
        is_legacy = name != template_id
        if is_legacy and template_id in present:
            continue
        if not is_legacy and legacy_twin and legacy_twin in present:
            # Canonical folder wins; prefer whichever actually holds media.
            canonical_dir = campaign_dir / name
            if not _has_media(canonical_dir) and _has_media(campaign_dir / legacy_twin):
                pairs.append((template_id, campaign_dir / legacy_twin))
                continue
        pairs.append((template_id, campaign_dir / name))
    return pairs


def _has_media(folder: Path) -> bool:
    from studio.paths import is_under_studio

    return any(
        p.is_file()
        and p.suffix.lower() in MEDIA_SUFFIXES
        and not is_under_studio(p)
        for p in folder.rglob("*")
    )


def _piece_scoped_dirs(folder: Path) -> list[Path]:
    return [p for p in sorted(folder.iterdir()) if p.is_dir() and p.name.startswith("piece_")]


def _group_versions(
    output_dir: Path,
    *,
    template_id: str,
    display_name: str,
    kind: str,
    piece_id: str | None,
) -> list[RenderVersion]:
    versioned: dict[int, list[Path]] = {}
    unversioned: list[Path] = []
    metadata: list[Path] = []

    for path in sorted(output_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            metadata.append(path)
            continue
        if suffix not in MEDIA_SUFFIXES and suffix not in SUPPORT_DOC_SUFFIXES:
            continue
        version = version_in_filename(path.name)
        if version is None:
            unversioned.append(path)
        else:
            versioned.setdefault(version, []).append(path)

    if not versioned:
        # A pre-versioning draft still deserves one reviewable unit.
        drafts = [p for p in unversioned if p.suffix.lower() in MEDIA_SUFFIXES]
        if not drafts:
            return []
        versioned = {1: drafts}
        unversioned = [p for p in unversioned if p not in drafts]

    manifest_created = _manifest_timestamps(metadata)
    highest = max(versioned)
    versions: list[RenderVersion] = []
    for number in sorted(versioned):
        media = [p for p in versioned[number] if p.suffix.lower() in MEDIA_SUFFIXES]
        docs = [p for p in versioned[number] if p.suffix.lower() in SUPPORT_DOC_SUFFIXES]
        drafts: list[Path] = []
        if not docs:
            # An unversioned caption is shared by every version that has not had
            # one written for it. Once a revision writes `caption_v3.md`, that
            # version uses its own and the others keep the shared one.
            docs = [p for p in unversioned if p.suffix.lower() in SUPPORT_DOC_SUFFIXES]
        if number == highest:
            # Unversioned media is a leftover draft, tracked separately so an
            # export never ships it beside the finished file.
            drafts = [
                p
                for p in unversioned
                if p.suffix.lower() in MEDIA_SUFFIXES and p not in media
            ]
        primary = _pick_primary(media or drafts, docs, kind)
        created = manifest_created.get(number) or _iso(_newest_file_stamp(media + docs))
        versions.append(
            RenderVersion(
                template_id=template_id,
                display_name=display_name,
                folder=output_dir,
                piece_id=piece_id,
                version=number,
                kind=kind,
                primary_path=primary,
                media_files=sorted(set(media)),
                support_files=sorted(set(docs)),
                draft_files=sorted(set(drafts)),
                metadata_files=sorted(
                    p for p in metadata if _metadata_belongs(p, number, highest)
                ),
                caption=_read_caption(docs),
                created_at=created,
                is_latest=number == highest,
            )
        )
    return versions


def _metadata_belongs(path: Path, number: int, highest: int) -> bool:
    version = version_in_filename(path.name)
    if version is not None:
        return version == number
    return number == highest


def _manifest_timestamps(metadata: list[Path]) -> dict[int, str]:
    stamps: dict[int, str] = {}
    for path in metadata:
        if not path.name.startswith("render_manifest_v"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        version = data.get("version")
        created = data.get("created_at")
        if isinstance(version, int) and isinstance(created, str):
            stamps[version] = created
    return stamps


def _newest_file_stamp(paths: list[Path]) -> datetime | None:
    stamps = [datetime.fromtimestamp(p.stat().st_mtime) for p in paths if p.is_file()]
    return max(stamps) if stamps else None


def _iso(moment: datetime | None) -> str:
    return moment.isoformat(timespec="seconds") if moment else ""


def _pick_primary(media: list[Path], docs: list[Path], kind: str) -> Path | None:
    if kind == "copy":
        return docs[0] if docs else (media[0] if media else None)
    videos = [p for p in media if p.suffix.lower() in {".mp4", ".mov"}]
    if videos:
        # Prefer a versioned file over a leftover draft.
        versioned = [p for p in videos if version_in_filename(p.name) is not None]
        return sorted(versioned or videos)[0]
    images = [p for p in media if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if images:
        return sorted(images)[0]
    return docs[0] if docs else None


def _read_caption(docs: list[Path]) -> str:
    for path in docs:
        if "caption" in path.name.lower():
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
    return ""


def discover_render_versions(campaign_dir: Path | None) -> list[RenderVersion]:
    if campaign_dir is None or not campaign_dir.is_dir():
        return []
    registry = templates_by_id()
    versions: list[RenderVersion] = []
    for template_id, folder in _render_folders(campaign_dir):
        template = registry.get(template_id)
        display_name = template.display_name if template else template_id.replace("_", " ").title()
        kind = _classify_kind(template.renderer_module if template else "")
        piece_dirs = _piece_scoped_dirs(folder)
        if piece_dirs:
            for piece_dir in piece_dirs:
                versions.extend(
                    _group_versions(
                        piece_dir,
                        template_id=template_id,
                        display_name=display_name,
                        kind=kind,
                        piece_id=piece_dir.name,
                    )
                )
        else:
            versions.extend(
                _group_versions(
                    folder,
                    template_id=template_id,
                    display_name=display_name,
                    kind=kind,
                    piece_id=None,
                )
            )
    return versions


# --- Approvals --------------------------------------------------------------

def approval_scope(file_path: str) -> tuple[str, str | None]:
    """Canonical (template_id, piece_id) a stored approval record refers to."""
    parts = [p for p in str(file_path).split("/") if p]
    if not parts:
        return "", None
    template_id = canonical_template_for_folder(parts[0])
    piece_id = parts[1] if len(parts) > 1 and parts[1].startswith("piece_") else None
    return template_id, piece_id


def _version_number(render_version_id: object) -> int:
    text = str(render_version_id or "v1").lstrip("vV")
    try:
        return int(text)
    except ValueError:
        return 1


def _aggregate(statuses: set[str]) -> str:
    if "rejected" in statuses:
        return "rejected"
    if "needs_revision" in statuses:
        return "needs_revision"
    if statuses and statuses <= {"approved"}:
        return "approved"
    return "awaiting_review"


def apply_approvals(campaign_dir: Path, versions: list[RenderVersion]) -> None:
    """Fold stored per-file approval records onto each render version."""
    from src.templates.approvals_store import load_campaign_approvals

    data = load_campaign_approvals(campaign_dir)
    grouped: dict[tuple[str, str | None, int], list[dict]] = {}
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        template_id, piece_id = approval_scope(str(item.get("file_path") or ""))
        if not template_id:
            continue
        key = (template_id, piece_id, _version_number(item.get("render_version_id")))
        grouped.setdefault(key, []).append(item)

    for version in versions:
        records = grouped.get((version.template_id, version.piece_id, version.version)) or []
        if not records:
            continue
        version.approval_status = _aggregate({str(r.get("status") or "") for r in records})
        notes = [str(r.get("note") or "").strip() for r in records]
        version.approval_note = next((n for n in notes if n), "")
        stamps = [r.get("reviewed_at") for r in records if r.get("reviewed_at")]
        version.reviewed_at = str(stamps[0]) if stamps else None


def apply_version_manifests(versions: list[RenderVersion]) -> None:
    """Attach `versions.json` provenance where a folder tracks it."""
    from review.versioning import load_versions

    cache: dict[Path, dict] = {}
    for version in versions:
        if version.folder not in cache:
            cache[version.folder] = load_versions(version.folder)
        entries = cache[version.folder].get("versions") or []
        for entry in entries:
            if int(entry.get("version") or 0) != version.version:
                continue
            version.addressed_recommendation_ids = [
                str(x) for x in entry.get("addressed_recommendation_ids") or []
            ]
            if not version.created_at:
                version.created_at = str(entry.get("created_at") or "")
            break


# --- Studio finished versions ----------------------------------------------

# A finished version belongs to the one render version it was built from.
# Studio records that parent as `render_vNNN`; the interface counts versions as
# integers, so every reader crosses the two through these helpers rather than
# formatting the id again and risking a mismatch.

def finish_records_for_version(version: RenderVersion) -> list["FinishRecord"]:  # noqa: F821
    """Studio finished versions built from this exact render version."""
    from studio.versions import list_finish_records, render_version_id

    parent = render_version_id(version.version)
    try:
        records = list_finish_records(version.folder)
    except OSError:
        return []
    return [
        record
        for record in records
        if record.parent_render_version_id == parent and record.status != "failed"
    ]


def finished_versions_sent_to_review(
    versions: list[RenderVersion],
) -> list[tuple[RenderVersion, "FinishRecord"]]:  # noqa: F821
    """Finished versions Studio has handed to Review, newest first.

    Only versions that went through Send to Review appear here, so a draft
    finish nobody submitted never reaches a reviewer.
    """
    pairs: list[tuple[RenderVersion, "FinishRecord"]] = []  # noqa: F821
    for version in versions:
        for record in finish_records_for_version(version):
            if record.status == "ready_for_review":
                pairs.append((version, record))
    pairs.sort(key=lambda pair: pair[1].updated_at or "", reverse=True)
    return pairs


def approved_finish_records_for_version(
    version: RenderVersion,
) -> list["FinishRecord"]:  # noqa: F821
    """Finished versions a person has signed off, so Export can ship them."""
    return [
        record
        for record in finish_records_for_version(version)
        if record.approval_status == "approved"
    ]


# --- Content pieces ---------------------------------------------------------

def _missing_inputs(record: ContentPieceRecord) -> list[str]:
    from renderers.primitives import resolve_media_path

    missing: list[str] = []
    if not record.source_assets:
        missing.append("No source media selected")
    for rel in record.source_assets:
        if not resolve_media_path(rel).exists():
            missing.append(f"Missing file: {Path(rel).name}")
    return missing


def _piece_status(
    *,
    can_render: bool,
    missing: list[str],
    versions: list[RenderVersion],
) -> str:
    if versions:
        # A piece can have output from more than one template. Take the most
        # recent version per template and let the weakest decision win, so a
        # piece is never reported as finished while part of it needs work.
        latest_per_template: dict[str, RenderVersion] = {}
        for version in versions:
            current = latest_per_template.get(version.template_id)
            if current is None or version.version > current.version:
                latest_per_template[version.template_id] = version
        statuses = {v.approval_status for v in latest_per_template.values()}
        if "needs_revision" in statuses:
            return "needs_revision"
        if "rejected" in statuses:
            return "rejected"
        if statuses <= {"approved"}:
            return "approved"
        return "awaiting_approval"
    if not can_render:
        return "unsupported"
    if missing:
        return "missing_inputs"
    return "ready_to_render"


def build_piece_states(
    package_path: Path | None,
    versions: list[RenderVersion],
) -> list[PieceState]:
    if package_path is None or not package_path.is_file():
        return []
    from src.templates.assignments import ensure_assignments_for_pieces, load_assignments
    from src.templates.pieces import load_package_pieces
    from ui.capability import effective_status

    records = load_package_pieces(package_path)
    ensure_assignments_for_pieces(package_path, records)
    saved = (load_assignments(package_path).get("pieces") or {})
    registry = templates_by_id()

    by_piece: dict[str, list[RenderVersion]] = {}
    by_template: dict[str, list[RenderVersion]] = {}
    for version in versions:
        if version.piece_id:
            by_piece.setdefault(version.piece_id, []).append(version)
        else:
            by_template.setdefault(version.template_id, []).append(version)

    claimed_templates: set[str] = set()
    states: list[PieceState] = []
    for record in records:
        raw = saved.get(record.piece_id) or {}
        template_id = str(raw.get("template_id") or "")
        template = registry.get(template_id)
        registry_status = template.renderer_status if template else "planned"
        module = template.renderer_module if template else ""
        render_check = renderability(template_id, registry_status, module)
        missing = _missing_inputs(record)

        piece_versions = sorted(
            by_piece.get(record.piece_id, []), key=lambda v: (v.template_id, v.version)
        )
        if not piece_versions and template_id not in claimed_templates:
            # Video renders are stored per template, not per piece.
            flat = sorted(by_template.get(template_id, []), key=lambda v: v.version)
            if flat:
                claimed_templates.add(template_id)
                piece_versions = flat

        states.append(
            PieceState(
                record=record,
                template_id=template_id,
                template=template,
                template_status=effective_status(template_id, registry_status),
                can_render=render_check.can_render,
                blocked_reason=render_check.reason,
                missing_inputs=missing,
                versions=piece_versions,
                status_key=_piece_status(
                    can_render=render_check.can_render,
                    missing=missing,
                    versions=piece_versions,
                ),
                assignment_is_override=bool(raw.get("override")),
            )
        )
    return states


# --- Revisions --------------------------------------------------------------

def revision_counts_for(campaign_dir: Path | None) -> dict[str, int]:
    """Revision tallies for this campaign, from `revisions/revision_requests.json`."""
    from services.revision_store import STATUSES, counts as store_counts

    if campaign_dir is None:
        tally = {status: 0 for status in STATUSES}
        tally.update({"awaiting_decision": 0, "ready_to_apply": 0, "needs_human": 0})
        return tally
    return store_counts(campaign_dir)


# --- Stage, blockers, next step --------------------------------------------

def _review_is_current(versions: list[RenderVersion]) -> bool:
    reviewed_at = last_review_at()
    if reviewed_at is None:
        return False
    newest = _newest_file_stamp([v.primary_path for v in versions if v.primary_path])
    if newest is None:
        return True
    return reviewed_at >= newest


def count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _blockers(
    pieces: list[PieceState],
    revisions: dict[str, int],
    *,
    api_configured: bool,
    ffmpeg_ready: bool,
) -> list[str]:
    blockers: list[str] = []
    if not api_configured:
        blockers.append("No API key configured — content generation and review cannot run.")
    unsupported = sum(1 for p in pieces if p.status_key == "unsupported")
    if unsupported:
        verb = "has" if unsupported == 1 else "have"
        blockers.append(
            f"{count_phrase(unsupported, 'content piece')} {verb} no working template."
        )
    incomplete = sum(1 for p in pieces if p.status_key == "missing_inputs")
    if incomplete:
        verb = "is" if incomplete == 1 else "are"
        blockers.append(
            f"{count_phrase(incomplete, 'content piece')} {verb} missing source media."
        )
    needs_video = any(
        p.template is not None and p.template.renderer_module == "video" and p.can_render
        for p in pieces
    )
    if needs_video and not ffmpeg_ready:
        blockers.append("FFmpeg not found — video templates cannot render.")
    waiting = revisions["needs_human"]
    if waiting:
        verb = "is" if waiting == 1 else "are"
        blockers.append(
            f"{count_phrase(waiting, 'revision')} {verb} waiting on something you need to "
            "supply — new footage, a photograph or a missing file."
        )
    if revisions["failed"]:
        blockers.append(
            f"{count_phrase(revisions['failed'], 'revision')} failed to apply. Nothing was changed."
        )
    return blockers


def _next_step(
    *,
    has_campaign: bool,
    pieces: list[PieceState],
    versions: list[RenderVersion],
    review_current: bool,
    revisions: dict[str, int],
    counts: dict[str, int],
) -> NextStep:
    """Legacy next-step helper. Prefer `ui.continue_campaign.resolve_continuation`."""
    if not has_campaign:
        return NextStep(
            "Start a Campaign",
            "Campaigns",
            "Choose or create a campaign to begin.",
        )
    if not pieces:
        return NextStep(
            "Set Campaign Goal",
            "workspace",
            "This campaign has no content plan yet.",
            tab="brief",
        )
    if any(p.status_key == "missing_inputs" for p in pieces) and not versions:
        return NextStep(
            "View Shot List",
            "workspace",
            "Footage is needed before a draft can be created.",
            tab="capture",
        )
    if counts["ready_to_render"]:
        ready = counts["ready_to_render"]
        verb = "is" if ready == 1 else "are"
        return NextStep(
            "Create Best Draft",
            "workspace",
            f"{count_phrase(ready, 'content piece')} {verb} ready to create.",
            tab="create",
        )
    if not versions:
        return NextStep(
            "Create Best Draft",
            "workspace",
            "No drafts exist yet.",
            tab="create",
            actionable=not all(p.status_key in {"unsupported", "missing_inputs"} for p in pieces),
        )
    if not _campaign_has_finish(versions):
        return NextStep(
            "Create Best Draft",
            "workspace",
            "Apply brand finishing and Creative Director Review.",
            tab="create",
        )
    if not review_current:
        return NextStep(
            "Review Draft",
            "workspace",
            "A draft is ready for your judgment.",
            tab="decide",
        )
    if revisions["ready_to_apply"]:
        chosen = revisions["ready_to_apply"]
        verb = "is" if chosen == 1 else "are"
        return NextStep(
            "Apply Revision",
            "workspace",
            f"{count_phrase(chosen, 'requested change')} {verb} ready to apply.",
            tab="decide",
        )
    if revisions["awaiting_decision"]:
        open_count = revisions["awaiting_decision"]
        verb = "is" if open_count == 1 else "are"
        return NextStep(
            "Request Changes",
            "workspace",
            f"{count_phrase(open_count, 'requested change')} {verb} waiting on a decision.",
            tab="decide",
        )
    if counts["awaiting_approval"] or counts["needs_revision"]:
        pending = counts["awaiting_approval"] + counts["needs_revision"]
        verb = "needs" if pending == 1 else "need"
        return NextStep(
            "Approve or Request Changes",
            "workspace",
            f"{count_phrase(pending, 'draft')} {verb} a decision.",
            tab="decide",
        )
    if counts["approved"]:
        approved = counts["approved"]
        verb = "is" if approved == 1 else "are"
        return NextStep(
            "Download Package",
            "workspace",
            f"{count_phrase(approved, 'approved draft')} {verb} ready to deliver.",
            tab="deliver",
        )
    return NextStep(
        "Review Draft",
        "workspace",
        "Nothing is approved yet.",
        tab="decide",
    )


def _campaign_has_finish(versions: list[RenderVersion]) -> bool:
    """True when any render folder has an immutable Studio finished version."""
    from studio.versions import list_finish_version_ids

    seen: set[Path] = set()
    for version in versions:
        folder = version.folder
        if folder in seen:
            continue
        seen.add(folder)
        try:
            if list_finish_version_ids(folder):
                return True
        except OSError:
            continue
    return False


def _steps(
    *,
    has_campaign: bool,
    pieces: list[PieceState],
    versions: list[RenderVersion],
    review_current: bool,
    revisions: dict[str, int],
    counts: dict[str, int],
    export_count: int,
    blockers: list[str],
) -> list[WorkflowStep]:
    """Founder-facing rail: Brief → Plan → Capture → Create → Decide → Deliver."""
    missing = any(p.status_key == "missing_inputs" for p in pieces)
    has_finish = _campaign_has_finish(versions)
    decide_clear = (
        counts["awaiting_approval"] == 0
        and counts["needs_revision"] == 0
        and revisions["awaiting_decision"] == 0
        and revisions["ready_to_apply"] == 0
    )
    complete = {
        "brief": has_campaign,
        "plan": bool(pieces),
        "capture": bool(pieces) and not missing,
        "create": bool(versions) and has_finish and counts["ready_to_render"] == 0,
        "decide": bool(versions) and has_finish and decide_clear and counts["approved"] > 0,
        "deliver": export_count > 0,
    }
    blocked = {
        "capture": missing and not versions,
        "create": bool(pieces)
        and not versions
        and all(p.status_key in {"unsupported", "missing_inputs"} for p in pieces),
        "decide": revisions["needs_human"] > 0
        and revisions["awaiting_decision"] == 0
        and revisions["ready_to_apply"] == 0,
        "deliver": counts["approved"] == 0 and export_count == 0,
    }

    from ui.status import WORKFLOW_STEPS

    # The rail reads left to right, so nothing after the current step may show
    # as complete — a later step being "done" only means it has no work queued.
    order = [key for key, _ in WORKFLOW_STEPS]
    first_open = next((i for i, key in enumerate(order) if not complete.get(key)), len(order))

    steps: list[WorkflowStep] = []
    for index, (key, label) in enumerate(WORKFLOW_STEPS):
        if index < first_open:
            state = "complete"
        elif index == first_open:
            state = "blocked" if blocked.get(key) else "current"
        else:
            state = "upcoming"
        steps.append(WorkflowStep(key=key, label=label, state=state))
    return steps


def _stage(
    *,
    has_campaign: bool,
    pieces: list[PieceState],
    versions: list[RenderVersion],
    review_current: bool,
    revisions: dict[str, int],
    counts: dict[str, int],
    export_count: int,
    steps: list[WorkflowStep],
) -> str:
    if not has_campaign:
        return "planning"
    if any(s.state == "blocked" for s in steps):
        return "blocked"
    if export_count:
        return "exported"
    if not pieces or not versions:
        return "planning" if not pieces else "creating"
    if counts["ready_to_render"]:
        return "creating"
    if not review_current:
        return "reviewing"
    if revisions["awaiting_decision"] or revisions["ready_to_apply"] or revisions["applying"]:
        return "revising"
    if counts["awaiting_approval"] or counts["needs_revision"]:
        return "awaiting_approval"
    if counts["approved"]:
        return "approved"
    return "reviewing"


def _activity(campaign_dir: Path | None, versions: list[RenderVersion]) -> list[str]:
    events: list[tuple[datetime, str]] = []
    for version in versions:
        stamp = _newest_file_stamp([version.primary_path] if version.primary_path else [])
        if stamp:
            events.append((stamp, f"{version.display_name} version {version.version} rendered"))
        reviewed = parse_iso(version.reviewed_at)
        if reviewed:
            events.append(
                (
                    reviewed,
                    f"{version.display_name} version {version.version} marked "
                    f"{version.approval_status.replace('_', ' ')}",
                )
            )
    reviewed = last_review_at()
    if reviewed:
        events.append((reviewed, "Creative Review completed"))
    exported = last_export_at()
    if exported:
        events.append((exported, "Export package created"))
    events.sort(key=lambda item: item[0], reverse=True)
    return [f"{_fmt_stamp(when)} — {what}" for when, what in events[:6]]


def count_exports(campaign_dir: Path | None) -> int:
    from ui.capability import exports_dir

    folder = exports_dir()
    if not folder.is_dir():
        return 0
    prefix = campaign_dir.name if campaign_dir else ""
    return len([p for p in folder.glob(f"{prefix}*.zip") if p.is_file()]) if prefix else 0


# --- Public entry point -----------------------------------------------------

def build_campaign_state(campaign_dir: Path | None) -> CampaignState:
    from ui.data_access import api_key_configured, ffmpeg_available

    package_path = package_for_campaign(campaign_dir)
    versions = discover_render_versions(campaign_dir)
    if campaign_dir is not None and versions:
        apply_approvals(campaign_dir, versions)
        apply_version_manifests(versions)
    pieces = build_piece_states(package_path, versions)

    package_text = ""
    if package_path and package_path.is_file():
        package_text = package_path.read_text(encoding="utf-8")
    goal = extract_campaign_goal(package_text) if package_text else ""

    revisions = revision_counts_for(campaign_dir)
    review_current = _review_is_current(versions)
    export_count = count_exports(campaign_dir)

    state = CampaignState(
        path=campaign_dir,
        name=campaign_display_name(campaign_dir),
        goal=goal or "No goal recorded",
        package_path=package_path,
        package_name=package_path.name if package_path else "",
        platforms=sorted({p.record.platform for p in pieces if p.record.platform}),
        pieces=pieces,
        versions=versions,
        stage="planning",
        blockers=[],
        next_step=NextStep("Open a campaign", "Campaigns", ""),
        steps=[],
        activity=_activity(campaign_dir, versions),
        created_at=_fmt_stamp(
            datetime.fromtimestamp(campaign_dir.stat().st_ctime) if campaign_dir else None
        ),
        updated_at=_fmt_stamp(_folder_stamp(campaign_dir) if campaign_dir else None),
        revision_counts=revisions,
        review_is_current=review_current,
        has_review=last_review_at() is not None,
        export_count=export_count,
    )

    counts = state.counts
    state.blockers = _blockers(
        pieces,
        revisions,
        api_configured=api_key_configured(),
        ffmpeg_ready=ffmpeg_available(),
    )
    state.steps = _steps(
        has_campaign=campaign_dir is not None,
        pieces=pieces,
        versions=versions,
        review_current=review_current,
        revisions=revisions,
        counts=counts,
        export_count=export_count,
        blockers=state.blockers,
    )
    state.next_step = _next_step(
        has_campaign=campaign_dir is not None,
        pieces=pieces,
        versions=versions,
        review_current=review_current,
        revisions=revisions,
        counts=counts,
    )
    state.stage = _stage(
        has_campaign=campaign_dir is not None,
        pieces=pieces,
        versions=versions,
        review_current=review_current,
        revisions=revisions,
        counts=counts,
        export_count=export_count,
        steps=state.steps,
    )
    return state
