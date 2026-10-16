"""Human-ready campaign delivery documents (PDF + DOCX).

JSON and technical records belong under BettyOS Data/. Primary deliverables
are polished documents founders can open without opening a terminal.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image as RLImage, Paragraph, SimpleDocTemplate, Spacer

from src.docx_simple import build_docx

CREAM = HexColor("#F7F1E8")
INK = HexColor("#2C241B")
JADE = HexColor("#3D6B5A")
MUTED = HexColor("#6E6256")
RULE = HexColor("#D9CBB8")


def _active_logo_png() -> tuple[Path | None, dict[str, Any]]:
    """Resolve active Settings logo for new documents. Returns (png_path, lineage_meta)."""
    try:
        from services.active_logo import rasterize_logo_png, resolve_active_logo

        mark = resolve_active_logo(bootstrap=True)
        if mark is None or not mark.suitable:
            return None, {}
        png = rasterize_logo_png(mark, max_edge=320)
        meta = {
            "logo_asset_id": mark.asset_id,
            "logo_display_name": mark.display_name,
            "logo_lineage_id": mark.lineage_id,
            "logo_storage_ref": mark.storage_ref,
        }
        return png, meta
    except Exception:
        return None, {}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=JADE,
            spaceAfter=6,
            tracking=1,
        ),
        "hero": ParagraphStyle(
            "hero",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=INK,
            spaceAfter=10,
            leading=26,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=INK,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=INK,
            leading=14,
            spaceAfter=6,
        ),
        "muted": ParagraphStyle(
            "muted",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=MUTED,
            leading=12,
            spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=JADE,
            spaceBefore=8,
            spaceAfter=2,
        ),
    }


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _pdf_from_sections(title: str, sections: list[tuple[str, list[tuple[str, str]]]]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=title,
        author="BettyOS",
    )
    styles = _styles()
    story: list[Any] = [
        Paragraph("CAMPAIGN DELIVERY", styles["eyebrow"]),
    ]
    logo_png, _meta = _active_logo_png()
    if logo_png is not None and logo_png.is_file():
        # Restrained mark — preserve aspect, no stretch.
        img = RLImage(str(logo_png))
        img.drawHeight = 0.55 * inch
        aspect = float(img.imageWidth) / float(img.imageHeight or 1)
        img.drawWidth = img.drawHeight * aspect
        story.append(img)
        story.append(Spacer(1, 0.12 * inch))
    story.extend(
        [
            Paragraph(_escape(title), styles["hero"]),
            HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=12),
        ]
    )
    for heading, fields in sections:
        if heading:
            story.append(Paragraph(_escape(heading), styles["h2"]))
        for label, value in fields:
            if not (value or "").strip():
                continue
            story.append(Paragraph(_escape(label), styles["label"]))
            story.append(Paragraph(_escape(value), styles["body"]))
        story.append(Spacer(1, 0.08 * inch))
    doc.build(story)
    return buffer.getvalue()


def _docx_from_sections(title: str, sections: list[tuple[str, list[tuple[str, str]]]]) -> bytes:
    paragraphs: list[str] = []
    for heading, fields in sections:
        if heading:
            paragraphs.append(f"# {heading}")
        for label, value in fields:
            if not (value or "").strip():
                continue
            paragraphs.append(f"{label}:")
            paragraphs.append(value.strip())
            paragraphs.append("")
    logo_png, _meta = _active_logo_png()
    logo_bytes = logo_png.read_bytes() if logo_png and logo_png.is_file() else None
    return build_docx(paragraphs, title=title, logo_png=logo_bytes)


def campaign_overview_copy(state, *, deliverable_count: int = 0, platform_count: int = 0) -> str:
    name = state.name or "this campaign"
    return (
        f"This delivery includes the current approved creative and publishing materials "
        f"for the {name} campaign, organized by platform and ready for execution."
        + (
            f" It covers {deliverable_count} deliverable"
            f"{'s' if deliverable_count != 1 else ''}"
            f" across {platform_count} platform{'s' if platform_count != 1 else ''}."
            if deliverable_count
            else ""
        )
    )


def build_overview_documents(state, plan) -> list[tuple[str, bytes]]:
    platforms = sorted({(i.platform or "other") for i in plan.included})
    fields = [
        ("Campaign", state.name),
        ("Objective", state.goal),
        ("Status", getattr(state, "stage", "") or "—"),
        ("Platforms", ", ".join(p.title() for p in platforms) or "—"),
        (
            "Included deliverables",
            str(len(plan.included)),
        ),
        (
            "About this delivery",
            campaign_overview_copy(
                state,
                deliverable_count=len(plan.included),
                platform_count=len(platforms),
            ),
        ),
    ]
    sections = [("", fields)]
    title = f"00 Campaign Overview"
    pdf = _pdf_from_sections(f"{state.name} — Campaign Overview", sections)
    return [(f"{title}.pdf", pdf)]


def build_posting_plan_documents(state, plan, *, runway: str | None = None) -> list[tuple[str, bytes]]:
    fields: list[tuple[str, str]] = [
        ("Campaign", state.name),
        ("Objective", state.goal),
    ]
    if runway:
        fields.append(("Estimated runway", runway))
    sequence = []
    for index, item in enumerate(plan.included, start=1):
        sequence.append(
            f"{index}. {item.platform.title()} — {item.content_type or item.label}"
        )
    fields.append(("Publishing sequence", "\n".join(sequence) or "No assets yet"))
    fields.append(
        (
            "Checklist",
            "Confirm asset filenames match the posting tools.\n"
            "Paste captions from the Campaign Copybook or platform copy sheets.\n"
            "Verify destination links and tracking before publishing.",
        )
    )
    sections = [("", fields)]
    pdf = _pdf_from_sections(f"{state.name} — Posting Plan", sections)
    docx = _docx_from_sections(f"{state.name} — Posting Plan", sections)
    return [("02 Posting Plan.pdf", pdf), ("02 Posting Plan.docx", docx)]


def _parse_copy_blob(text: str) -> dict[str, str]:
    """Best-effort field extraction from caption / metadata source text."""
    data: dict[str, str] = {}
    if not text or not text.strip():
        return data
    patterns = {
        "title": r"(?im)^(?:title|pin title)\s*[:\-]\s*(.+)$",
        "hook": r"(?im)^(?:hook)\s*[:\-]\s*(.+)$",
        "headline": r"(?im)^(?:headline)\s*[:\-]\s*(.+)$",
        "caption": r"(?im)^(?:caption|body)\s*[:\-]\s*(.+)$",
        "description": r"(?im)^(?:description|desc)\s*[:\-]\s*(.+)$",
        "cta": r"(?im)^(?:cta|call to action)\s*[:\-]\s*(.+)$",
        "alt_text": r"(?im)^(?:alt(?:\s*text)?)\s*[:\-]\s*(.+)$",
        "hashtags": r"(?im)^(?:hashtags?)\s*[:\-]\s*(.+)$",
        "keywords": r"(?im)^(?:keywords?)\s*[:\-]\s*(.+)$",
        "board": r"(?im)^(?:board)\s*[:\-]\s*(.+)$",
        "url": r"(?im)^(?:url|link|destination)\s*[:\-]\s*(.+)$",
        "first_comment": r"(?im)^(?:first comment)\s*[:\-]\s*(.+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            data[key] = match.group(1).strip()
    if "caption" not in data and "description" not in data:
        # Treat whole blob as caption when unstructured
        cleaned = text.strip()
        if cleaned and len(cleaned) < 4000:
            data["caption"] = cleaned
    return data


def _copy_fields_for_item(item) -> dict[str, str]:
    fields: dict[str, str] = {
        "platform": (item.platform or "").title(),
        "format": item.content_type or item.label,
        "asset_filename": "",
        "campaign_role": "",
    }
    texts: list[str] = []
    for pkg in getattr(item, "package_files", []) or []:
        if pkg.role in {"caption", "copy", "metadata"} and getattr(pkg, "source", None):
            try:
                if pkg.source.is_file():
                    texts.append(pkg.source.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        elif pkg.role in {"media", "slide"} and not fields["asset_filename"]:
            fields["asset_filename"] = Path(pkg.archive_name).name

    # Fall back to version support docs (captions may be omitted from ZIP when
    # they still contain production notes — still useful for the Copybook).
    version = getattr(item, "version", None)
    if version is not None and not texts:
        for path in getattr(version, "support_files", []) or []:
            try:
                if path.is_file() and (
                    "caption" in path.name.lower()
                    or path.suffix.lower() in {".md", ".txt"}
                ):
                    texts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue

    blob = "\n".join(texts)
    fields.update(_parse_copy_blob(blob))
    # Prefer a Caption section from markdown-ish production docs
    if "caption" not in fields and blob:
        match = re.search(
            r"(?is)##\s*Caption\s*\n+(.+?)(?:\n##|\Z)",
            blob,
        )
        if match:
            fields["caption"] = re.sub(r"\*\*", "", match.group(1)).strip()[:1200]
        else:
            # Strip production scaffolding headings; keep readable remainder
            cleaned = re.sub(r"(?im)^\*\*Exact Asset File Paths:\*\*.*$", "", blob)
            cleaned = re.sub(r"(?im)^\*\*Recommended Shot Order\*\*.*$", "", cleaned)
            cleaned = re.sub(r"(?m)^- `assets/.*$", "", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            if cleaned and len(cleaned) < 2000:
                fields["caption"] = cleaned[:1200]
    return fields


_FIELD_ORDER = [
    ("platform", "Platform"),
    ("format", "Format"),
    ("recommended_window", "Recommended publishing window"),
    ("asset_filename", "Asset filename"),
    ("campaign_role", "Campaign role"),
    ("hook", "Hook"),
    ("headline", "Headline"),
    ("title", "Title"),
    ("caption", "Caption"),
    ("description", "Description"),
    ("cta", "CTA"),
    ("first_comment", "First comment"),
    ("hashtags", "Hashtags"),
    ("keywords", "Keywords"),
    ("board", "Board recommendation"),
    ("alt_text", "Alt text"),
    ("url", "Destination URL"),
    ("tracking", "Tracking parameters"),
    ("notes", "Publishing notes"),
]


def build_copybook_documents(state, plan) -> list[tuple[str, bytes]]:
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for item in plan.included:
        fields_map = _copy_fields_for_item(item)
        heading = f"{fields_map.get('platform') or 'Asset'} — {fields_map.get('format') or item.label}"
        pairs = [(label, fields_map[key]) for key, label in _FIELD_ORDER if fields_map.get(key)]
        if pairs:
            sections.append((heading, pairs))
    if not sections:
        sections = [("", [("Note", "No publishing copy was available for this delivery.")])]
    title = f"{state.name} — Campaign Copybook"
    pdf = _pdf_from_sections(title, sections)
    docx = _docx_from_sections(title, sections)
    return [("03 Campaign Copybook.pdf", pdf), ("03 Campaign Copybook.docx", docx)]


def build_platform_copy_documents(state, plan) -> list[tuple[str, bytes]]:
    """One concise copy sheet per platform that has copy-bearing items."""
    by_platform: dict[str, list] = {}
    for item in plan.included:
        platform = (item.platform or "other").lower()
        by_platform.setdefault(platform, []).append(item)

    docs: list[tuple[str, bytes]] = []
    folder_names = {
        "instagram": "Instagram",
        "pinterest": "Pinterest",
        "email": "Email",
        "website": "Website",
        "carousel": "Carousel",
    }
    for platform, items in by_platform.items():
        sections: list[tuple[str, list[tuple[str, str]]]] = []
        for item in items:
            fields_map = _copy_fields_for_item(item)
            # Skip if no real copy beyond platform/format
            content_keys = {
                "hook",
                "headline",
                "title",
                "caption",
                "description",
                "cta",
                "alt_text",
                "keywords",
                "hashtags",
            }
            if not any(fields_map.get(k) for k in content_keys):
                continue
            heading = fields_map.get("format") or item.label
            pairs = [(label, fields_map[key]) for key, label in _FIELD_ORDER if fields_map.get(key)]
            sections.append((heading, pairs))
        if not sections:
            continue
        folder = folder_names.get(platform, platform.title())
        sheet_title = f"{folder} Posting Copy"
        pdf = _pdf_from_sections(f"{state.name} — {sheet_title}", sections)
        docx = _docx_from_sections(f"{state.name} — {sheet_title}", sections)
        docs.append((f"{folder}/{sheet_title}.pdf", pdf))
        docs.append((f"{folder}/{sheet_title}.docx", docx))
    return docs


def human_delivery_root(state) -> str:
    name = (state.name or "Campaign").strip()
    if not name.lower().endswith("campaign"):
        name = f"{name} Campaign"
    return name


def human_archive_filename(state, *, day: str | None = None) -> str:
    from datetime import date

    from src.campaign_meta import campaign_slug_from_title

    slug = campaign_slug_from_title(state.name or "campaign")
    stamp = day or date.today().isoformat()
    return f"{slug}_campaign-delivery_{stamp}.zip"


def is_primary_text_deliverable(archive_name: str) -> bool:
    """True when a path would be a human-facing TXT/MD (not BettyOS Data)."""
    lower = archive_name.lower()
    if "/bettyos data/" in lower or archive_name.lower().startswith("bettyos data/"):
        return False
    return lower.endswith(".txt") or lower.endswith(".md")
