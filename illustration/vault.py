"""Brand Asset Vault — durable, reusable, private reference catalog.

Upload once, select forever. The index lives under the private data root
(``src.data_dir``), so family photographs and proprietary product masters never
enter the public repository. Full originals are always preserved; thumbnails and
previews are derived.

This sits *on top of* the existing ``studio.brand_assets`` feature rather than
replacing it: locked house marks already uploaded as Studio brand assets are
surfaced through :func:`linked_brand_assets` instead of being copied into a
second disconnected pile.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from PIL import Image, ImageOps

from src.common import DEFAULT_BRAND_ID
from src.data_dir import (
    relative_to_data_root,
    resolve_data_path,
    vault_dir,
    vault_index,
    vault_thumbnails_dir,
)
from src.persistence import atomic_write_json, load_json
from studio import brand_assets as studio_brand_assets
from studio.paths import sanitize_filename
from illustration.models import (
    REFERENCE_ROLES,
    VAULT_CATEGORIES,
    VERIFICATION_STATES,
    VaultAsset,
    utc_now_iso,
)

# Safe import surface (brief §7D). PDFs are stored but not rasterised here.
ALLOWED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".svg", ".pdf",
}
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
MAX_FILE_BYTES = 64 * 1024 * 1024       # 64 MB per asset
MAX_ZIP_ENTRIES = 500
MAX_ZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
THUMBNAIL_MAX = (480, 480)

_SVG_FORBIDDEN = re.compile(
    r"<script|javascript:|<foreignObject|\son\w+\s*=|<!ENTITY|<iframe",
    re.IGNORECASE,
)


class VaultError(Exception):
    """Vault import or update failed."""


# --- index I/O -----------------------------------------------------------------


def _load_raw(brand_id: str) -> dict:
    data = load_json(vault_index(brand_id), default={"assets": []})
    return data if isinstance(data, dict) else {"assets": []}


def _save_raw(brand_id: str, data: dict) -> None:
    data["brand_id"] = brand_id
    data["updated_at"] = utc_now_iso()
    atomic_write_json(vault_index(brand_id), data)


def list_assets(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    include_archived: bool = False,
) -> list[VaultAsset]:
    raw = _load_raw(brand_id)
    assets = [
        VaultAsset.from_dict(a)
        for a in raw.get("assets") or []
        if isinstance(a, dict)
    ]
    if include_archived:
        return assets
    return [a for a in assets if not a.archived]


def get_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset | None:
    for asset in list_assets(brand_id, include_archived=True):
        if asset.asset_id == asset_id:
            return asset
    return None


def require_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    asset = get_asset(asset_id, brand_id)
    if asset is None:
        raise VaultError(f"Unknown vault asset: {asset_id}")
    return asset


def asset_path(asset: VaultAsset) -> Path:
    """Absolute path to the preserved original."""
    return resolve_data_path(asset.file_path)


def find_by_checksum(sha256: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset | None:
    for asset in list_assets(brand_id, include_archived=True):
        if asset.sha256 == sha256:
            return asset
    return None


# --- validation ----------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_svg(text: str) -> str:
    """Strip active content from an SVG. Raises when it cannot be made safe."""
    if "<svg" not in text.lower():
        raise VaultError("File does not contain an <svg> root element.")
    if _SVG_FORBIDDEN.search(text):
        raise VaultError(
            "SVG contains scripts, event handlers, entities or embedded frames "
            "and was rejected. Export a clean SVG without active content."
        )
    return text


def validate_source(path: Path, *, category: str, roles: Iterable[str]) -> list[str]:
    errors: list[str] = []
    path = Path(path)
    if not path.is_file():
        return ["File is not readable."]
    size = path.stat().st_size
    if size <= 0:
        return ["File is empty."]
    if size > MAX_FILE_BYTES:
        errors.append(
            f"File is {size / 1_048_576:.1f} MB; the limit is "
            f"{MAX_FILE_BYTES // 1_048_576} MB."
        )
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        errors.append(
            f"Unsupported format {suffix or '(none)'}. "
            f"Use {', '.join(sorted(ALLOWED_SUFFIXES))}."
        )
        return errors
    if category not in VAULT_CATEGORIES:
        errors.append(f"Unknown vault category: {category}")
    for role in roles:
        if role not in REFERENCE_ROLES:
            errors.append(f"Unknown reference role: {role}")

    if suffix == ".svg":
        try:
            sanitize_svg(path.read_text(encoding="utf-8", errors="ignore"))
        except VaultError as exc:
            errors.append(str(exc))
    elif suffix in RASTER_SUFFIXES:
        try:
            with Image.open(path) as img:
                img.verify()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Image could not be decoded: {exc}")
    return errors


def _probe(path: Path) -> tuple[int | None, int | None, bool]:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        text = path.read_text(encoding="utf-8", errors="ignore")
        width = height = None
        wb = re.search(r'width=["\']([\d.]+)', text)
        hb = re.search(r'height=["\']([\d.]+)', text)
        if wb and hb:
            try:
                width, height = int(float(wb.group(1))), int(float(hb.group(1)))
            except ValueError:
                pass
        if width is None:
            vb = re.search(
                r'viewBox=["\']\s*[\d.-]+\s+[\d.-]+\s+([\d.]+)\s+([\d.]+)', text
            )
            if vb:
                try:
                    width, height = int(float(vb.group(1))), int(float(vb.group(2)))
                except ValueError:
                    pass
        return width, height, True
    if suffix == ".pdf":
        return None, None, False
    with Image.open(path) as img:
        img.load()
        has_alpha = img.mode in {"RGBA", "LA"} or (
            img.mode == "P" and "transparency" in img.info
        )
        return img.width, img.height, bool(has_alpha)


def _make_thumbnail(source: Path, asset_id: str, brand_id: str) -> str | None:
    if source.suffix.lower() not in RASTER_SUFFIXES:
        return None
    try:
        with Image.open(source) as img:
            # Normalize orientation without touching the preserved original.
            img = ImageOps.exif_transpose(img)
            img.thumbnail(THUMBNAIL_MAX)
            out = vault_thumbnails_dir(brand_id) / f"{asset_id}.png"
            img.convert("RGBA").save(out, "PNG")
            return relative_to_data_root(out)
    except Exception:  # noqa: BLE001 — thumbnails are derived, never load-bearing
        return None


# --- import --------------------------------------------------------------------


def import_asset(
    source: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    category: str,
    display_name: str = "",
    roles: list[str] | None = None,
    state: str = "draft",
    tags: list[str] | None = None,
    product_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    botanical_names: list[str] | None = None,
    reference_priority: int = 50,
    license_note: str = "",
    is_private: bool = True,
    third_party_api_opt_in: bool = False,
    original_filename: str | None = None,
    dedupe: bool = True,
) -> VaultAsset:
    """Copy a file into the vault once and register it durably."""
    source = Path(source)
    roles = list(roles or [])
    errors = validate_source(source, category=category, roles=roles)
    if errors:
        raise VaultError("; ".join(errors))
    if state not in VERIFICATION_STATES:
        raise VaultError(f"Unknown verification state: {state}")

    checksum = sha256_of(source)
    if dedupe:
        existing = find_by_checksum(checksum, brand_id)
        if existing is not None:
            return existing

    asset_id = f"va_{uuid4().hex[:10]}"
    safe = sanitize_filename(original_filename or source.name)
    dest = vault_dir(brand_id) / f"{asset_id}_{safe}"
    shutil.copy2(source, dest)

    if dest.suffix.lower() == ".svg":
        # Persist the sanitized text so the stored original is itself safe.
        dest.write_text(
            sanitize_svg(dest.read_text(encoding="utf-8", errors="ignore")),
            encoding="utf-8",
        )

    width, height, has_alpha = _probe(dest)
    mime, _ = mimetypes.guess_type(dest.name)
    now = utc_now_iso()

    record = VaultAsset(
        asset_id=asset_id,
        brand_id=brand_id,
        category=category,
        display_name=(display_name or source.stem).strip(),
        file_path=relative_to_data_root(dest),
        sha256=checksum,
        mime_type=mime or "application/octet-stream",
        original_filename=original_filename or source.name,
        roles=roles,
        width=width,
        height=height,
        has_alpha=has_alpha,
        tags=list(tags or []),
        product_ids=list(product_ids or []),
        character_ids=list(character_ids or []),
        botanical_names=list(botanical_names or []),
        reference_priority=int(reference_priority),
        state=state,
        license_note=license_note,
        is_private=is_private,
        third_party_api_opt_in=third_party_api_opt_in,
        thumbnail_path=_make_thumbnail(dest, asset_id, brand_id),
        created_at=now,
        updated_at=now,
    )

    raw = _load_raw(brand_id)
    assets = list(raw.get("assets") or [])
    assets.append(record.to_dict())
    raw["assets"] = assets
    _save_raw(brand_id, raw)

    saved = get_asset(asset_id, brand_id)
    if saved is None:
        raise VaultError("Vault write could not be verified.")
    return saved


def _read_manifest(zf: zipfile.ZipFile, members: list) -> dict[str, dict]:
    import json

    manifest: dict[str, dict] = {}
    for member in members:
        if Path(member.filename).name.lower() != "manifest.json":
            continue
        try:
            payload = json.loads(zf.read(member).decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for entry in payload.get("assets") or []:
            if isinstance(entry, dict) and entry.get("path"):
                manifest[str(entry["path"]).strip("/")] = entry
    return manifest


def _classify_member(name: str, size: int) -> tuple[bool, str]:
    """Shared gate for a dry run and the real import."""
    base = Path(name).name
    if base.lower() == "manifest.json":
        return False, "manifest"
    if name.startswith("/") or ".." in Path(name).parts:
        return False, "unsafe archive path"
    if Path(base).suffix.lower() not in ALLOWED_SUFFIXES:
        return False, "unsupported file type"
    if size > MAX_FILE_BYTES:
        return False, "file too large"
    return True, ""


def inspect_zip(
    archive: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    default_category: str = "style_anchors",
) -> dict[str, Any]:
    """Dry run: what a starter pack would import, without writing anything."""
    archive = Path(archive)
    if not archive.is_file():
        raise VaultError("Archive is not readable.")

    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > MAX_ZIP_ENTRIES:
            raise VaultError(
                f"Archive has {len(members)} files; the limit is {MAX_ZIP_ENTRIES}."
            )
        manifest = _read_manifest(zf, members)
        described = set(manifest)
        for member in members:
            ok, reason = _classify_member(member.filename, member.file_size)
            if not ok:
                if reason != "manifest":
                    skipped.append({"path": member.filename, "reason": reason})
                continue
            meta = manifest.get(member.filename.strip("/"), {})
            planned.append(
                {
                    "path": member.filename,
                    "bytes": member.file_size,
                    "category": str(meta.get("category") or default_category),
                    "state": str(meta.get("state") or "draft"),
                    "roles": list(meta.get("roles") or []),
                    "tags": list(meta.get("tags") or []),
                    "character_ids": list(meta.get("character_ids") or []),
                    "product_ids": list(meta.get("product_ids") or []),
                    "in_manifest": member.filename.strip("/") in manifest,
                }
            )
    return {
        "planned": planned,
        "skipped": skipped,
        "manifest_entries": len(described),
        "undescribed": [p["path"] for p in planned if not p["in_manifest"]],
        "manifest_paths_not_in_zip": sorted(
            described - {p["path"].strip("/") for p in planned}
        ),
    }


def import_zip(
    archive: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    default_category: str = "style_anchors",
) -> dict[str, Any]:
    """Bootstrap from a starter-pack ZIP, honouring an optional manifest.

    ``manifest.json`` may map archive member names to per-asset metadata::

        {"assets": [{"path": "marks/flower.svg", "category": "official_marks",
                      "state": "locked", "roles": ["mark_source"]}]}
    """
    archive = Path(archive)
    if not archive.is_file():
        raise VaultError("Archive is not readable.")

    imported: list[VaultAsset] = []
    skipped: list[dict[str, str]] = []
    staging = vault_dir(brand_id) / f"_import_{uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) > MAX_ZIP_ENTRIES:
                raise VaultError(
                    f"Archive has {len(members)} files; the limit is {MAX_ZIP_ENTRIES}."
                )
            total = sum(m.file_size for m in members)
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise VaultError(
                    f"Archive expands to {total / 1_048_576:.0f} MB; the limit is "
                    f"{MAX_ZIP_UNCOMPRESSED_BYTES // 1_048_576} MB."
                )

            manifest = _read_manifest(zf, members)

            for member in members:
                name = member.filename
                base = Path(name).name
                ok, reason = _classify_member(name, member.file_size)
                if not ok:
                    if reason != "manifest":
                        skipped.append({"path": name, "reason": reason})
                    continue

                target = staging / sanitize_filename(base)
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)

                meta = manifest.get(name.strip("/"), {})
                # Identical bytes already in the vault: report it rather than
                # silently returning the old record under a new manifest role.
                duplicate = find_by_checksum(sha256_of(target), brand_id)
                if duplicate is not None:
                    skipped.append(
                        {
                            "path": name,
                            "reason": (
                                f"duplicate of existing asset {duplicate.asset_id} "
                                f"({duplicate.display_name})"
                            ),
                        }
                    )
                    target.unlink(missing_ok=True)
                    continue
                try:
                    record = import_asset(
                        target,
                        brand_id=brand_id,
                        category=str(meta.get("category") or default_category),
                        display_name=str(meta.get("display_name") or Path(base).stem),
                        roles=list(meta.get("roles") or []),
                        state=str(meta.get("state") or "draft"),
                        tags=list(meta.get("tags") or []),
                        product_ids=list(meta.get("product_ids") or []),
                        character_ids=list(meta.get("character_ids") or []),
                        botanical_names=list(meta.get("botanical_names") or []),
                        reference_priority=int(meta.get("reference_priority") or 50),
                        license_note=str(meta.get("license_note") or ""),
                        is_private=bool(meta.get("is_private", True)),
                        original_filename=base,
                    )
                except VaultError as exc:
                    skipped.append({"path": name, "reason": str(exc)})
                    continue
                imported.append(record)
                target.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {"imported": imported, "skipped": skipped}


# --- mutation ------------------------------------------------------------------


def _update(asset_id: str, brand_id: str, **updates: Any) -> VaultAsset:
    raw = _load_raw(brand_id)
    found = False
    for item in raw.get("assets") or []:
        if isinstance(item, dict) and item.get("asset_id") == asset_id:
            item.update(updates)
            item["updated_at"] = utc_now_iso()
            found = True
            break
    if not found:
        raise VaultError(f"Unknown vault asset: {asset_id}")
    _save_raw(brand_id, raw)
    return require_asset(asset_id, brand_id)


def rename_asset(asset_id: str, display_name: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    return _update(asset_id, brand_id, display_name=display_name.strip())


def set_state(asset_id: str, state: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    if state not in VERIFICATION_STATES:
        raise VaultError(f"Unknown verification state: {state}")
    return _update(asset_id, brand_id, state=state)


def set_roles(asset_id: str, roles: list[str], brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    for role in roles:
        if role not in REFERENCE_ROLES:
            raise VaultError(f"Unknown reference role: {role}")
    return _update(asset_id, brand_id, roles=list(roles))


def set_tags(asset_id: str, tags: list[str], brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    return _update(asset_id, brand_id, tags=list(tags))


def associate(
    asset_id: str,
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    product_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    botanical_names: list[str] | None = None,
) -> VaultAsset:
    updates: dict[str, Any] = {}
    if product_ids is not None:
        updates["product_ids"] = list(product_ids)
    if character_ids is not None:
        updates["character_ids"] = list(character_ids)
    if botanical_names is not None:
        updates["botanical_names"] = list(botanical_names)
    return _update(asset_id, brand_id, **updates)


def set_api_opt_in(asset_id: str, opted_in: bool, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    """Explicit consent before a private reference reaches a third-party API."""
    return _update(asset_id, brand_id, third_party_api_opt_in=bool(opted_in))


def archive_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    return _update(asset_id, brand_id, archived=True)


def restore_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> VaultAsset:
    return _update(asset_id, brand_id, archived=False)


def replace_with_new_version(
    asset_id: str,
    source: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    display_name: str = "",
) -> VaultAsset:
    """Supersede an asset without deleting it. History stays reachable."""
    parent = require_asset(asset_id, brand_id)
    child = import_asset(
        source,
        brand_id=brand_id,
        category=parent.category,
        display_name=display_name or parent.display_name,
        roles=list(parent.roles),
        state=parent.state,
        tags=list(parent.tags),
        product_ids=list(parent.product_ids),
        character_ids=list(parent.character_ids),
        botanical_names=list(parent.botanical_names),
        reference_priority=parent.reference_priority,
        license_note=parent.license_note,
        is_private=parent.is_private,
        dedupe=False,
    )
    child = _update(
        child.asset_id,
        brand_id,
        parent_id=parent.asset_id,
        version=parent.version + 1,
    )
    _update(asset_id, brand_id, archived=True)
    return child


def version_lineage(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> list[VaultAsset]:
    """Oldest-first chain for an asset, following parent links."""
    by_id = {a.asset_id: a for a in list_assets(brand_id, include_archived=True)}
    current = by_id.get(asset_id)
    chain: list[VaultAsset] = []
    seen: set[str] = set()
    while current is not None and current.asset_id not in seen:
        seen.add(current.asset_id)
        chain.append(current)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return list(reversed(chain))


# --- selection -----------------------------------------------------------------


def search(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    text: str = "",
    categories: Iterable[str] | None = None,
    roles: Iterable[str] | None = None,
    states: Iterable[str] | None = None,
    product_id: str | None = None,
    character_id: str | None = None,
    include_archived: bool = False,
) -> list[VaultAsset]:
    results = list_assets(brand_id, include_archived=include_archived)
    if categories:
        wanted = set(categories)
        results = [a for a in results if a.category in wanted]
    if roles:
        wanted = set(roles)
        results = [a for a in results if wanted & set(a.roles)]
    if states:
        wanted = set(states)
        results = [a for a in results if a.state in wanted]
    if product_id:
        results = [a for a in results if product_id in a.product_ids]
    if character_id:
        results = [a for a in results if character_id in a.character_ids]
    if text:
        needle = text.strip().lower()
        results = [
            a for a in results
            if needle in a.display_name.lower()
            or needle in " ".join(a.tags).lower()
            or needle in " ".join(a.botanical_names).lower()
            or needle in a.original_filename.lower()
        ]
    return sorted(results, key=_selection_rank)


def _selection_rank(asset: VaultAsset) -> tuple[int, int, str]:
    """Approved records outrank drafts; rejected never anchors (brief §7C)."""
    state_rank = {
        "locked": 0,
        "approved": 1,
        "unverified": 2,
        "draft": 3,
        "rejected": 9,
    }.get(asset.state, 5)
    return (state_rank, asset.reference_priority, asset.display_name.lower())


def best_asset(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    categories: Iterable[str] | None = None,
    roles: Iterable[str] | None = None,
    product_id: str | None = None,
    character_id: str | None = None,
) -> VaultAsset | None:
    """Highest-precedence non-rejected asset for a slot."""
    candidates = [
        a for a in search(
            brand_id,
            categories=categories,
            roles=roles,
            product_id=product_id,
            character_id=character_id,
        )
        if a.state != "rejected"
    ]
    return candidates[0] if candidates else None


def locked_mark(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    tag: str,
) -> VaultAsset | None:
    """A locked official mark by tag, e.g. ``quatrefoil`` or ``signature``."""
    for asset in search(
        brand_id, categories=["official_marks"], states=["locked", "approved"]
    ):
        if tag in asset.tags or tag in asset.display_name.lower():
            return asset
    return None


def linked_brand_assets(brand_id: str = DEFAULT_BRAND_ID) -> list[dict[str, Any]]:
    """Existing Studio brand assets, surfaced without duplicating them."""
    rows: list[dict[str, Any]] = []
    for asset in studio_brand_assets.list_assets(brand_id):
        rows.append(
            {
                "asset_id": asset.asset_id,
                "display_name": asset.display_name,
                "role": asset.role,
                "source": "studio.brand_assets",
                "path": studio_brand_assets.resolve_asset_path(asset),
            }
        )
    return rows


def stats(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, Any]:
    assets = list_assets(brand_id)
    by_category = {category: 0 for category in VAULT_CATEGORIES}
    for asset in assets:
        by_category[asset.category] = by_category.get(asset.category, 0) + 1
    return {
        "total": len(assets),
        "by_category": by_category,
        "locked": sum(1 for a in assets if a.state == "locked"),
        "private": sum(1 for a in assets if a.is_private),
    }
