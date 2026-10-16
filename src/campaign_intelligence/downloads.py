"""Reliable local download helpers for Production Briefs and packages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def confirm_readable_file(path: Path) -> tuple[bool, str]:
    path = Path(path)
    if not path.is_file():
        return False, "File does not exist."
    try:
        data = path.read_bytes()
    except OSError as exc:
        return False, f"File is not readable: {exc}"
    if len(data) < 20:
        return False, "File is empty or incomplete."
    return True, human_size(len(data))


def show_in_finder(path: Path) -> tuple[bool, str]:
    """Reveal a file in Finder on macOS. No-op message on other platforms."""
    path = Path(path).resolve()
    if not path.exists():
        return False, "File not found."
    if sys.platform != "darwin":
        return False, "Show in Finder is available on macOS only."
    try:
        subprocess.run(
            ["open", "-R", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, "Revealed in Finder."
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, f"Could not open Finder: {exc}"
