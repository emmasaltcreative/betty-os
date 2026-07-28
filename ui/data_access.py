"""Read-only access to files on disk for the BettyOS interface."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.brand import BRAND_BRAIN_FILES, load_brand_brain
from src.common import (
    ASSETS_PATH,
    BRANDS_DIR,
    DEFAULT_BRAND_ID,
    OUTPUTS_DIR,
    PRODUCTION_DIR,
    ROOT,
    THUMBNAILS_DIR,
    BettyOSError,
    find_latest_content_package,
    find_latest_render_dirs,
)


def brand_display_name(brand_id: str = DEFAULT_BRAND_ID) -> str:
    return brand_id.replace("_", " ").title()


def list_content_packages() -> list[Path]:
    return sorted(OUTPUTS_DIR.glob("*_content_package.md"), reverse=True)


def load_text(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load_latest_package_text() -> tuple[Path | None, str | None]:
    try:
        path = find_latest_content_package()
    except BettyOSError:
        return None, None
    return path, path.read_text(encoding="utf-8")


def load_package_by_name(name: str) -> tuple[Path | None, str | None]:
    path = OUTPUTS_DIR / name
    if not path.is_file():
        return None, None
    return path, path.read_text(encoding="utf-8")


# --- Review -----------------------------------------------------------------

def load_latest_scores() -> dict[str, Any] | None:
    path = OUTPUTS_DIR / "latest_scores.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    from review.scoring import ensure_scores_recommendations

    return ensure_scores_recommendations(data)


def save_latest_scores(data: dict[str, Any]) -> Path:
    from src.persistence import atomic_write_json

    path = OUTPUTS_DIR / "latest_scores.json"
    atomic_write_json(path, data)
    if load_latest_scores() is None:
        raise RuntimeError("The review file could not be read back after saving.")
    return path


def load_latest_review_markdown() -> str | None:
    return load_text(OUTPUTS_DIR / "latest_review.md")


# --- Environment ------------------------------------------------------------

def api_key_configured() -> bool:
    load_dotenv(ROOT / ".env")
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def friendly_path(path: Path | None) -> str:
    """A path a person can read: home-relative, and never the bare `.`."""
    if path is None:
        return "—"
    resolved = path.resolve()
    try:
        return f"~/{resolved.relative_to(Path.home()).as_posix()}"
    except ValueError:
        return resolved.as_posix()


def list_render_dirs_for_campaign(campaign_dir: Path | None) -> list[Path]:
    """Render folders the review engine understands (it looks for legacy names)."""
    if campaign_dir is None:
        return find_latest_render_dirs()
    found: list[Path] = []
    for name in ("ritual_reel", "page_turn_loop"):
        path = campaign_dir / name
        if path.is_dir():
            found.append(path)
    return found


# --- Brand guide ------------------------------------------------------------

BRAND_DOC_LABELS = {
    "identity.md": "Identity",
    "audience.md": "Audience",
    "products.md": "Products",
    "voice.md": "Voice",
    "visual_language.md": "Visual Language",
    "business_strategy.md": "Business Strategy",
    "creative_principles.md": "Creative Principles",
}


def load_brand_documents(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, str]:
    brand_dir = BRANDS_DIR / brand_id
    docs: dict[str, str] = {}
    for filename in BRAND_BRAIN_FILES:
        path = brand_dir / filename
        label = BRAND_DOC_LABELS.get(filename, filename)
        docs[label] = (
            path.read_text(encoding="utf-8") if path.is_file() else "_Not written yet._"
        )
    return docs


def brand_guide_loaded(brand_id: str = DEFAULT_BRAND_ID) -> bool:
    try:
        load_brand_brain(brand_id)
        return True
    except BettyOSError:
        return False


# --- Asset library ----------------------------------------------------------

@dataclass
class AssetSummary:
    key: str
    filename: str
    asset_type: str
    summary: str
    products: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    thumbnail: Path | None = None
    exists: bool = False


def _thumbnail_for(key: str) -> Path | None:
    if not THUMBNAILS_DIR.is_dir():
        return None
    stem = key.replace("/", "_")
    matches = sorted(THUMBNAILS_DIR.glob(f"{stem}_*.jpg"))
    return matches[len(matches) // 2] if matches else None


def count_indexed_assets() -> int:
    if not ASSETS_PATH.is_file():
        return 0
    try:
        data = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return len(data) if isinstance(data, dict) else 0


def load_asset_summaries() -> list[AssetSummary]:
    if not ASSETS_PATH.is_file():
        return []
    try:
        data = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []

    summaries: list[AssetSummary] = []
    for key, raw in sorted(data.items()):
        if not isinstance(raw, dict):
            continue
        summaries.append(
            AssetSummary(
                key=str(key),
                filename=str(raw.get("filename") or Path(str(key)).name),
                asset_type=str(raw.get("asset_type") or "unknown"),
                summary=str(raw.get("summary") or ""),
                products=[str(p) for p in raw.get("products") or []],
                objects=[str(o) for o in raw.get("objects") or []],
                thumbnail=_thumbnail_for(str(key)),
                exists=(ROOT / str(key)).exists(),
            )
        )
    return summaries


# --- Production rules -------------------------------------------------------

def _load_production_json(name: str) -> dict[str, Any]:
    path = PRODUCTION_DIR / name
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def production_rules() -> list[tuple[str, list[tuple[str, str]]]]:
    """Production constraints and output standards in readable form."""
    exports = _load_production_json("exports.json")
    layout = _load_production_json("layout.json")
    typography = _load_production_json("typography.json")
    colors = _load_production_json("colors.json")
    animation = _load_production_json("animation.json")
    defaults = _load_production_json("global_defaults.json")
    safe = _load_production_json("safe_zones.json")

    def dimension() -> str:
        width, height = exports.get("width"), exports.get("height")
        return f"{width} × {height}" if width and height else "—"

    margins = layout.get("minimum_margins") or {}
    audio = (exports.get("audio") or {}).get("behavior") or "—"
    compression = exports.get("compression") or {}
    shadow = colors.get("shadow") or {}

    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Output standard",
            [
                ("Frame size", dimension()),
                ("Frame rate", f"{exports.get('fps')} fps" if exports.get("fps") else "—"),
                ("Video codec", str(exports.get("codec") or "—")),
                ("Bitrate", str(exports.get("bitrate") or "—")),
                ("Quality", f"CRF {compression.get('crf')}" if compression.get("crf") else "—"),
                ("Audio", "Removed" if audio == "remove" else str(audio).title()),
            ],
        ),
        (
            "Layout",
            [
                ("Alignment", str(layout.get("alignment") or "—").title()),
                (
                    "Maximum text width",
                    f"{layout.get('maximum_text_width')} px"
                    if layout.get("maximum_text_width")
                    else "—",
                ),
                (
                    "Minimum margins",
                    ", ".join(f"{k} {v}px" for k, v in margins.items()) or "—",
                ),
                ("Default platform", str(safe.get("default_platform") or "—").title()),
                (
                    "Words per screen",
                    str(defaults.get("maximum_words_per_screen") or "—"),
                ),
            ],
        ),
        (
            "Typography",
            [
                ("Primary typeface", str((typography.get("primary_font") or {}).get("name") or "—")),
                (
                    "Secondary typeface",
                    str((typography.get("secondary_font") or {}).get("name") or "—"),
                ),
                ("Hook size", str((typography.get("hook") or {}).get("size") or "—")),
                ("Footer size", str((typography.get("footer") or {}).get("size") or "—")),
                ("Call-to-action size", str((typography.get("cta") or {}).get("size") or "—")),
            ],
        ),
        (
            "Colour and contrast",
            [
                ("Primary text", str(colors.get("primary_text_color") or "—").title()),
                (
                    "Text opacity",
                    f"{float(colors.get('text_opacity', 0)) * 100:.0f}%"
                    if colors.get("text_opacity")
                    else "—",
                ),
                ("Text shadow", "On" if shadow.get("enabled") else "Off"),
                (
                    "Background wash",
                    "On" if (colors.get("background_wash") or {}).get("enabled") else "Off",
                ),
            ],
        ),
        (
            "Motion and pacing",
            [
                ("Pacing", str(defaults.get("preferred_pacing") or "—").title()),
                ("Transitions", str(defaults.get("transition_style") or "—").title()),
                (
                    "Opening fade",
                    f"{animation.get('opening_fade_seconds')}s"
                    if animation.get("opening_fade_seconds") is not None
                    else "—",
                ),
                (
                    "Closing fade",
                    f"{animation.get('closing_fade_seconds')}s"
                    if animation.get("closing_fade_seconds") is not None
                    else "—",
                ),
                (
                    "Call-to-action appears",
                    f"{animation.get('cta_appear_from_end_seconds')}s before the end"
                    if animation.get("cta_appear_from_end_seconds") is not None
                    else "—",
                ),
                ("Crop", str(defaults.get("preferred_crop_strategy") or "—").replace("_", " ").title()),
            ],
        ),
    ]
    return sections


def production_style_guide() -> str | None:
    return load_text(PRODUCTION_DIR / "style_guide.md")
