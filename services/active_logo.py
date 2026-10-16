"""Canonical active brand-mark resolver for BettyOS.

Settings (and Library Brand Setup) select one active mark. Studio, revisions,
Brand Check, campaign documents, and delivery packages all resolve through
this module — never by guessing paths or hardcoding seed assets.

Historical renders keep whatever logo was baked into them; only new work
reads the active mark.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.common import DEFAULT_BRAND_ID, ROOT
from studio.brand_assets import (
    analyze_mark_pixels,
    get_asset,
    is_suitable_transparent_mark,
    resolve_asset_path,
    select_suitable_logo_candidates,
)
from studio.models import BrandAssetRecord, utc_now_iso
from studio.paths import brand_assets_dir, brand_assets_index
from src.persistence import atomic_write_json, load_json

Severity = Literal["pass", "warning", "blocking"]


@dataclass
class LogoSuitability:
    suitable: bool
    severity: Severity
    reasons: list[str] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActiveLogoMark:
    """Resolved active brand mark — the single source of truth for new work."""

    asset_id: str
    display_name: str
    storage_ref: str  # repo-relative path; never expose absolute paths in packages
    file_type: str
    width: int | None
    height: int | None
    suitable: bool
    validation: LogoSuitability
    selected_at: str
    brand_id: str
    lineage_id: str
    mime_type: str = ""
    role: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "display_name": self.display_name,
            "storage_ref": self.storage_ref,
            "file_type": self.file_type,
            "width": self.width,
            "height": self.height,
            "suitable": self.suitable,
            "validation": self.validation.as_dict(),
            "selected_at": self.selected_at,
            "brand_id": self.brand_id,
            "lineage_id": self.lineage_id,
            "mime_type": self.mime_type,
            "role": self.role,
        }

    @property
    def absolute_path(self) -> Path:
        path = Path(self.storage_ref)
        return path if path.is_absolute() else ROOT / path


def _index(brand_id: str) -> dict[str, Any]:
    data = load_json(brand_assets_index(brand_id), default={"assets": []})
    return data if isinstance(data, dict) else {"assets": []}


def _save_index(brand_id: str, data: dict[str, Any]) -> None:
    data["brand_id"] = brand_id
    data["updated_at"] = utc_now_iso()
    atomic_write_json(brand_assets_index(brand_id), data)


def evaluate_logo_suitability(path: Path | None) -> LogoSuitability:
    """Meaningful suitability check — not filename or seed-path based."""
    reasons: list[str] = []
    if path is None or not Path(path).is_file():
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=["The image cannot be read."],
            analysis={},
        )

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=[f"Unsupported logo format: {suffix or 'unknown'}."],
        )

    if path.stat().st_size <= 0:
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=["The image file is empty."],
        )

    # SVG structural checks before raster heuristics.
    if suffix == ".svg":
        svg_result = _evaluate_svg(path)
        if not svg_result.suitable:
            return svg_result

    analysis = analyze_mark_pixels(path)
    if not analysis.get("ok"):
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=[analysis.get("reason") or "The image cannot be read."],
            analysis=analysis,
        )

    if analysis.get("looks_like_solid_rectangle"):
        reasons.append(
            "This image is nearly a single flat color and does not appear to contain a usable logo."
        )
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=reasons,
            analysis=analysis,
        )

    if not analysis.get("suitable_transparent_mark"):
        reasons.append(analysis.get("reason") or "Logo is not suitable for brand overlay use.")
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=reasons,
            analysis=analysis,
        )

    width = analysis.get("width")
    height = analysis.get("height")
    # Raster dimension hints from PIL path are in analyze; SVG may omit.
    if suffix != ".svg":
        try:
            from PIL import Image

            with Image.open(path) as img:
                width, height = img.size
        except Exception:
            pass
        if width and height and min(width, height) < 24:
            return LogoSuitability(
                suitable=False,
                severity="blocking",
                reasons=["The image is too small for campaign document use."],
                analysis=analysis,
            )
        if width and height and min(width, height) < 48:
            reasons.append("The logo may be difficult to read at the required overlay size.")
            return LogoSuitability(
                suitable=True,
                severity="warning",
                reasons=reasons,
                analysis=analysis,
            )

    return LogoSuitability(
        suitable=True,
        severity="pass",
        reasons=["Active Settings logo is suitable for brand use."],
        analysis=analysis,
    )


def _evaluate_svg(path: Path) -> LogoSuitability:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=["The image cannot be read."],
        )
    lowered = text.lower()
    if "<svg" not in lowered:
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=["SVG does not contain a valid root element."],
        )
    if "<script" in lowered or "javascript:" in lowered:
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=["SVG contains script content and cannot be accepted."],
        )

    shapes = re.findall(r"<(path|circle|ellipse|polygon|polyline|rect|g)\b", lowered)
    if not shapes:
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=["The image is an empty transparent canvas."],
        )

    # Plain single rectangle — same class of failure as the jade PNG placeholder.
    meaningful = [s for s in shapes if s != "g"]
    if meaningful == ["rect"] or (len(meaningful) == 1 and meaningful[0] == "rect"):
        return LogoSuitability(
            suitable=False,
            severity="blocking",
            reasons=[
                "This image is nearly a single flat color and does not appear to contain a usable logo."
            ],
            analysis={"looks_like_solid_rectangle": True, "suitable_transparent_mark": False},
        )

    return LogoSuitability(
        suitable=True,
        severity="pass",
        reasons=["SVG mark has drawable artwork."],
        analysis={"suitable_transparent_mark": True, "ok": True},
    )


def _mark_from_asset(
    asset: BrandAssetRecord,
    *,
    selected_at: str,
    validation: LogoSuitability | None = None,
) -> ActiveLogoMark:
    path = resolve_asset_path(asset)
    validation = validation or evaluate_logo_suitability(path)
    stamp = selected_at or asset.updated_at or utc_now_iso()
    return ActiveLogoMark(
        asset_id=asset.asset_id,
        display_name=asset.display_name,
        storage_ref=asset.file_path,
        file_type=Path(asset.file_path).suffix.lower().lstrip(".") or "unknown",
        width=asset.width,
        height=asset.height,
        suitable=validation.suitable,
        validation=validation,
        selected_at=stamp,
        brand_id=asset.brand_id,
        lineage_id=f"logo:{asset.asset_id}@{stamp}",
        mime_type=asset.mime_type,
        role=asset.role,
    )


def resolve_active_logo(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    bootstrap: bool = True,
) -> ActiveLogoMark | None:
    """Return the canonical active brand mark, or None if none is valid."""
    data = _index(brand_id)
    active_id = data.get("active_brand_mark_id")
    selected_at = str(data.get("active_brand_mark_selected_at") or "")

    if active_id:
        asset = get_asset(str(active_id), brand_id)
        if asset is not None and asset.active and not asset.archived:
            mark = _mark_from_asset(asset, selected_at=selected_at)
            if mark.suitable:
                return mark
            # Active pointer exists but asset became unsuitable — do not invent a fallback silently.
            return mark

    if not bootstrap:
        return None

    # Bootstrap once: promote the best suitable candidate and persist the pointer.
    candidates = select_suitable_logo_candidates(brand_id)
    if not candidates:
        return None
    best = candidates[0]
    return set_active_brand_mark(best.asset_id, brand_id=brand_id, force=False)


def set_active_brand_mark(
    asset_id: str,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    force: bool = False,
) -> ActiveLogoMark:
    """Validate and activate a brand mark. Invalid uploads do not displace the last valid mark."""
    asset = get_asset(asset_id, brand_id)
    if asset is None:
        raise KeyError(f"Brand asset not found: {asset_id}")
    if asset.archived or not asset.active:
        raise ValueError("Archived or inactive assets cannot become the active brand mark.")

    validation = evaluate_logo_suitability(resolve_asset_path(asset))
    if not validation.suitable and not force:
        raise ValueError("; ".join(validation.reasons) or "Logo is not suitable.")

    stamp = utc_now_iso()
    data = _index(brand_id)
    data["active_brand_mark_id"] = asset_id
    data["active_brand_mark_selected_at"] = stamp
    # Keep role-default in sync for Studio role lookups.
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            continue
        if item.get("asset_id") == asset_id:
            item["is_default_for_role"] = True
            item["updated_at"] = stamp
        elif item.get("role") == asset.role:
            item["is_default_for_role"] = False
    _save_index(brand_id, data)
    return _mark_from_asset(asset, selected_at=stamp, validation=validation)


def clear_active_brand_mark(brand_id: str = DEFAULT_BRAND_ID) -> None:
    data = _index(brand_id)
    data.pop("active_brand_mark_id", None)
    data.pop("active_brand_mark_selected_at", None)
    _save_index(brand_id, data)


def remove_active_brand_mark(
    brand_id: str = DEFAULT_BRAND_ID,
) -> ActiveLogoMark | None:
    """Clear the active pointer; optionally fall back to next suitable candidate."""
    clear_active_brand_mark(brand_id)
    candidates = select_suitable_logo_candidates(brand_id)
    if not candidates:
        return None
    return set_active_brand_mark(candidates[0].asset_id, brand_id=brand_id)


def rasterize_logo_png(mark: ActiveLogoMark, *, max_edge: int = 512) -> Path | None:
    """Produce a PNG suitable for PDF/DOCX embedding. Caches beside the asset."""
    source = mark.absolute_path
    if not source.is_file():
        return None
    cache = brand_assets_dir(mark.brand_id) / f"{mark.asset_id}_doc_preview_{max_edge}.png"
    if cache.is_file() and cache.stat().st_mtime >= source.stat().st_mtime:
        return cache

    suffix = source.suffix.lower()
    try:
        if suffix == ".svg":
            # Prefer rsvg-convert when available (macOS Homebrew); fall back to none.
            rsvg = _which("rsvg-convert")
            if rsvg:
                subprocess.run(
                    [
                        rsvg,
                        "-w",
                        str(max_edge),
                        "-h",
                        str(max_edge),
                        "-f",
                        "png",
                        "-o",
                        str(cache),
                        str(source),
                    ],
                    check=True,
                    capture_output=True,
                )
                if cache.is_file():
                    return cache
            return None

        from PIL import Image

        with Image.open(source) as img:
            img = img.convert("RGBA")
            img.thumbnail((max_edge, max_edge))
            cache.parent.mkdir(parents=True, exist_ok=True)
            img.save(cache, format="PNG")
        return cache
    except Exception:
        return None


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)
