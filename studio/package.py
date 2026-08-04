"""Studio package ZIP and download helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

from studio.models import FinishRecord
from studio.paths import download_basename, finish_version_dir, sanitize_filename
from studio.versions import resolve_finish_output


def mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".json": "application/json",
        ".zip": "application/zip",
    }.get(suffix, "application/octet-stream")


def finished_download_name(record: FinishRecord, output: Path) -> str:
    recipe = record.recipe_id or "custom"
    piece = record.content_piece_id or "piece"
    return download_basename(
        record.campaign_id,
        piece,
        recipe,
        record.finish_version_id,
        output.suffix,
    )


def build_studio_package(
    render_folder: Path,
    record: FinishRecord,
    *,
    dest: Path,
) -> Path:
    folder = finish_version_dir(render_folder, record.finish_version_id)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in record.output_files:
            path = folder / rel
            if path.is_file():
                zf.write(path, arcname=f"outputs/{path.name}")
        for rel in record.preview_files:
            path = folder / rel
            if path.is_file():
                zf.write(path, arcname=f"previews/{path.name}")
        for name in (
            "finish_config.json",
            "finish_metadata.json",
            "validation.json",
            "edit_decision.json",
            "execution_report.json",
        ):
            path = folder / name
            if path.is_file():
                zf.write(path, arcname=name)
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise RuntimeError("Studio package was not created.")
    return dest


def package_download_name(record: FinishRecord) -> str:
    return download_basename(
        record.campaign_id,
        record.content_piece_id or "piece",
        record.recipe_id or "custom",
        record.finish_version_id,
        ".zip",
    )


def output_is_downloadable(render_folder: Path, record: FinishRecord) -> Path | None:
    path = resolve_finish_output(render_folder, record)
    if path is None or not path.is_file() or path.stat().st_size <= 0:
        return None
    return path
