"""Migrate legacy ritual_reel / page_turn_loop outputs to canonical templates."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common import OUTPUTS_DIR
from src.persistence import atomic_write_json
from src.templates.approvals_store import load_campaign_approvals, write_campaign_approvals
from src.templates.registry import LEGACY_FOLDER_TO_TEMPLATE, display_name_for


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def migrate_campaign(campaign_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "campaign": campaign_dir.name,
        "migrated": [],
        "unresolved": [],
        "errors": [],
        "updated_at": _now(),
    }
    for legacy, template_id in LEGACY_FOLDER_TO_TEMPLATE.items():
        src = campaign_dir / legacy
        if not src.is_dir():
            continue
        dest = campaign_dir / template_id
        try:
            if not dest.exists():
                # Copy tree so originals remain.
                shutil.copytree(src, dest)
            marker = {
                "legacy_folder": legacy,
                "template_id": template_id,
                "display_name": display_name_for(template_id),
                "preserved_original": str(src),
                "canonical_folder": str(dest),
                "migrated_at": _now(),
            }
            atomic_write_json(dest / "migration_marker.json", marker)
            report["migrated"].append(marker)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"folder": legacy, "error": str(exc)})

    # Normalize approvals schema in place (non-destructive field add).
    try:
        approvals = load_campaign_approvals(campaign_dir)
        write_campaign_approvals(campaign_dir, approvals)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append({"folder": "approvals.json", "error": str(exc)})

    # Unresolved render dirs
    known = set(LEGACY_FOLDER_TO_TEMPLATE) | set(LEGACY_FOLDER_TO_TEMPLATE.values())
    for child in campaign_dir.iterdir():
        if child.is_dir() and child.name not in known and not child.name.startswith("."):
            if any(child.glob("*.mp4")) or any(child.glob("*.png")):
                report["unresolved"].append(child.name)

    atomic_write_json(campaign_dir / "migration_report.json", report)
    return report


def migrate_all_campaigns() -> dict[str, Any]:
    campaigns = sorted(p for p in OUTPUTS_DIR.glob("*_campaign") if p.is_dir())
    reports = [migrate_campaign(c) for c in campaigns]
    summary = {
        "updated_at": _now(),
        "campaigns": len(reports),
        "migrated_items": sum(len(r["migrated"]) for r in reports),
        "errors": sum(len(r["errors"]) for r in reports),
        "reports": reports,
    }
    atomic_write_json(OUTPUTS_DIR / "migration_report.json", summary)
    return summary
