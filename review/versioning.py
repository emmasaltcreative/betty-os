"""Versioned render outputs — never overwrite an original draft."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

VERSION_MANIFEST = "versions.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_versions(render_dir: Path) -> dict[str, Any]:
    path = render_dir / VERSION_MANIFEST
    if not path.is_file():
        return {"piece": render_dir.name, "versions": [], "current_version": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"piece": render_dir.name, "versions": [], "current_version": 0}
    if not isinstance(data, dict):
        return {"piece": render_dir.name, "versions": [], "current_version": 0}
    data.setdefault("piece", render_dir.name)
    data.setdefault("versions", [])
    data.setdefault("current_version", 0)
    return data


from src.persistence import atomic_write_json


def save_versions(render_dir: Path, data: dict[str, Any]) -> Path:
    path = render_dir / VERSION_MANIFEST
    atomic_write_json(path, data)
    return path


def _legacy_draft(render_dir: Path) -> Path | None:
    preferred = [
        render_dir / f"{render_dir.name}_draft.mp4",
        render_dir / f"{render_dir.name}.mp4",
    ]
    for path in preferred:
        if path.is_file():
            return path
    videos = sorted(render_dir.glob("*.mp4"))
    return videos[0] if videos else None


def ensure_baseline_version(render_dir: Path) -> dict[str, Any]:
    """Ensure an existing draft is recorded as version 1 without overwriting it."""
    data = load_versions(render_dir)
    if data.get("versions"):
        return data

    draft = _legacy_draft(render_dir)
    if draft is None:
        return data

    v1_name = f"{render_dir.name}_v1.mp4"
    v1_path = render_dir / v1_name
    if not v1_path.exists():
        shutil.copy2(draft, v1_path)

    entry = {
        "version": 1,
        "filename": v1_name,
        "parent_version": None,
        "revision_request_id": None,
        "revision_request_ids": [],
        "created_at": _now(),
        "review_status": "awaiting_review",
        "addressed_recommendation_ids": [],
        "source_draft": draft.name,
    }
    data["versions"] = [entry]
    data["current_version"] = 1
    save_versions(render_dir, data)
    return data


def next_version_number(render_dir: Path) -> int:
    data = ensure_baseline_version(render_dir)
    current = int(data.get("current_version") or 0)
    if current > 0:
        return current + 1
    # Also inspect filenames in case manifest is empty but vN files exist.
    highest = 0
    for path in render_dir.glob(f"{render_dir.name}_v*.mp4"):
        match = re.search(r"_v(\d+)\.mp4$", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1 if highest else 1


def register_version(
    render_dir: Path,
    *,
    version: int,
    filename: str,
    parent_version: int | None,
    revision_request_ids: list[str] | None = None,
    addressed_recommendation_ids: list[str] | None = None,
    review_status: str = "awaiting_review",
) -> dict[str, Any]:
    data = ensure_baseline_version(render_dir)
    entry = {
        "version": version,
        "filename": filename,
        "parent_version": parent_version,
        "revision_request_id": (revision_request_ids or [None])[0],
        "revision_request_ids": list(revision_request_ids or []),
        "created_at": _now(),
        "review_status": review_status,
        "addressed_recommendation_ids": list(addressed_recommendation_ids or []),
    }
    # Replace existing entry for this version if re-registered.
    versions = [
        v for v in data.get("versions") or [] if int(v.get("version") or 0) != version
    ]
    versions.append(entry)
    versions.sort(key=lambda v: int(v.get("version") or 0))
    data["versions"] = versions
    data["current_version"] = version
    save_versions(render_dir, data)
    return entry


def set_version_review_status(
    render_dir: Path,
    version: int,
    status: str,
) -> dict[str, Any] | None:
    data = load_versions(render_dir)
    found = None
    for entry in data.get("versions") or []:
        if int(entry.get("version") or 0) == version:
            entry["review_status"] = status
            found = entry
            break
    if found is None:
        return None
    save_versions(render_dir, data)
    return found


def list_version_entries(render_dir: Path) -> list[dict[str, Any]]:
    data = ensure_baseline_version(render_dir)
    return list(data.get("versions") or [])


def version_video_path(render_dir: Path, version: int) -> Path | None:
    data = load_versions(render_dir)
    for entry in data.get("versions") or []:
        if int(entry.get("version") or 0) == version:
            path = render_dir / str(entry.get("filename"))
            return path if path.is_file() else None
    candidate = render_dir / f"{render_dir.name}_v{version}.mp4"
    return candidate if candidate.is_file() else None
