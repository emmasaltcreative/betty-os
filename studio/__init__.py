"""BettyOS Studio — deterministic, non-destructive finishing of existing renders."""

from __future__ import annotations

__all__ = [
    "SUPPORTED_STATIC",
    "SUPPORTED_VIDEO",
]

SUPPORTED_STATIC = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_VIDEO = {".mp4", ".mov"}
