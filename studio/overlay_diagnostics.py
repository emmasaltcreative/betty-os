"""Diagnostics for every visual overlay Studio writes into finished media.

Temporary but durable trail so we can prove which function stamped pixels.
Written beside each finish as `overlay_diagnostics.json` when a work_dir is known,
and always accumulated in-process for the current render.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OverlayEvent:
    source_function: str
    kind: str  # logo | skipped_logo | cta | watermark | other
    asset_path: str | None = None
    asset_id: str | None = None
    position: tuple[int, int] | None = None
    dimensions: tuple[int, int] | None = None
    opacity: float | None = None
    reason: str = ""
    applied: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.position is not None:
            payload["position"] = {"x": self.position[0], "y": self.position[1]}
        if self.dimensions is not None:
            payload["dimensions"] = {
                "width": self.dimensions[0],
                "height": self.dimensions[1],
            }
        return payload


_EVENTS: list[OverlayEvent] = []


def reset_overlay_diagnostics() -> None:
    _EVENTS.clear()


def record_overlay(event: OverlayEvent) -> OverlayEvent:
    _EVENTS.append(event)
    return event


def overlay_events() -> list[OverlayEvent]:
    return list(_EVENTS)


def write_overlay_diagnostics(work_dir: Path | None) -> Path | None:
    if work_dir is None:
        return None
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "overlay_diagnostics.json"
    payload = {
        "events": [e.to_dict() for e in _EVENTS],
        "applied_count": sum(1 for e in _EVENTS if e.applied),
        "skipped_count": sum(1 for e in _EVENTS if not e.applied),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
