"""Finish drafts and immutable finished versions — non-destructive persistence."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.common import ROOT, relative_to_root
from src.persistence import atomic_write_json, load_json
from studio.models import FinishConfiguration, FinishRecord, utc_now_iso
from studio.paths import drafts_dir, finish_version_dir, render_studio_root


def render_version_id(version: int) -> str:
    return f"render_v{int(version):03d}"


def list_finish_version_ids(render_folder: Path) -> list[str]:
    root = render_studio_root(render_folder, create=False)
    if not root.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and path.name.startswith("finish_v"):
            meta = path / "finish_metadata.json"
            if meta.is_file():
                ids.append(path.name)
    return ids


def next_finish_version_id(render_folder: Path) -> str:
    """Derive next finish_vNNN from persisted directories — not session state."""
    highest = 0
    root = render_studio_root(render_folder, create=False)
    names = list_finish_version_ids(render_folder)
    if root.is_dir():
        for path in root.glob("finish_v*"):
            names.append(path.name)
    for name in names:
        try:
            highest = max(highest, int(name.replace("finish_v", "").split("_")[0]))
        except ValueError:
            continue
    return f"finish_v{highest + 1:03d}"


def draft_id_for(
    campaign_id: str,
    content_piece_id: str | None,
    render_version_id_str: str,
    source_name: str,
) -> str:
    piece = content_piece_id or "nopiece"
    safe_source = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(source_name).stem)[:40]
    return f"draft_{campaign_id[:24]}_{piece[:32]}_{render_version_id_str}_{safe_source}"


def draft_path(render_folder: Path, draft_id: str) -> Path:
    return drafts_dir(render_folder) / draft_id


def load_draft(render_folder: Path, draft_id: str) -> dict[str, Any] | None:
    path = draft_path(render_folder, draft_id) / "finish_config.json"
    data = load_json(path, default=None)
    return data if isinstance(data, dict) else None


def save_draft(
    render_folder: Path,
    draft_id: str,
    config: FinishConfiguration,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    folder = draft_path(render_folder, draft_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = config.to_dict()
    payload["_draft_id"] = draft_id
    payload["_updated_at"] = utc_now_iso()
    if meta:
        payload["_meta"] = meta
    atomic_write_json(folder / "finish_config.json", payload)
    reloaded = load_draft(render_folder, draft_id)
    if reloaded is None:
        raise RuntimeError("Draft save could not be verified.")
    return reloaded


def discard_draft(render_folder: Path, draft_id: str) -> None:
    folder = draft_path(render_folder, draft_id)
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def load_finish_record(render_folder: Path, finish_version_id: str) -> FinishRecord | None:
    meta_path = finish_version_dir(render_folder, finish_version_id) / "finish_metadata.json"
    data = load_json(meta_path, default=None)
    if not isinstance(data, dict):
        return None
    return FinishRecord.from_dict(data)


def load_finish_config(render_folder: Path, finish_version_id: str) -> FinishConfiguration | None:
    path = finish_version_dir(render_folder, finish_version_id) / "finish_config.json"
    data = load_json(path, default=None)
    if not isinstance(data, dict):
        return None
    return FinishConfiguration.from_dict(data)


def list_finish_records(render_folder: Path) -> list[FinishRecord]:
    records: list[FinishRecord] = []
    for fid in list_finish_version_ids(render_folder):
        record = load_finish_record(render_folder, fid)
        if record is not None:
            records.append(record)
    return records


def create_finished_version(
    *,
    render_folder: Path,
    campaign_id: str,
    content_piece_id: str | None,
    template_id: str,
    parent_render_version_id: str,
    parent_finish_version_id: str | None,
    source_file: Path,
    media_type: str,
    config: FinishConfiguration,
    process_fn,
    source_asset_id: str | None = None,
    source_output_id: str | None = None,
    edit_decision: dict[str, Any] | None = None,
    execution_report: dict[str, Any] | None = None,
    revision_note: str | None = None,
    creative_review_score: float | None = None,
) -> FinishRecord:
    """
    Non-destructive finished version creation.

    1. validate (caller)
    2. temp working directory
    3. process output via process_fn(work_dir) -> dict with output/preview/validation/ffmpeg
    4. validate generated file (caller + process_fn)
    5. write config + metadata
    6. atomically move into final finish_vNNN location
    7. reload and return
    """
    finish_id = next_finish_version_id(render_folder)
    final_dir = finish_version_dir(render_folder, finish_id)
    if final_dir.exists():
        raise RuntimeError(f"Finish version already exists: {finish_id}")

    studio_root = render_studio_root(render_folder)
    studio_root.mkdir(parents=True, exist_ok=True)
    tmp_parent = Path(
        tempfile.mkdtemp(prefix=f".{finish_id}.", dir=str(studio_root))
    )

    try:
        work_outputs = tmp_parent / "outputs"
        work_previews = tmp_parent / "previews"
        work_outputs.mkdir(parents=True)
        work_previews.mkdir(parents=True)

        result = process_fn(tmp_parent, work_outputs, work_previews)
        if not isinstance(result, dict):
            raise RuntimeError("Processor returned an invalid result.")
        if result.get("ok") is not True:
            reason = str(result.get("error") or "Processing failed.")
            _persist_failure(
                render_folder=render_folder,
                finish_id=finish_id,
                campaign_id=campaign_id,
                content_piece_id=content_piece_id,
                template_id=template_id,
                parent_render_version_id=parent_render_version_id,
                parent_finish_version_id=parent_finish_version_id,
                source_file=source_file,
                media_type=media_type,
                config=config,
                failure_reason=reason,
                source_asset_id=source_asset_id,
                source_output_id=source_output_id,
                edit_decision=edit_decision,
                execution_report=execution_report,
                revision_note=revision_note,
                creative_review_score=creative_review_score,
            )
            raise RuntimeError(reason)

        output_files = [Path(p) for p in result.get("output_files") or []]
        preview_files = [Path(p) for p in result.get("preview_files") or []]
        for path in output_files:
            if not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError("Finished output file is missing or empty.")

        validation = result.get("validation") or {"outcome": "pass", "items": []}
        now = utc_now_iso()

        # Relocate paths into final names before move
        rel_outputs: list[str] = []
        rel_previews: list[str] = []
        for path in output_files:
            rel_outputs.append(f"outputs/{path.name}")
        for path in preview_files:
            rel_previews.append(f"previews/{path.name}")

        config_payload = config.to_dict()
        atomic_write_json(tmp_parent / "finish_config.json", config_payload)
        atomic_write_json(tmp_parent / "validation.json", validation)

        record = FinishRecord(
            finish_version_id=finish_id,
            campaign_id=campaign_id,
            content_piece_id=content_piece_id,
            template_id=template_id,
            parent_render_version_id=parent_render_version_id,
            parent_finish_version_id=parent_finish_version_id,
            source_asset_id=source_asset_id,
            source_output_id=source_output_id,
            source_file=relative_to_root(source_file),
            media_type=media_type,
            recipe_id=config.recipe_id,
            recipe_version=config.recipe_version,
            logo_configuration=config.logo.to_dict(),
            lighting_configuration=config.lighting.to_dict(),
            color_configuration=config.color.to_dict(),
            texture_configuration=config.texture.to_dict(),
            geometry_configuration=config.geometry.to_dict(),
            lut_configuration=config.lut.to_dict(),
            export_configuration=config.export.to_dict(),
            video_configuration=config.video.to_dict(),
            output_files=rel_outputs,
            preview_files=rel_previews,
            validation_results=validation,
            # Immutable on disk; Send to Review sets ready_for_review.
            status="draft",
            approval_status="not_submitted",
            created_at=now,
            updated_at=now,
            failure_reason=None,
            ffmpeg_command=result.get("ffmpeg_command"),
            technical_notes=dict(result.get("technical_notes") or {}),
            edit_decision=dict(edit_decision or {}),
            execution_report=dict(execution_report or {}),
            revision_note=revision_note,
            creative_review_score=creative_review_score,
        )
        atomic_write_json(tmp_parent / "finish_metadata.json", record.to_dict())
        # Always persist decision/report artifacts for audit (empty when manual finish).
        atomic_write_json(tmp_parent / "edit_decision.json", edit_decision or {})
        atomic_write_json(tmp_parent / "execution_report.json", execution_report or {})

        # Atomic move into place
        os_replace_dir(tmp_parent, final_dir)

        reloaded = load_finish_record(render_folder, finish_id)
        if reloaded is None:
            raise RuntimeError("Finished version could not be reloaded after write.")
        # Verify outputs exist
        for rel in reloaded.output_files:
            out = finish_version_dir(render_folder, finish_id) / rel
            if not out.is_file() or out.stat().st_size <= 0:
                raise RuntimeError("Finished output missing after move.")
        return reloaded
    except Exception:
        shutil.rmtree(tmp_parent, ignore_errors=True)
        raise


def os_replace_dir(src: Path, dest: Path) -> None:
    """Move completed version directory into final location atomically when possible."""
    dest = Path(dest)
    if dest.exists():
        raise RuntimeError(f"Destination already exists: {dest}")
    src.rename(dest)


def _persist_failure(
    *,
    render_folder: Path,
    finish_id: str,
    campaign_id: str,
    content_piece_id: str | None,
    template_id: str,
    parent_render_version_id: str,
    parent_finish_version_id: str | None,
    source_file: Path,
    media_type: str,
    config: FinishConfiguration,
    failure_reason: str,
    source_asset_id: str | None,
    source_output_id: str | None,
    edit_decision: dict[str, Any] | None = None,
    execution_report: dict[str, Any] | None = None,
    revision_note: str | None = None,
    creative_review_score: float | None = None,
) -> None:
    """Write a failed record beside studio root without claiming success."""
    fail_dir = render_studio_root(render_folder) / f"{finish_id}_failed_{uuid4().hex[:6]}"
    fail_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now_iso()
    record = FinishRecord(
        finish_version_id=finish_id,
        campaign_id=campaign_id,
        content_piece_id=content_piece_id,
        template_id=template_id,
        parent_render_version_id=parent_render_version_id,
        parent_finish_version_id=parent_finish_version_id,
        source_asset_id=source_asset_id,
        source_output_id=source_output_id,
        source_file=relative_to_root(source_file),
        media_type=media_type,
        recipe_id=config.recipe_id,
        recipe_version=config.recipe_version,
        logo_configuration=config.logo.to_dict(),
        lighting_configuration=config.lighting.to_dict(),
        color_configuration=config.color.to_dict(),
        texture_configuration=config.texture.to_dict(),
        geometry_configuration=config.geometry.to_dict(),
        lut_configuration=config.lut.to_dict(),
        export_configuration=config.export.to_dict(),
        video_configuration=config.video.to_dict(),
        output_files=[],
        preview_files=[],
        validation_results={"outcome": "fail", "items": []},
        status="failed",
        approval_status="not_submitted",
        created_at=now,
        updated_at=now,
        failure_reason=failure_reason,
        edit_decision=dict(edit_decision or {}),
        execution_report=dict(execution_report or {}),
        revision_note=revision_note,
        creative_review_score=creative_review_score,
    )
    atomic_write_json(fail_dir / "finish_metadata.json", record.to_dict())
    atomic_write_json(fail_dir / "finish_config.json", config.to_dict())
    atomic_write_json(fail_dir / "edit_decision.json", edit_decision or {})
    atomic_write_json(fail_dir / "execution_report.json", execution_report or {})


def update_finish_status(
    render_folder: Path,
    finish_version_id: str,
    *,
    status: str | None = None,
    approval_status: str | None = None,
    revision_note: str | None = None,
) -> FinishRecord:
    record = load_finish_record(render_folder, finish_version_id)
    if record is None:
        raise KeyError(finish_version_id)
    data = record.to_dict()
    if status is not None:
        data["status"] = status
    if approval_status is not None:
        data["approval_status"] = approval_status
    if revision_note is not None:
        data["revision_note"] = revision_note
    data["updated_at"] = utc_now_iso()
    meta_path = finish_version_dir(render_folder, finish_version_id) / "finish_metadata.json"
    atomic_write_json(meta_path, data)
    reloaded = load_finish_record(render_folder, finish_version_id)
    if reloaded is None:
        raise RuntimeError("Status update could not be verified.")
    return reloaded


def resolve_finish_output(render_folder: Path, record: FinishRecord) -> Path | None:
    if not record.output_files:
        return None
    path = finish_version_dir(render_folder, record.finish_version_id) / record.output_files[0]
    return path if path.is_file() else None


def resolve_finish_outputs(render_folder: Path, record: FinishRecord) -> list[Path]:
    """Every finished output that is still on disk, in recorded order."""
    base = finish_version_dir(render_folder, record.finish_version_id)
    return [path for rel in record.output_files if (path := base / rel).is_file()]


def resolve_finish_preview(render_folder: Path, record: FinishRecord) -> Path | None:
    if not record.preview_files:
        return None
    path = finish_version_dir(render_folder, record.finish_version_id) / record.preview_files[0]
    return path if path.is_file() else None


def resolve_source(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    return path


def config_hash(config: FinishConfiguration) -> str:
    payload = json.dumps(config.to_dict(), sort_keys=True, ensure_ascii=False)
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
