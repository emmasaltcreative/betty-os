"""Bridge illustration versions into the existing Review and Approvals flow.

Illustration versions live in the private data root, while BettyOS Review and
Approvals are campaign-centric and read from ``outputs/``. This module connects
them without duplicating either:

* Sending to review **publishes** an export copy into the campaign's output
  folder (``outputs/`` is gitignored), so the normal Review and Export screens
  can see a real file.
* Approvals are written to the campaign's own approvals store, so illustrations
  appear beside renders in the Approvals screen.
* Every decision is recorded as a standard ``ApprovalEvent``, so Insights and
  the learning engine treat illustration feedback like any other.

The private original is never moved: the published copy is a copy.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from src.common import DEFAULT_BRAND_ID
from src.templates.approvals_store import upsert_approval
from studio.learning import new_approval_event, record_approval_event
from illustration import canon, service, versions

REVIEW_STATUSES = ("awaiting_review", "approved", "needs_revision", "rejected")
PUBLISH_DIRNAME = "illustrations"


class ReviewBridgeError(Exception):
    """Could not connect an illustration version to Review/Approvals."""


def published_dir(campaign_dir: Path) -> Path:
    path = Path(campaign_dir) / PUBLISH_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def publish_exports(
    version_id: str,
    campaign_dir: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
) -> list[Path]:
    """Copy a version's real exported files into the campaign output folder."""
    version = versions.require_version(version_id, brand_id)
    if not version.export_paths:
        raise ReviewBridgeError(
            f"{version_id} has no exports yet. Export it before sending to Review."
        )
    target = published_dir(campaign_dir)
    published: list[Path] = []
    for stored in version.export_paths.values():
        source = versions.resolve(stored)
        if source is None or not source.is_file():
            # Never advertise a file that is not really there.
            raise ReviewBridgeError(
                f"{version_id} records an export that is missing on disk: {stored}"
            )
        destination = target / source.name
        shutil.copy2(source, destination)
        published.append(destination)
    return published


def send_to_review(
    version_id: str,
    campaign_dir: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    note: str = "",
) -> dict[str, Any]:
    """Publish exports and queue the version for human review."""
    version = versions.require_version(version_id, brand_id)
    published = publish_exports(version_id, campaign_dir, brand_id=brand_id)
    primary = next((p for p in published if p.suffix == ".jpg"), published[0])

    upsert_approval(
        Path(campaign_dir),
        asset_id=version_id,
        template_id=version.brief.template_id,
        render_version_id=version_id,
        status="awaiting_review",
        note=note,
        file_path=str(primary),
        item_name=primary.stem,
        item_type="illustration",
    )
    updated = versions.update_version(
        version_id,
        brand_id,
        status="needs_accuracy_review"
        if version.status == "draft"
        else version.status,
    )
    return {
        "ok": True,
        "version": updated,
        "published": published,
        "campaign_dir": str(campaign_dir),
    }


def set_approval(
    version_id: str,
    status: str,
    *,
    campaign_dir: Path | None = None,
    brand_id: str = DEFAULT_BRAND_ID,
    note: str = "",
    product_accurate: bool = False,
) -> dict[str, Any]:
    """Approve / Needs Revision / Reject, recorded everywhere BettyOS looks.

    ``product_accurate`` is only honoured when the product profile is itself
    verified; otherwise the claim is refused and the version stays flagged.
    """
    if status not in REVIEW_STATUSES:
        raise ReviewBridgeError(f"Unsupported approval status: {status}")
    version = versions.require_version(version_id, brand_id)

    product = (
        canon.product(version.brief.product_id, brand_id)
        if version.brief.product_id
        else None
    )
    accuracy_allowed = bool(
        product is not None
        and product.accuracy_status == "product_accurate_verified"
    )
    accuracy_refused = product_accurate and not accuracy_allowed

    if status == "approved":
        versions.approve(
            version_id,
            brand_id,
            product_accurate=product_accurate and accuracy_allowed,
        )
    elif status == "rejected":
        versions.reject(version_id, brand_id, note=note)
    else:
        versions.update_version(version_id, brand_id, status="needs_accuracy_review")

    campaign_id = Path(campaign_dir).name if campaign_dir else ""
    event = new_approval_event(
        brand_id=brand_id,
        campaign_id=campaign_id,
        content_piece_id=None,
        finish_version_id=version_id,
        template_id=version.brief.template_id,
        status=status,
        approval_status=status,
        revision_note=note,
        content_type="illustration",
        platform="shopify_pdp" if version.brief.canvas.startswith("shopify") else "",
        parent_finish_version_id=version.parent_version_id,
        resulting_changes={
            "approval_status": status,
            "accuracy_status": versions.require_version(
                version_id, brand_id
            ).accuracy_status,
        },
    )
    record_approval_event(event)

    if campaign_dir is not None:
        primary = ""
        for stored in version.export_paths.values():
            path = versions.resolve(stored)
            if path and path.suffix == ".jpg":
                primary = str(published_dir(campaign_dir) / path.name)
                break
        upsert_approval(
            Path(campaign_dir),
            asset_id=version_id,
            template_id=version.brief.template_id,
            render_version_id=version_id,
            status=status,
            note=note,
            file_path=primary,
            item_name=version_id,
            item_type="illustration",
        )

    refreshed = service.run_qa(version_id, brand_id=brand_id)
    return {
        "ok": True,
        "version": refreshed,
        "event": event,
        "accuracy_refused": accuracy_refused,
        "accuracy_status": refreshed.accuracy_status,
    }


def review_queue(brand_id: str = DEFAULT_BRAND_ID) -> list[dict[str, Any]]:
    """Versions waiting on a human, newest first."""
    rows: list[dict[str, Any]] = []
    for version in versions.list_versions(brand_id):
        if version.status not in {"draft", "needs_accuracy_review"}:
            continue
        blocking = [
            c for c in version.qa_results
            if c.get("outcome") in {"fail", "needs_human"}
        ]
        rows.append(
            {
                "version_id": version.version_id,
                "status": version.status,
                "accuracy_status": version.accuracy_status,
                "template_id": version.brief.template_id,
                "needs_attention": [c.get("label") for c in blocking],
                "exported": bool(version.export_paths),
                "created_at": version.created_at,
            }
        )
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)
