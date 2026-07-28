"""Path helpers for Studio storage — adapted to existing outputs/ layout."""

from __future__ import annotations

import re
from pathlib import Path

from src.common import BRANDS_DIR, DEFAULT_BRAND_ID

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def brand_studio_dir(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    path = BRANDS_DIR / brand_id / "studio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def brand_assets_dir(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    path = brand_studio_dir(brand_id) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def brand_assets_index(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "brand_assets.json"


def color_recipes_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "color_recipes.json"


def luts_dir(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    path = brand_studio_dir(brand_id) / "luts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def luts_index(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "luts.json"


def guardrails_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "production_guardrails.json"


def capabilities_path(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_studio_dir(brand_id) / "capabilities.json"


def preview_cache_dir(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    path = brand_studio_dir(brand_id) / "preview_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def render_studio_root(render_folder: Path, *, create: bool = True) -> Path:
    """Studio root beside a render version's output directory."""
    path = Path(render_folder) / "studio"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def drafts_dir(render_folder: Path) -> Path:
    path = render_studio_root(render_folder) / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def finish_version_dir(render_folder: Path, finish_version_id: str) -> Path:
    return render_studio_root(render_folder, create=False) / finish_version_id


def sanitize_filename(name: str, *, fallback: str = "asset") -> str:
    cleaned = SAFE_NAME_RE.sub("_", (name or "").strip()).strip("._")
    return cleaned or fallback


def download_basename(
    campaign: str,
    content_piece: str,
    recipe: str,
    finish_version_id: str,
    extension: str,
) -> str:
    parts = [
        sanitize_filename(campaign, fallback="campaign"),
        sanitize_filename(content_piece, fallback="piece"),
        sanitize_filename(recipe, fallback="recipe"),
        sanitize_filename(finish_version_id, fallback="finish"),
    ]
    ext = extension if extension.startswith(".") else f".{extension}"
    return "_".join(parts) + ext.lower()


def is_under_studio(path: Path) -> bool:
    """True when path sits inside a Studio outputs/drafts tree."""
    return "studio" in Path(path).parts
