"""Campaign asset visibility — separate internal QA from user-facing creative.

Internal / QA / smoke_test / diagnostic assets must never enter Today, Decide,
campaign coverage, readiness, or delivery packages.

Classification prefers an explicit marker file over title heuristics.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Visibility = Literal["campaign", "internal"]
Purpose = Literal["campaign", "smoke_test", "qa", "diagnostic", "fixture"]

META_FILENAME = "betty_asset_meta.json"

# Folder-name heuristics (secondary). Explicit meta always wins.
_INTERNAL_NAME_PATTERNS = (
    re.compile(r"(^|_)smoke(_|$)", re.I),
    re.compile(r"(^|_)qa(_|$)", re.I),
    re.compile(r"(^|_)diagnostic", re.I),
    re.compile(r"^internal_", re.I),
    re.compile(r"^logo_smoke", re.I),
    re.compile(r"^__betty_", re.I),
)

# Campaign-level directories that are never render deliverables.
NON_DELIVERABLE_DIR_NAMES = frozenset(
    {
        "approvals.json",
        "approval_summary.md",
        "migration_report.json",
        "render_queue_summary.md",
        "exports",
        "studio",
        "document_previews",
        "revision_jobs",
        "production_briefs",
        "BettyOS Data",
        "betty_data",
        ".betty_internal",
    }
)


@dataclass(frozen=True)
class AssetVisibility:
    visibility: Visibility
    purpose: Purpose
    reason: str
    folder_name: str
    meta_path: str | None = None
    folder_path: str | None = None

    @property
    def is_internal(self) -> bool:
        return self.visibility == "internal"

    @property
    def is_user_facing(self) -> bool:
        return self.visibility == "campaign"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def meta_path_for(folder: Path) -> Path:
    return Path(folder) / META_FILENAME


def write_asset_meta(
    folder: Path,
    *,
    visibility: Visibility,
    purpose: Purpose = "campaign",
    notes: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    """Persist explicit visibility. Prefer this over relying on folder names."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "visibility": visibility,
        "purpose": purpose,
        "notes": notes,
    }
    if extra:
        payload.update(extra)
    path = meta_path_for(folder)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_asset_meta(folder: Path) -> dict[str, Any] | None:
    path = meta_path_for(folder)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def classify_asset_folder(folder: Path | None) -> AssetVisibility:
    """Classify a render folder as campaign (user-facing) or internal."""
    if folder is None:
        return AssetVisibility("internal", "diagnostic", "Missing folder", "", folder_path=None)
    folder = Path(folder)
    name = folder.name
    folder_path = str(folder)

    meta = read_asset_meta(folder)
    if meta:
        visibility = str(meta.get("visibility") or "campaign").lower()
        purpose = str(meta.get("purpose") or "campaign").lower()
        if visibility in {"internal", "qa", "smoke_test", "diagnostic", "fixture"}:
            purpose_norm: Purpose = (
                purpose if purpose in {"smoke_test", "qa", "diagnostic", "fixture"} else "qa"
            )
            return AssetVisibility(
                "internal",
                purpose_norm,
                str(meta.get("notes") or "Marked internal in betty_asset_meta.json"),
                name,
                str(meta_path_for(folder)),
                folder_path,
            )
        if visibility == "campaign":
            return AssetVisibility(
                "campaign",
                "campaign",
                "Marked campaign in betty_asset_meta.json",
                name,
                str(meta_path_for(folder)),
                folder_path,
            )

    # Parent path under BettyOS Data / .betty_internal is always internal.
    parts_lower = [p.lower() for p in folder.parts]
    if "bettyos data" in parts_lower or ".betty_internal" in parts_lower:
        return AssetVisibility(
            "internal",
            "qa",
            "Stored under BettyOS Data / .betty_internal",
            name,
            folder_path=folder_path,
        )

    for pattern in _INTERNAL_NAME_PATTERNS:
        if pattern.search(name):
            return AssetVisibility(
                "internal",
                "smoke_test" if "smoke" in name.lower() else "qa",
                f"Folder name matches internal pattern ({pattern.pattern})",
                name,
                folder_path=folder_path,
            )

    return AssetVisibility(
        "campaign",
        "campaign",
        "Default campaign deliverable",
        name,
        folder_path=folder_path,
    )


def is_internal_asset_folder(folder: Path | None) -> bool:
    return classify_asset_folder(folder).is_internal


def is_user_facing_asset_folder(folder: Path | None) -> bool:
    return classify_asset_folder(folder).is_user_facing


def filter_user_facing_versions(versions: list) -> list:
    """Drop internal QA render versions from product-facing lists."""
    return [v for v in versions if is_user_facing_asset_folder(getattr(v, "folder", None))]


def filter_user_facing_deliverables(deliverables: list) -> list:
    """Drop deliverables whose template_id looks internal (defense in depth)."""
    result = []
    for item in deliverables:
        template_id = str(getattr(item, "template_id", "") or "")
        if any(p.search(template_id) for p in _INTERNAL_NAME_PATTERNS):
            continue
        result.append(item)
    return result


def list_internal_asset_folders(campaign_dir: Path | None) -> list[AssetVisibility]:
    """Discover internal QA folders for Diagnostics (includes relocated QA)."""
    if campaign_dir is None or not Path(campaign_dir).is_dir():
        return []
    found: list[AssetVisibility] = []
    root = Path(campaign_dir)
    candidates: list[Path] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        # Skip bookkeeping containers themselves; walk their qa children below.
        if path.name in NON_DELIVERABLE_DIR_NAMES:
            continue
        candidates.append(path)
    qa_roots = [
        root / "BettyOS Data" / "qa",
        root / ".betty_internal",
    ]
    for qa_root in qa_roots:
        if qa_root.is_dir():
            candidates.extend([p for p in qa_root.iterdir() if p.is_dir()])
    seen: set[str] = set()
    for folder in candidates:
        key = str(folder.resolve())
        if key in seen:
            continue
        seen.add(key)
        info = classify_asset_folder(folder)
        if info.is_internal:
            found.append(info)
    return found
