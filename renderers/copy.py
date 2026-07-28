"""CopyRenderer family — captions, emails, short CTA sets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from renderers.primitives import next_output_version, validate_outputs, write_render_manifest
from src.common import OUTPUTS_DIR, BettyOSError
from src.persistence import atomic_write_text
from src.templates.registry import get_template

COPY_READY = {
    "instagram_caption",
    "pinterest_caption_metadata",
    "email_letter",
    "launch_email",
    "short_form_cta_set",
    "product_description",
    "website_announcement",
    "founder_note",
}


def _body_for(template_id: str, copy_fields: dict[str, str], title: str) -> str:
    caption = copy_fields.get("caption") or copy_fields.get("body_text") or ""
    hook = copy_fields.get("hook_text") or ""
    cta = copy_fields.get("cta_text") or "Join the waitlist."
    headline = copy_fields.get("headline") or title or "The Reading Hour"

    if template_id == "instagram_caption":
        return (
            f"# Instagram Caption\n\n"
            f"{caption or hook or headline}\n\n"
            f"{cta}\n"
        )
    if template_id == "pinterest_caption_metadata":
        return (
            f"# Pinterest Pin Description\n\n"
            f"**Title:** {headline}\n\n"
            f"**Description:**\n{caption or hook or headline}\n\n"
            f"**CTA:** {cta}\n"
        )
    if template_id in {"email_letter", "launch_email", "founder_note"}:
        return (
            f"# {headline}\n\n"
            f"Dear reader,\n\n"
            f"{caption or hook or 'The hour already belongs to you.'}\n\n"
            f"{cta}\n\n"
            f"With care,\nOh Betty Jaletti\n"
        )
    if template_id == "short_form_cta_set":
        variants = [
            cta,
            "The waitlist is open.",
            "Be among the first.",
            "Link in bio.",
        ]
        lines = ["# Short-Form CTA Set", ""]
        for index, text in enumerate(variants, start=1):
            lines.append(f"{index}. {text}")
        lines.append("")
        return "\n".join(lines)
    return f"# {headline}\n\n{caption or hook}\n\n{cta}\n"


def render_copy_template(
    *,
    template_id: str,
    content_piece_id: str,
    campaign_dir: Path | None = None,
    copy_fields: dict[str, str] | None = None,
    title: str = "",
    source_assets: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = get_template(template_id)
    if template is None:
        raise BettyOSError(f"Unknown template: {template_id}")
    if template.renderer_status == "planned":
        raise BettyOSError(f"Template `{template_id}` is planned only.")
    if template_id not in COPY_READY and template.renderer_status != "ready":
        raise BettyOSError(
            f"Copy template `{template_id}` is not ready ({template.renderer_status})."
        )

    copy_fields = copy_fields or {}
    if campaign_dir is None:
        campaign_dir = OUTPUTS_DIR / "studio_renders"
        campaign_dir.mkdir(parents=True, exist_ok=True)
    out_dir = campaign_dir / template_id / content_piece_id
    out_dir.mkdir(parents=True, exist_ok=True)

    version = next_output_version(out_dir, template_id, "md")
    output = out_dir / f"{template_id}_v{version}.md"
    body = _body_for(template_id, copy_fields, title)
    if len(body.strip()) < 20:
        raise BettyOSError("Copy render produced empty content.")
    atomic_write_text(output, body if body.endswith("\n") else body + "\n")
    validate_outputs([output])
    write_render_manifest(
        out_dir,
        template_id=template_id,
        content_piece_id=content_piece_id,
        version=version,
        outputs=[output.name],
        source_assets=source_assets or [],
        config=config or {},
        parent_version=version - 1 if version > 1 else None,
    )
    return {
        "ok": True,
        "template_id": template_id,
        "content_piece_id": content_piece_id,
        "version": version,
        "output_dir": str(out_dir),
        "outputs": [str(output)],
    }
