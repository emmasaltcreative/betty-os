"""Private data root for BettyOS.

The GitHub repository is public. Family photographs, proprietary product
masters, label print art and generated illustration bytes must never land in
version control. Everything written by the Illustration Studio therefore goes
under a configurable data root that lives outside the repository tree by
default-of-intent, and is gitignored when it sits inside it.

Resolution order:
  1. ``BETTY_OS_DATA_DIR`` environment variable (absolute or relative path).
  2. ``<repo>/.betty_data`` — gitignored fallback so a fresh clone still runs.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.common import DEFAULT_BRAND_ID, ROOT

DATA_DIR_ENV = "BETTY_OS_DATA_DIR"
DEFAULT_DATA_DIRNAME = ".betty_data"


def data_root(*, create: bool = True) -> Path:
    """Return the private data root, creating it on first use."""
    raw = (os.getenv(DATA_DIR_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else ROOT / DEFAULT_DATA_DIRNAME
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def is_configured() -> bool:
    """True when the owner has pointed the data root outside the repo."""
    return bool((os.getenv(DATA_DIR_ENV) or "").strip())


def is_inside_repo() -> bool:
    """True when the active data root sits inside the repository tree."""
    try:
        data_root(create=False).resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def brand_data_dir(brand_id: str = DEFAULT_BRAND_ID, *, create: bool = True) -> Path:
    path = data_root(create=create) / "brands" / brand_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def vault_dir(brand_id: str = DEFAULT_BRAND_ID, *, create: bool = True) -> Path:
    """Binary originals for vault assets."""
    path = brand_data_dir(brand_id, create=create) / "vault"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def vault_index(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_data_dir(brand_id) / "vault_index.json"


def vault_thumbnails_dir(brand_id: str = DEFAULT_BRAND_ID, *, create: bool = True) -> Path:
    path = brand_data_dir(brand_id, create=create) / "vault_thumbnails"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def illustration_dir(brand_id: str = DEFAULT_BRAND_ID, *, create: bool = True) -> Path:
    """Generated illustration versions, overlays and exports."""
    path = brand_data_dir(brand_id, create=create) / "illustration"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def illustration_index(brand_id: str = DEFAULT_BRAND_ID) -> Path:
    return brand_data_dir(brand_id) / "illustration_versions.json"


def relative_to_data_root(path: Path) -> str:
    """Store paths relative to the data root so the root stays relocatable."""
    try:
        return Path(path).resolve().relative_to(data_root(create=False).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def resolve_data_path(stored: str) -> Path:
    """Inverse of :func:`relative_to_data_root`."""
    path = Path(stored)
    if path.is_absolute():
        return path
    return data_root(create=False) / path


def redact(path: Path | str) -> str:
    """Log-safe rendering of a private path — never leak the real location."""
    name = Path(path).name
    return f"<data_root>/…/{name}" if name else "<data_root>"
