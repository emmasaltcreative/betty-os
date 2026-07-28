"""Campaign approval persistence with canonical Sprint 15 schema."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.persistence import atomic_write_json, load_json
from src.templates.models import APPROVAL_STATUSES, ApprovalRecord
from src.templates.registry import template_id_for_legacy_folder


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def approvals_path(campaign_dir: Path) -> Path:
    return campaign_dir / "approvals.json"


def _infer_template_id(file_path: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    folder = file_path.split("/")[0] if "/" in file_path else file_path
    return template_id_for_legacy_folder(folder) or folder


def _infer_asset_id(file_path: str, item_name: str = "") -> str:
    folder = file_path.split("/")[0] if "/" in file_path else (item_name or "asset")
    return folder


def _infer_version_id(file_path: str, item_name: str = "") -> str:
    name = Path(file_path).name or item_name
    import re

    match = re.search(r"_v(\d+)\.", name)
    if match:
        return f"v{match.group(1)}"
    if "draft" in name:
        return "v1"
    return "v1"


def normalize_approval_item(
    item: dict[str, Any],
    *,
    campaign_id: str,
) -> dict[str, Any]:
    file_path = str(item.get("file_path") or "")
    status = str(item.get("status") or "awaiting_review")
    if status not in APPROVAL_STATUSES:
        status = "awaiting_review"
    record = ApprovalRecord(
        campaign_id=str(item.get("campaign_id") or campaign_id),
        asset_id=str(item.get("asset_id") or _infer_asset_id(file_path, str(item.get("item_name") or ""))),
        template_id=str(
            item.get("template_id")
            or _infer_template_id(file_path, None)
        ),
        render_version_id=str(
            item.get("render_version_id")
            or _infer_version_id(file_path, str(item.get("item_name") or ""))
        ),
        status=status,
        note=str(item.get("note") or ""),
        reviewed_at=item.get("reviewed_at"),
        updated_at=str(item.get("updated_at") or item.get("reviewed_at") or _now()),
        item_name=str(item.get("item_name") or Path(file_path).name),
        item_type=str(item.get("item_type") or "file"),
        file_path=file_path,
    )
    return record.model_dump()


def load_campaign_approvals(campaign_dir: Path) -> dict[str, Any]:
    path = approvals_path(campaign_dir)
    data = load_json(path, default=None)
    if not isinstance(data, dict):
        return {"campaign_id": campaign_dir.name, "campaign": campaign_dir.name, "items": [], "updated_at": None}
    items = []
    for item in data.get("items") or []:
        if isinstance(item, dict):
            items.append(normalize_approval_item(item, campaign_id=campaign_dir.name))
    return {
        "campaign_id": campaign_dir.name,
        "campaign": campaign_dir.name,
        "updated_at": data.get("updated_at"),
        "items": items,
    }


def write_campaign_approvals(campaign_dir: Path, approvals: dict[str, Any]) -> Path:
    path = approvals_path(campaign_dir)
    items = [
        normalize_approval_item(item, campaign_id=campaign_dir.name)
        for item in (approvals.get("items") or [])
        if isinstance(item, dict)
    ]
    payload = {
        "campaign_id": campaign_dir.name,
        "campaign": campaign_dir.name,
        "updated_at": _now(),
        "items": items,
    }
    atomic_write_json(path, payload)
    # Reload verify
    reloaded = load_campaign_approvals(campaign_dir)
    if len(reloaded.get("items") or []) != len(items):
        raise RuntimeError("Approval save verification failed.")
    return path


def upsert_approval(
    campaign_dir: Path,
    *,
    asset_id: str,
    template_id: str,
    render_version_id: str,
    status: str,
    note: str = "",
    file_path: str = "",
    item_name: str = "",
    item_type: str = "render",
) -> dict[str, Any]:
    if status not in APPROVAL_STATUSES:
        raise ValueError(f"Invalid approval status: {status}")
    data = load_campaign_approvals(campaign_dir)
    items = list(data.get("items") or [])
    now = _now()
    updated = None
    for index, item in enumerate(items):
        same_asset = item.get("asset_id") == asset_id
        same_version = item.get("render_version_id") == render_version_id
        same_path = file_path and item.get("file_path") == file_path
        if same_path or (same_asset and same_version and item.get("template_id") == template_id):
            row = dict(item)
            row.update(
                {
                    "status": status,
                    "note": note if status in {"needs_revision", "rejected"} else (note or row.get("note") or ""),
                    "reviewed_at": now if status != "awaiting_review" else row.get("reviewed_at"),
                    "updated_at": now,
                    "campaign_id": campaign_dir.name,
                    "asset_id": asset_id,
                    "template_id": template_id,
                    "render_version_id": render_version_id,
                    "file_path": file_path or row.get("file_path") or "",
                    "item_name": item_name or row.get("item_name") or "",
                    "item_type": item_type or row.get("item_type") or "render",
                }
            )
            items[index] = normalize_approval_item(row, campaign_id=campaign_dir.name)
            updated = items[index]
            break
    if updated is None:
        updated = normalize_approval_item(
            {
                "campaign_id": campaign_dir.name,
                "asset_id": asset_id,
                "template_id": template_id,
                "render_version_id": render_version_id,
                "status": status,
                "note": note,
                "reviewed_at": now if status != "awaiting_review" else None,
                "updated_at": now,
                "file_path": file_path,
                "item_name": item_name or Path(file_path).name,
                "item_type": item_type,
            },
            campaign_id=campaign_dir.name,
        )
        items.append(updated)
    write_campaign_approvals(campaign_dir, {"items": items})
    return updated
