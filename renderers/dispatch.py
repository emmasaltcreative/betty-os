"""Dispatch render requests to the correct renderer family."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from renderers.carousel import render_carousel_template
from renderers.copy import render_copy_template
from renderers.static import render_static_template
from renderers.video import render_video_template
from src.common import BettyOSError
from src.templates.registry import get_template


def render_template(
    *,
    template_id: str,
    content_piece_id: str,
    source_assets: list[str] | None = None,
    campaign_dir: Path | None = None,
    copy_fields: dict[str, str] | None = None,
    title: str = "",
    duration_seconds: float | None = None,
    cta_appear_at_seconds: float | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = get_template(template_id)
    if template is None:
        raise BettyOSError(f"Unknown template: {template_id}")
    if template.renderer_status == "planned":
        raise BettyOSError(
            f"`{template.display_name}` is planned. "
            "It is registered but not marked ready."
        )
    if template.renderer_status == "manual_only":
        raise BettyOSError(
            f"`{template.display_name}` requires manual completion."
        )

    module = template.renderer_module
    source_assets = source_assets or []
    copy_fields = copy_fields or {}

    if module == "video":
        return render_video_template(
            template_id=template_id,
            content_piece_id=content_piece_id,
            source_assets=source_assets,
            campaign_dir=campaign_dir,
            copy_fields=copy_fields,
            duration_seconds=duration_seconds,
            cta_appear_at_seconds=cta_appear_at_seconds,
            config=config,
        )
    if module == "static":
        return render_static_template(
            template_id=template_id,
            content_piece_id=content_piece_id,
            source_assets=source_assets,
            campaign_dir=campaign_dir,
            copy_fields=copy_fields,
            config=config,
        )
    if module == "carousel":
        return render_carousel_template(
            template_id=template_id,
            content_piece_id=content_piece_id,
            source_assets=source_assets,
            campaign_dir=campaign_dir,
            copy_fields=copy_fields,
            config=config,
        )
    if module == "copy":
        return render_copy_template(
            template_id=template_id,
            content_piece_id=content_piece_id,
            campaign_dir=campaign_dir,
            copy_fields=copy_fields,
            title=title,
            source_assets=source_assets,
            config=config,
        )
    raise BettyOSError(f"No renderer module for `{template_id}` ({module}).")
