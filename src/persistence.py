"""Atomic file writes for BettyOS persistent state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write text atomically: temp file in the same directory, then replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return path


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> Path:
    """Serialize JSON and write atomically."""
    payload = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    return atomic_write_text(path, payload)


def load_json(path: Path, default: Any = None) -> Any:
    """Load JSON from disk; return default when missing or invalid."""
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
