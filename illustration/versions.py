"""Version lineage and storage for illustration generations.

Every draft, revision and export is an immutable record. Approving or revising
never overwrites a parent: a new version is written with ``parent_version_id``
pointing back. All bytes live under the private data root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common import DEFAULT_BRAND_ID
from src.data_dir import (
    illustration_dir,
    illustration_index,
    relative_to_data_root,
    resolve_data_path,
)
from src.persistence import atomic_write_json, load_json
from illustration.models import (
    ACCURACY_STATUSES,
    ILLUSTRATION_STATUSES,
    GenerationVersion,
    utc_now_iso,
)


class VersionError(Exception):
    """Version write or transition failed."""


def _load_raw(brand_id: str) -> dict:
    data = load_json(illustration_index(brand_id), default={"versions": []})
    return data if isinstance(data, dict) else {"versions": []}


def _save_raw(brand_id: str, data: dict) -> None:
    data["brand_id"] = brand_id
    data["updated_at"] = utc_now_iso()
    atomic_write_json(illustration_index(brand_id), data)


def list_versions(brand_id: str = DEFAULT_BRAND_ID) -> list[GenerationVersion]:
    raw = _load_raw(brand_id)
    return [
        GenerationVersion.from_dict(v)
        for v in raw.get("versions") or []
        if isinstance(v, dict)
    ]


def get_version(version_id: str, brand_id: str = DEFAULT_BRAND_ID) -> GenerationVersion | None:
    for version in list_versions(brand_id):
        if version.version_id == version_id:
            return version
    return None


def require_version(version_id: str, brand_id: str = DEFAULT_BRAND_ID) -> GenerationVersion:
    version = get_version(version_id, brand_id)
    if version is None:
        raise VersionError(f"Unknown illustration version: {version_id}")
    return version


def next_version_id(brand_id: str = DEFAULT_BRAND_ID) -> str:
    existing = list_versions(brand_id)
    numbers = []
    for version in existing:
        tail = version.version_id.rsplit("_v", 1)[-1]
        if tail.isdigit():
            numbers.append(int(tail))
    return f"ill_v{max(numbers, default=0) + 1:03d}"


def version_dir(version_id: str, brand_id: str = DEFAULT_BRAND_ID) -> Path:
    path = illustration_dir(brand_id) / version_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_bytes(
    version_id: str, filename: str, payload: bytes, brand_id: str = DEFAULT_BRAND_ID
) -> str:
    """Write bytes into a version's folder; returns the data-root-relative path."""
    target = version_dir(version_id, brand_id) / filename
    target.write_bytes(payload)
    return relative_to_data_root(target)


def resolve(stored: str | None) -> Path | None:
    return resolve_data_path(stored) if stored else None


def append_version(version: GenerationVersion, brand_id: str = DEFAULT_BRAND_ID) -> GenerationVersion:
    if version.status not in ILLUSTRATION_STATUSES:
        raise VersionError(f"Unknown status: {version.status}")
    if version.accuracy_status not in ACCURACY_STATUSES:
        raise VersionError(f"Unknown accuracy status: {version.accuracy_status}")
    raw = _load_raw(brand_id)
    versions = list(raw.get("versions") or [])
    if any(
        isinstance(v, dict) and v.get("version_id") == version.version_id
        for v in versions
    ):
        raise VersionError(
            f"{version.version_id} already exists; versions are never overwritten."
        )
    versions.append(version.to_dict())
    raw["versions"] = versions
    _save_raw(brand_id, raw)
    return require_version(version.version_id, brand_id)


def update_version(
    version_id: str, brand_id: str = DEFAULT_BRAND_ID, **updates: Any
) -> GenerationVersion:
    """Mutate metadata only — never the stored image bytes of a parent."""
    if "status" in updates and updates["status"] not in ILLUSTRATION_STATUSES:
        raise VersionError(f"Unknown status: {updates['status']}")
    if (
        "accuracy_status" in updates
        and updates["accuracy_status"] not in ACCURACY_STATUSES
    ):
        raise VersionError(f"Unknown accuracy status: {updates['accuracy_status']}")
    raw = _load_raw(brand_id)
    found = False
    for item in raw.get("versions") or []:
        if isinstance(item, dict) and item.get("version_id") == version_id:
            item.update(updates)
            item["updated_at"] = utc_now_iso()
            found = True
            break
    if not found:
        raise VersionError(f"Unknown illustration version: {version_id}")
    _save_raw(brand_id, raw)
    return require_version(version_id, brand_id)


def lineage(version_id: str, brand_id: str = DEFAULT_BRAND_ID) -> list[GenerationVersion]:
    """Oldest-first chain from the original draft to this version."""
    by_id = {v.version_id: v for v in list_versions(brand_id)}
    current = by_id.get(version_id)
    chain: list[GenerationVersion] = []
    seen: set[str] = set()
    while current is not None and current.version_id not in seen:
        seen.add(current.version_id)
        chain.append(current)
        current = (
            by_id.get(current.parent_version_id) if current.parent_version_id else None
        )
    return list(reversed(chain))


def children(version_id: str, brand_id: str = DEFAULT_BRAND_ID) -> list[GenerationVersion]:
    return [v for v in list_versions(brand_id) if v.parent_version_id == version_id]


def approve(
    version_id: str,
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    product_accurate: bool = False,
) -> GenerationVersion:
    """Promote to editorial use. Accuracy is a separate, deliberate claim."""
    return update_version(
        version_id,
        brand_id,
        status="approved_for_editorial_use",
        accuracy_status=(
            "product_accurate_verified"
            if product_accurate
            else "requires_product_verification"
        ),
    )


def reject(version_id: str, brand_id: str = DEFAULT_BRAND_ID, *, note: str = "") -> GenerationVersion:
    """Rejected versions stay reachable but never anchor future work."""
    return update_version(version_id, brand_id, status="rejected", notes=note)


def export_manifest(
    version_ids: list[str], brand_id: str = DEFAULT_BRAND_ID
) -> dict[str, Any]:
    """Handoff manifest describing exactly the files that exist on disk."""
    entries: list[dict[str, Any]] = []
    for version_id in version_ids:
        version = require_version(version_id, brand_id)
        files: dict[str, Any] = {}
        for kind, stored in version.export_paths.items():
            path = resolve(stored)
            files[kind] = {
                "filename": path.name if path else None,
                "exists": bool(path and path.is_file()),
                "bytes": path.stat().st_size if path and path.is_file() else 0,
            }
        entries.append(
            {
                "version_id": version.version_id,
                "status": version.status,
                "accuracy_status": version.accuracy_status,
                "template_id": version.brief.template_id,
                "canvas": version.brief.canvas,
                "provider": version.provider,
                "model": version.model,
                "parent_version_id": version.parent_version_id,
                "created_at": version.created_at,
                "source_resolution": [version.source_width, version.source_height],
                "reference_asset_ids": [
                    r.asset_id for r in version.brief.references
                ],
                "layers": version.layer_manifest.names(),
                "files": files,
            }
        )
    return {
        "brand_id": brand_id,
        "generated_at": utc_now_iso(),
        "versions": entries,
    }
