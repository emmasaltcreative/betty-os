"""Persistent brand-asset library for Studio logo placement."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

from PIL import Image

from src.common import DEFAULT_BRAND_ID, ROOT, relative_to_root
from src.persistence import atomic_write_json, load_json
from studio.models import LOGO_PLACEMENTS, LOGO_ROLES, BrandAssetRecord, utc_now_iso
from studio.paths import brand_assets_dir, brand_assets_index, sanitize_filename

ROLE_LABELS = {
    "primary": "Primary Logo",
    "secondary": "Secondary Logo",
    "wordmark": "Wordmark",
    "emblem": "Emblem",
    "monogram": "Monogram",
    "watermark": "Watermark",
    "light": "Light Logo",
    "dark": "Dark Logo",
}

ALLOWED_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}


def _index_path(brand_id: str) -> Path:
    return brand_assets_index(brand_id)


def _load_raw(brand_id: str) -> dict:
    data = load_json(_index_path(brand_id), default={"assets": []})
    return data if isinstance(data, dict) else {"assets": []}


def _save_raw(brand_id: str, data: dict) -> None:
    data["brand_id"] = brand_id
    data["updated_at"] = utc_now_iso()
    atomic_write_json(_index_path(brand_id), data)


def list_assets(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    include_archived: bool = False,
) -> list[BrandAssetRecord]:
    raw = _load_raw(brand_id)
    assets = [BrandAssetRecord.from_dict(a) for a in raw.get("assets") or [] if isinstance(a, dict)]
    if include_archived:
        return assets
    return [a for a in assets if a.active and not a.archived]


def get_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord | None:
    for asset in list_assets(brand_id, include_archived=True):
        if asset.asset_id == asset_id:
            return asset
    return None


def resolve_asset_path(asset: BrandAssetRecord) -> Path:
    path = Path(asset.file_path)
    if not path.is_absolute():
        path = ROOT / path
    return path


def default_asset_for_role(role: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord | None:
    assets = [a for a in list_assets(brand_id) if a.role == role]
    for asset in assets:
        if asset.is_default_for_role:
            return asset
    return assets[0] if assets else None


def _probe_image(path: Path) -> tuple[int | None, int | None, bool]:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        text = path.read_text(encoding="utf-8", errors="ignore")
        has_transparency = True
        # Best-effort dimension parse; SVG may omit absolute size.
        width = height = None
        import re

        wb = re.search(r'width=["\']([\d.]+)', text)
        hb = re.search(r'height=["\']([\d.]+)', text)
        if wb and hb:
            try:
                width = int(float(wb.group(1)))
                height = int(float(hb.group(1)))
            except ValueError:
                pass
        return width, height, has_transparency

    with Image.open(path) as img:
        img.load()
        has_alpha = img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info)
        if has_alpha:
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            has_transparency = alpha.getextrema()[0] < 250
        else:
            has_transparency = False
        return img.width, img.height, has_transparency


def validate_upload(path: Path, *, role: str) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        errors.append("File is not readable.")
        return errors
    if path.stat().st_size <= 0:
        errors.append("File is empty.")
        return errors
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        errors.append(f"Unsupported format {suffix}. Use SVG, PNG, or JPG.")
        return errors
    if role not in LOGO_ROLES:
        errors.append(f"Unknown role: {role}")
    if suffix == ".svg":
        text = path.read_text(encoding="utf-8", errors="ignore").lstrip()
        if not text.startswith("<") or "<svg" not in text.lower():
            errors.append("SVG does not appear to contain a valid <svg> root.")
        lowered = text.lower()
        if "<script" in lowered or "javascript:" in lowered:
            errors.append("SVG contains script content and cannot be accepted.")
    else:
        try:
            with Image.open(path) as img:
                img.verify()
            width, height, has_transparency = _probe_image(path)
            if not width or not height:
                errors.append("Image dimensions could not be detected.")
            if suffix in {".jpg", ".jpeg"} and role in {"primary", "secondary", "wordmark", "light", "dark"}:
                if not has_transparency:
                    # Soft communication — not a hard fail
                    pass
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Image could not be decoded: {exc}")
    return errors


def upload_brand_asset(
    source: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    display_name: str,
    role: str,
    set_as_default: bool = False,
    original_filename: str | None = None,
) -> BrandAssetRecord:
    if role not in LOGO_ROLES:
        raise ValueError(f"Invalid role: {role}")
    source = Path(source)
    errors = validate_upload(source, role=role)
    hard = [e for e in errors if "JPG" not in e and "transparency" not in e.lower()]
    # validate_upload currently only returns hard errors for jpg transparency note as pass
    if hard:
        raise ValueError("; ".join(hard))

    asset_id = f"ba_{uuid4().hex[:10]}"
    safe = sanitize_filename(original_filename or source.name)
    dest_name = f"{asset_id}_{safe}"
    dest = brand_assets_dir(brand_id) / dest_name
    shutil.copy2(source, dest)

    width, height, has_transparency = _probe_image(dest)
    mime, _ = mimetypes.guess_type(dest.name)
    now = utc_now_iso()
    aspect = (width / height) if width and height else None

    if set_as_default:
        _clear_default_for_role(brand_id, role)

    record = BrandAssetRecord(
        asset_id=asset_id,
        brand_id=brand_id,
        display_name=display_name.strip() or ROLE_LABELS.get(role, role),
        role=role,
        file_path=relative_to_root(dest),
        original_filename=original_filename or source.name,
        mime_type=mime or "application/octet-stream",
        width=width,
        height=height,
        aspect_ratio=aspect,
        has_transparency=has_transparency,
        preferred_background="dark" if role == "light" else "light",
        minimum_display_width=48,
        default_opacity=0.85,
        default_size_percentage=18.0,
        allowed_placements=list(LOGO_PLACEMENTS),
        prohibited_placements=[],
        default_safe_margin=24.0,
        active=True,
        is_default_for_role=set_as_default or not any(
            a.role == role and a.is_default_for_role for a in list_assets(brand_id)
        ),
        created_at=now,
        updated_at=now,
        archived=False,
    )

    raw = _load_raw(brand_id)
    assets = list(raw.get("assets") or [])
    if record.is_default_for_role:
        for item in assets:
            if isinstance(item, dict) and item.get("role") == role:
                item["is_default_for_role"] = False
    assets.append(record.to_dict())
    raw["assets"] = assets
    _save_raw(brand_id, raw)
    saved = get_asset(asset_id, brand_id)
    if saved is None:
        raise RuntimeError("Brand asset write could not be verified.")
    return saved


def _clear_default_for_role(brand_id: str, role: str) -> None:
    raw = _load_raw(brand_id)
    for item in raw.get("assets") or []:
        if isinstance(item, dict) and item.get("role") == role:
            item["is_default_for_role"] = False
    _save_raw(brand_id, raw)


def rename_asset(asset_id: str, display_name: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord:
    return _update(asset_id, brand_id, display_name=display_name.strip())


def assign_role(asset_id: str, role: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord:
    if role not in LOGO_ROLES:
        raise ValueError(role)
    return _update(asset_id, brand_id, role=role)


def set_as_default(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord:
    asset = get_asset(asset_id, brand_id)
    if asset is None:
        raise KeyError(asset_id)
    _clear_default_for_role(brand_id, asset.role)
    return _update(asset_id, brand_id, is_default_for_role=True)


def edit_usage_rules(
    asset_id: str,
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    minimum_display_width: int | None = None,
    default_opacity: float | None = None,
    default_size_percentage: float | None = None,
    default_safe_margin: float | None = None,
    allowed_placements: list[str] | None = None,
    prohibited_placements: list[str] | None = None,
) -> BrandAssetRecord:
    updates: dict = {}
    if minimum_display_width is not None:
        updates["minimum_display_width"] = int(minimum_display_width)
    if default_opacity is not None:
        updates["default_opacity"] = float(default_opacity)
    if default_size_percentage is not None:
        updates["default_size_percentage"] = float(default_size_percentage)
    if default_safe_margin is not None:
        updates["default_safe_margin"] = float(default_safe_margin)
    if allowed_placements is not None:
        updates["allowed_placements"] = list(allowed_placements)
    if prohibited_placements is not None:
        updates["prohibited_placements"] = list(prohibited_placements)
    return _update(asset_id, brand_id, **updates)


def archive_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord:
    return _update(asset_id, brand_id, archived=True, active=False)


def restore_asset(asset_id: str, brand_id: str = DEFAULT_BRAND_ID) -> BrandAssetRecord:
    return _update(asset_id, brand_id, archived=False, active=True)


def _update(asset_id: str, brand_id: str, **updates) -> BrandAssetRecord:
    raw = _load_raw(brand_id)
    found = False
    for item in raw.get("assets") or []:
        if not isinstance(item, dict):
            continue
        if item.get("asset_id") != asset_id:
            continue
        item.update(updates)
        item["updated_at"] = utc_now_iso()
        found = True
        break
    if not found:
        raise KeyError(asset_id)
    _save_raw(brand_id, raw)
    asset = get_asset(asset_id, brand_id)
    if asset is None:
        raise RuntimeError("Asset update could not be verified.")
    return asset


def jpg_transparency_note(path: Path) -> str | None:
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        return None
    return (
        "JPG does not support transparency. Prefer SVG or transparent PNG for logos "
        "that sit over imagery."
    )


# Preferred roles when Automatic Studio selects a mark.
PREFERRED_MARK_ROLES: tuple[str, ...] = (
    "wordmark",
    "monogram",
    "light",
    "dark",
    "primary",
    "secondary",
    "watermark",
    "emblem",
)

# Minimum safe inset for auto-applied marks (readable spacing, not a UI badge).
AUTO_LOGO_MIN_MARGIN_PX = 48.0
AUTO_LOGO_MIN_MARGIN_RATIO = 0.04  # 4% of canvas width
AUTO_LOGO_MIN_WIDTH_PX = 72


def analyze_mark_pixels(path: Path) -> dict:
    """Classify whether a logo file is a real transparent mark or a solid badge.

    The Oh Betty seed asset is a jade rectangle with only edge padding alpha —
    that must not be treated as a suitable brand wordmark.
    """
    path = Path(path)
    result = {
        "path": str(path),
        "ok": False,
        "has_alpha_channel": False,
        "transparent_pixel_ratio": 0.0,
        "opaque_pixel_ratio": 0.0,
        "dominant_opaque_share": 0.0,
        "unique_opaque_colors": 0,
        "bbox_fill_ratio": 0.0,
        "looks_like_solid_rectangle": False,
        "suitable_transparent_mark": False,
        "reason": "",
    }
    if not path.is_file():
        result["reason"] = "Logo file is missing."
        return result
    if path.suffix.lower() == ".svg":
        result["ok"] = True
        result["has_alpha_channel"] = True
        result["suitable_transparent_mark"] = True
        result["reason"] = "SVG marks are treated as transparent vector artwork."
        return result
    try:
        with Image.open(path) as img:
            img.load()
            rgba = img.convert("RGBA")
            width, height = rgba.size
            pixels = rgba.load()
    except OSError as exc:
        result["reason"] = f"Logo could not be read: {exc}"
        return result

    total = width * height or 1
    # Soft-opaque samples (a >= 200) capture fills that are deliberately
    # semi-transparent badges (e.g. jade at alpha 230), not only a=255.
    fill_colors: list[tuple[int, int, int]] = []
    soft_opaque = 0
    transparent = 0
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a < 32:
                transparent += 1
                continue
            if a >= 200:
                soft_opaque += 1
                fill_colors.append((r, g, b))
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    result["ok"] = True
    result["has_alpha_channel"] = True
    result["transparent_pixel_ratio"] = transparent / total
    result["opaque_pixel_ratio"] = soft_opaque / total

    if soft_opaque == 0:
        result["reason"] = "Logo has no opaque pixels."
        return result

    buckets: dict[tuple[int, int, int], int] = {}
    for r, g, b in fill_colors:
        key = (r // 12 * 12, g // 12 * 12, b // 12 * 12)
        buckets[key] = buckets.get(key, 0) + 1
    dominant = max(buckets.values()) if buckets else 0
    result["unique_opaque_colors"] = len(buckets)
    result["dominant_opaque_share"] = dominant / soft_opaque

    if max_x >= min_x and max_y >= min_y:
        bbox_area = max(1, (max_x - min_x + 1) * (max_y - min_y + 1))
        result["bbox_fill_ratio"] = soft_opaque / bbox_area
    else:
        result["bbox_fill_ratio"] = 0.0

    # Solid rectangular badge: one dominant fill packing the opaque bbox.
    # Anti-aliased edge crumbs can inflate unique_opaque_colors, so dominant
    # share + bbox fill are the primary signals.
    looks_badge = (
        result["dominant_opaque_share"] >= 0.85
        and result["bbox_fill_ratio"] >= 0.80
        and result["opaque_pixel_ratio"] >= 0.40
    )
    result["looks_like_solid_rectangle"] = looks_badge

    if looks_badge:
        result["suitable_transparent_mark"] = False
        result["reason"] = (
            "Logo looks like a solid-color rectangular badge rather than a "
            "transparent wordmark or monogram."
        )
        return result

    if result["transparent_pixel_ratio"] < 0.05 and result["dominant_opaque_share"] >= 0.9:
        result["suitable_transparent_mark"] = False
        result["reason"] = "Logo asset lacks meaningful transparency."
        return result

    result["suitable_transparent_mark"] = True
    result["reason"] = "Transparent mark with varied artwork."
    return result


def is_suitable_transparent_mark(asset: BrandAssetRecord) -> bool:
    if asset is None:
        return False
    if not asset.has_transparency and Path(asset.file_path).suffix.lower() not in {".svg"}:
        # JPG / opaque raster — not preferred for overlay.
        analysis = analyze_mark_pixels(resolve_asset_path(asset))
        return bool(analysis.get("suitable_transparent_mark"))
    analysis = analyze_mark_pixels(resolve_asset_path(asset))
    return bool(analysis.get("suitable_transparent_mark"))


def select_best_logo_asset(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    preferred_roles: tuple[str, ...] | None = None,
) -> BrandAssetRecord | None:
    """Pick the best transparent mark, preferring wordmark / monogram / light / dark."""
    roles = preferred_roles or PREFERRED_MARK_ROLES
    seen: set[str] = set()
    for role in roles:
        asset = default_asset_for_role(role, brand_id)
        if asset is None or asset.asset_id in seen:
            continue
        seen.add(asset.asset_id)
        if is_suitable_transparent_mark(asset):
            return asset
    # Fall through: any active asset that is suitable, regardless of role order.
    for asset in list_assets(brand_id):
        if asset.asset_id in seen:
            continue
        if is_suitable_transparent_mark(asset):
            return asset
    return None


def auto_logo_safe_margin_px(canvas_width: int | None = None) -> float:
    """Readable inset so auto marks never sit flush against the edge."""
    if canvas_width and canvas_width > 0:
        return max(AUTO_LOGO_MIN_MARGIN_PX, float(canvas_width) * AUTO_LOGO_MIN_MARGIN_RATIO)
    return AUTO_LOGO_MIN_MARGIN_PX
