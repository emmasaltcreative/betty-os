"""Persistence for campaign intelligence attached to existing campaign folders."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.campaign_intelligence.models import (
    CampaignIntelligence,
    LearningOutcome,
    ProductionBriefRecord,
)
from src.common import DEFAULT_BRAND_ID, relative_to_root
from src.persistence import atomic_write_json, load_json

INTELLIGENCE_FILENAME = "intelligence.json"
ESTIMATES_FILENAME = "estimates.json"
LEARNING_FILENAME = "learning_outcomes.json"
BRIEFS_DIRNAME = "production_briefs"
BRIEFS_INDEX = "index.json"


def intelligence_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / INTELLIGENCE_FILENAME


def estimates_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / ESTIMATES_FILENAME


def learning_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / LEARNING_FILENAME


def briefs_dir(campaign_dir: Path) -> Path:
    path = Path(campaign_dir) / BRIEFS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def briefs_index_path(campaign_dir: Path) -> Path:
    return briefs_dir(campaign_dir) / BRIEFS_INDEX


def load_intelligence(campaign_dir: Path | None) -> CampaignIntelligence | None:
    if campaign_dir is None or not Path(campaign_dir).is_dir():
        return None
    data = load_json(intelligence_path(campaign_dir), default=None)
    if not data:
        return None
    return CampaignIntelligence.from_dict(data)


def save_intelligence(campaign_dir: Path, intel: CampaignIntelligence) -> Path:
    intel.updated_at = datetime.now(timezone.utc).isoformat()
    path = intelligence_path(campaign_dir)
    atomic_write_json(path, intel.as_dict())
    # Mirror runway/deliverable snapshot for easy reload
    atomic_write_json(
        estimates_path(campaign_dir),
        {
            "deliverable_estimate": (
                intel.deliverable_estimate.as_dict() if intel.deliverable_estimate else None
            ),
            "runway_history": [r.as_dict() for r in intel.runway_history],
            "cadence": [c.as_dict() for c in intel.cadence],
            "updated_at": intel.updated_at,
        },
    )
    return path


def load_learning(campaign_dir: Path | None) -> LearningOutcome:
    if campaign_dir is None:
        return LearningOutcome()
    data = load_json(learning_path(campaign_dir), default={}) or {}
    return LearningOutcome.from_dict(data)


def save_learning(campaign_dir: Path, outcome: LearningOutcome) -> Path:
    outcome.updated_at = datetime.now(timezone.utc).isoformat()
    return atomic_write_json(learning_path(campaign_dir), outcome.as_dict())


def load_briefs_index(campaign_dir: Path) -> dict[str, Any]:
    return load_json(briefs_index_path(campaign_dir), default={}) or {
        "newest_id": None,
        "briefs": [],
    }


def save_briefs_index(campaign_dir: Path, index: dict[str, Any]) -> Path:
    return atomic_write_json(briefs_index_path(campaign_dir), index)


def register_brief(
    campaign_dir: Path,
    *,
    brief_id: str,
    filename: str,
    path: Path,
    campaign_slug: str,
    page_count: int,
    summary: dict[str, Any],
) -> ProductionBriefRecord:
    path = Path(path)
    size = path.stat().st_size if path.is_file() else 0
    record = ProductionBriefRecord(
        brief_id=brief_id,
        filename=filename,
        path=relative_to_root(path),
        created_at=datetime.now(timezone.utc).isoformat(),
        campaign_slug=campaign_slug,
        page_count=page_count,
        file_size_bytes=size,
        summary=summary,
    )
    index = load_briefs_index(campaign_dir)
    briefs = list(index.get("briefs") or [])
    briefs = [b for b in briefs if b.get("brief_id") != brief_id]
    briefs.insert(0, record.as_dict())
    index["briefs"] = briefs
    index["newest_id"] = brief_id
    index["newest_path"] = record.path
    index["newest_filename"] = filename
    save_briefs_index(campaign_dir, index)
    return record


def newest_brief(campaign_dir: Path | None) -> ProductionBriefRecord | None:
    if campaign_dir is None:
        return None
    index = load_briefs_index(campaign_dir)
    newest_id = index.get("newest_id")
    for raw in index.get("briefs") or []:
        if raw.get("brief_id") == newest_id or newest_id is None:
            record = ProductionBriefRecord.from_dict(raw)
            if newest_id is None:
                return record
            return record
    if index.get("briefs"):
        return ProductionBriefRecord.from_dict(index["briefs"][0])
    return None


def resolve_brief_file(campaign_dir: Path, record: ProductionBriefRecord) -> Path | None:
    """Resolve brief path relative to repo root or campaign folder."""
    from src.common import ROOT

    candidates = [
        ROOT / record.path,
        Path(record.path),
        briefs_dir(campaign_dir) / record.filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def campaign_slug(name: str, fallback: str = "campaign") -> str:
    text = (name or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-") or fallback
    return text[:60]


def default_brand_inventory_available(brand_id: str = DEFAULT_BRAND_ID) -> bool | None:
    """Read honest inventory stance from brand strategy when present."""
    from src.common import BRANDS_DIR

    strategy = BRANDS_DIR / brand_id / "business_strategy.md"
    if not strategy.is_file():
        return None
    text = strategy.read_text(encoding="utf-8").lower()
    if "no inventory is currently available" in text or "inventory is **not available**" in text:
        return False
    if "inventory is available" in text:
        return True
    return None
