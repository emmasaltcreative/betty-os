"""Package finished renders into a downloadable archive.

Export is the last step of the workflow and the only one that had no
implementation. This module reads render versions that already exist on disk
and writes a new ZIP under `outputs/exports/`. It never modifies, moves, or
deletes a render.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.common import timestamp_stamp
from ui.campaign_state import CampaignState, RenderVersion
from ui.capability import exports_dir

MODES: tuple[tuple[str, str, str], ...] = (
    (
        "approved",
        "Approved Only",
        "Every render version you have approved.",
    ),
    (
        "latest",
        "Latest Versions",
        "The newest version of each render, whatever its approval state.",
    ),
    (
        "selected",
        "Selected Assets",
        "Only the render versions you tick below.",
    ),
    (
        "archive",
        "Full Archive",
        "Every version, plus render settings and version history.",
    ),
)

MODE_LABELS = {key: label for key, label, _ in MODES}


@dataclass
class ExportItem:
    version: RenderVersion
    label: str
    file_count: int
    total_bytes: int
    # Studio finished files that ship with this version, as (finish_id, path).
    finish_files: list[tuple[str, Path]] = field(default_factory=list)


@dataclass
class ExportExclusion:
    label: str
    reason: str


@dataclass
class ExportPlan:
    mode: str
    included: list[ExportItem] = field(default_factory=list)
    excluded: list[ExportExclusion] = field(default_factory=list)
    include_metadata: bool = False

    @property
    def file_count(self) -> int:
        return sum(item.file_count for item in self.included)

    @property
    def total_bytes(self) -> int:
        return sum(item.total_bytes for item in self.included)

    @property
    def is_empty(self) -> bool:
        return not self.included


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


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _piece_label(state: CampaignState, version: RenderVersion) -> str:
    """Name a render the way the user named its content piece."""
    return state.describe(version)


def _exclusion_reason(version: RenderVersion, mode: str, latest_keys: set[str]) -> str | None:
    if mode == "approved":
        if version.approval_status == "approved":
            return None
        if version.approval_status == "awaiting_review":
            return "Not approved yet"
        if version.approval_status == "needs_revision":
            return "Marked as needing revision"
        if version.approval_status == "rejected":
            return "Rejected"
        return "Not approved"
    if mode == "latest":
        return None if version.key in latest_keys else "Superseded by a newer version"
    return None


def _finish_files(version: RenderVersion, mode: str) -> list[tuple[str, Path]]:
    """Studio finished files that belong in the package.

    A finished version is what actually gets published, so an approved one has
    to travel with the render it was built from. Only signed-off finishes ship;
    the full archive additionally carries the ones still awaiting a decision.
    """
    from studio.versions import resolve_finish_outputs
    from ui.campaign_state import (
        approved_finish_records_for_version,
        finish_records_for_version,
    )

    records = (
        finish_records_for_version(version)
        if mode == "archive"
        else approved_finish_records_for_version(version)
    )
    files: list[tuple[str, Path]] = []
    for record in records:
        for path in resolve_finish_outputs(version.folder, record):
            files.append((record.finish_version_id, path))
    return files


def build_plan(
    state: CampaignState,
    *,
    mode: str,
    selected_keys: set[str] | None = None,
) -> ExportPlan:
    """Decide what a package would contain, without writing anything."""
    plan = ExportPlan(mode=mode, include_metadata=mode == "archive")
    selected_keys = selected_keys or set()

    latest_by_group: dict[tuple[str, str | None], RenderVersion] = {}
    for version in state.versions:
        group = (version.template_id, version.piece_id)
        current = latest_by_group.get(group)
        if current is None or version.version > current.version:
            latest_by_group[group] = version
    latest_keys = {v.key for v in latest_by_group.values()}

    for version in state.versions:
        files = version.all_files(include_metadata=plan.include_metadata)
        label = _piece_label(state, version)
        if mode == "selected":
            if version.key not in selected_keys:
                plan.excluded.append(ExportExclusion(label, "Not selected"))
                continue
        else:
            reason = _exclusion_reason(version, mode, latest_keys)
            if reason:
                plan.excluded.append(ExportExclusion(label, reason))
                continue
        finish_files = _finish_files(version, mode)
        if not files and not finish_files:
            plan.excluded.append(ExportExclusion(label, "No files found on disk"))
            continue
        plan.included.append(
            ExportItem(
                version=version,
                label=label,
                file_count=len(files) + len(finish_files),
                total_bytes=(
                    sum(f.stat().st_size for f in files)
                    + sum(p.stat().st_size for _, p in finish_files)
                ),
                finish_files=finish_files,
            )
        )
    return plan


def _archive_name(state: CampaignState, mode: str) -> str:
    campaign = state.path.name if state.path else "campaign"
    return f"{campaign}_{timestamp_stamp()}_{mode}.zip"


def _version_prefix(version: RenderVersion) -> list[str]:
    parts = [version.template_id]
    if version.piece_id:
        parts.append(version.piece_id)
    parts.append(f"v{version.version}")
    return parts


def _arc_path(version: RenderVersion, file: Path) -> str:
    return "/".join([*_version_prefix(version), file.name])


def _finish_arc_path(version: RenderVersion, finish_id: str, file: Path) -> str:
    """Keep finished files beside their render but clearly labelled as Studio work."""
    return "/".join([*_version_prefix(version), "studio", finish_id, file.name])


def _manifest(state: CampaignState, plan: ExportPlan, created_at: str) -> str:
    lines = [
        "# Export package",
        "",
        f"- Campaign: {state.name}",
        f"- Goal: {state.goal}",
        f"- Contents: {MODE_LABELS.get(plan.mode, plan.mode)}",
        f"- Created: {created_at}",
        f"- Files: {plan.file_count}",
        f"- Size: {human_size(plan.total_bytes)}",
        "",
        "## Included",
        "",
    ]
    for item in plan.included:
        status = item.version.approval_status.replace("_", " ")
        lines.append(f"- {item.label} ({status}, {item.file_count} files)")
        for finish_id, file in item.finish_files:
            lines.append(f"    - Studio finish {finish_id}: {file.name}")
    if plan.excluded:
        lines.extend(["", "## Excluded", ""])
        for exclusion in plan.excluded:
            lines.append(f"- {exclusion.label} — {exclusion.reason}")
    return "\n".join(lines) + "\n"


def create_export_package(
    state: CampaignState,
    *,
    mode: str,
    selected_keys: set[str] | None = None,
) -> ExportResult:
    """Write the ZIP. Returns a result the UI can report honestly."""
    if state.path is None:
        return ExportResult(False, "No campaign is open.")

    plan = build_plan(state, mode=mode, selected_keys=selected_keys)
    if plan.is_empty:
        return ExportResult(
            False,
            "Nothing to export.",
            excluded=plan.excluded,
            detail="No render version matched the selected contents.",
        )

    created_at = datetime.now().strftime("%-d %b %Y, %H:%M")
    target_dir = exports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _archive_name(state, mode)

    written = 0
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in plan.included:
                for file in item.version.all_files(include_metadata=plan.include_metadata):
                    archive.write(file, _arc_path(item.version, file))
                    written += 1
                for finish_id, file in item.finish_files:
                    archive.write(file, _finish_arc_path(item.version, finish_id, file))
                    written += 1
            archive.writestr("MANIFEST.md", _manifest(state, plan, created_at))
    except (OSError, zipfile.BadZipFile) as exc:
        target.unlink(missing_ok=True)
        return ExportResult(
            False,
            "Could not create the export package.",
            excluded=plan.excluded,
            detail=str(exc),
        )

    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return ExportResult(
            False,
            "The export package was empty after writing.",
            excluded=plan.excluded,
        )

    return ExportResult(
        ok=True,
        message="Export package created.",
        path=target,
        file_count=written,
        total_bytes=target.stat().st_size,
        included=[item.label for item in plan.included],
        excluded=plan.excluded,
        created_at=created_at,
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
