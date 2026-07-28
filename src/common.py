"""Shared paths, timestamps, and lookup helpers for BettyOS."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
LIBRARY_DIR = ROOT / "library"
ASSETS_PATH = LIBRARY_DIR / "assets.json"
THUMBNAILS_DIR = LIBRARY_DIR / "thumbnails"
BRANDS_DIR = ROOT / "brands"
PRODUCTION_DIR = ROOT / "production"
ASSETS_MEDIA_DIR = ROOT / "assets"

PAGE_TURN_TEMPLATE_PATH = PRODUCTION_DIR / "templates" / "page_turn_loop.json"
RITUAL_REEL_TEMPLATE_PATH = PRODUCTION_DIR / "templates" / "ritual_reel.json"
PAGE_TURN_SOURCE = ASSETS_MEDIA_DIR / "reading-hour-shoot" / "IMG_2545.mov"

DEFAULT_BRAND_ID = "oh_betty_jaletti"

# Predictable output naming: always include seconds to avoid collisions.
STAMP_FORMAT = "%Y-%m-%d_%H%M%S"


class BettyOSError(Exception):
    """User-facing BettyOS error with an optional recovery hint."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


def timestamp_stamp() -> str:
    """Return a filesystem-safe timestamp used in output folder/file names."""
    return datetime.now().strftime(STAMP_FORMAT)


def ensure_outputs_dir() -> Path:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUTS_DIR


def relative_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def find_latest_content_package() -> Path:
    ensure_outputs_dir()
    packages = sorted(OUTPUTS_DIR.glob("*_content_package.md"))
    if not packages:
        raise BettyOSError(
            "No content package found.",
            hint="Run: python3 main.py repurpose",
        )
    return packages[-1]


def find_latest_campaign_dir() -> Path | None:
    ensure_outputs_dir()
    campaigns = sorted(p for p in OUTPUTS_DIR.glob("*_campaign") if p.is_dir())
    return campaigns[-1] if campaigns else None


def require_latest_campaign_dir() -> Path:
    campaign = find_latest_campaign_dir()
    if campaign is None:
        raise BettyOSError(
            "No campaign folder found.",
            hint="Run: python3 main.py create all",
        )
    return campaign


def find_latest_render_dirs() -> list[Path]:
    """Latest render folders — prefer campaign subfolders, else top-level singles."""
    ensure_outputs_dir()
    campaign = find_latest_campaign_dir()
    if campaign is not None:
        campaign_renders = []
        for name in ("ritual_reel", "page_turn_loop"):
            path = campaign / name
            if path.is_dir() and (
                any(path.glob("*.mp4")) or any(path.glob("*.mov")) or (path / "caption.md").is_file()
            ):
                campaign_renders.append(path)
        if campaign_renders:
            return campaign_renders

    found: list[Path] = []
    for suffix in ("_ritual_reel", "_page_turn_loop"):
        dirs = sorted(p for p in OUTPUTS_DIR.glob(f"*{suffix}") if p.is_dir())
        if dirs:
            found.append(dirs[-1])
    return found


def campaign_render_dir(campaign_dir: Path, folder_name: str) -> Path:
    """Canonical render subfolder inside a campaign."""
    return campaign_dir / folder_name


def single_render_dir(piece_folder: str) -> Path:
    """Top-level folder for a single-render command."""
    return ensure_outputs_dir() / f"{timestamp_stamp()}_{piece_folder}"


def new_campaign_dir() -> Path:
    path = ensure_outputs_dir() / f"{timestamp_stamp()}_campaign"
    path.mkdir(parents=True, exist_ok=True)
    return path
