"""Concise visual Production Brief PDF generation (3–5 pages)."""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.campaign_intelligence.models import CampaignIntelligence
from src.campaign_intelligence.store import (
    briefs_dir,
    campaign_slug,
    register_brief,
)

# Calm, brand-adjacent palette — not purple AI defaults.
CREAM = HexColor("#F7F1E8")
INK = HexColor("#2C241B")
JADE = HexColor("#3D6B5A")
WARM = HexColor("#C4A574")
MUTED = HexColor("#6E6256")
RULE = HexColor("#D9CBB8")


def generate_production_brief(
    campaign_dir: Path,
    intel: CampaignIntelligence,
    *,
    include_csv: bool = False,
) -> dict[str, Any]:
    """Fully generate the Production Brief PDF before returning download metadata."""
    slug = campaign_slug(intel.campaign_name or campaign_dir.name)
    day = date.today().isoformat()
    filename = f"{slug}_production-brief_{day}.pdf"
    out_dir = briefs_dir(campaign_dir)
    pdf_path = out_dir / filename

    buffer = BytesIO()
    page_count = _build_pdf(buffer, intel)
    pdf_bytes = buffer.getvalue()
    if not pdf_bytes or len(pdf_bytes) < 100:
        raise RuntimeError("Production Brief PDF generation produced an empty file.")

    pdf_path.write_bytes(pdf_bytes)
    if not pdf_path.is_file() or pdf_path.stat().st_size < 100:
        raise RuntimeError("Production Brief PDF was not written to disk.")

    # Verify readable
    _ = pdf_path.read_bytes()

    csv_path = None
    files_for_zip: list[Path] = [pdf_path]
    if include_csv:
        csv_name = f"{slug}_production-plan_{day}.csv"
        csv_path = out_dir / csv_name
        csv_path.write_text(_publishing_csv(intel), encoding="utf-8")
        files_for_zip.append(csv_path)

    summary = _brief_summary(intel)
    brief_id = f"brief_{uuid4().hex[:10]}"
    record = register_brief(
        campaign_dir,
        brief_id=brief_id,
        filename=filename,
        path=pdf_path,
        campaign_slug=slug,
        page_count=page_count,
        summary=summary,
    )
    intel.newest_brief_id = brief_id

    result = {
        "ok": True,
        "brief_id": brief_id,
        "path": pdf_path,
        "filename": filename,
        "page_count": page_count,
        "file_size_bytes": pdf_path.stat().st_size,
        "bytes": pdf_bytes,
        "summary": summary,
        "record": record,
        "csv_path": csv_path,
        "download_paths": files_for_zip,
    }
    return result


def _build_pdf(buffer: BytesIO, intel: CampaignIntelligence) -> int:
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=f"Production Brief — {intel.campaign_name}",
        author="BettyOS",
    )
    styles = _styles()
    story: list[Any] = []

    # PAGE 1 — Overview
    story.append(Paragraph("PRODUCTION BRIEF", styles["eyebrow"]))
    story.append(Paragraph(intel.campaign_name or "Campaign", styles["hero"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width="100%", thickness=1, color=RULE, spaceAfter=12))

    primary = intel.primary_recommendation()
    deliverable = intel.deliverable_estimate
    runway = intel.current_runway()
    session = intel.production_session

    overview_rows = [
        ["Business objective", intel.inputs.business_objective or "—"],
        [
            "Core creative direction",
            intel.creative_direction
            or "Quiet ritual, honest waitlist framing, product familiarity before the ask.",
        ],
        [
            "Target milestone",
            _fmt_date(intel.inputs.target_milestone_date)
            or (primary.timing.milestone_date.isoformat() if primary and primary.timing.milestone_date else "Not confirmed"),
        ],
        [
            "Campaign portfolio",
            _portfolio_line(intel),
        ],
        [
            "Expected deliverables",
            (_range_label(deliverable.final_assets, unit="assets") + " final assets")
            if deliverable
            else "—",
        ],
        [
            "Estimated filming",
            _minutes_label(deliverable.filming_minutes if deliverable else None)
            or (
                _minutes_label(session.filming_minutes)
                if session
                else "—"
            ),
        ],
        [
            "Estimated editing",
            _minutes_label(deliverable.editing_minutes if deliverable else None) or "—",
        ],
        ["Recommended cadence", _cadence_line(intel)],
        [
            "Estimated content runway",
            (
                f"Approximately {_range_label(runway.days)}"
                if runway
                else "—"
            ),
        ],
        [
            "Confidence",
            (deliverable.confidence if deliverable else "medium").title(),
        ],
    ]
    story.append(_kv_table(overview_rows))
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "Evidence note: figures above are operational estimates and planning assumptions — "
            "not performance forecasts.",
            styles["muted"],
        )
    )
    story.append(_page_break())

    # PAGE 2 — Visual shot plan
    story.append(Paragraph("VISUAL SHOT PLAN", styles["eyebrow"]))
    story.append(Paragraph("What to film", styles["h1"]))
    story.append(Spacer(1, 0.1 * inch))

    shots = session.shots if session else []
    must = [s for s in shots if s.must_have]
    optional = [s for s in shots if not s.must_have]

    story.append(Paragraph("Must-have shots", styles["h2"]))
    for shot in must:
        story.append(Paragraph(f"<b>{shot.sequence_order}. {shot.description}</b>", styles["body"]))
        meta = []
        if shot.shared:
            meta.append("Shared across campaigns")
        if shot.framing:
            meta.append(f"Framing: {shot.framing}")
        if shot.lighting:
            meta.append(f"Lighting: {shot.lighting}")
        if shot.props:
            meta.append(f"Props: {shot.props}")
        if shot.negative_space:
            meta.append(f"Negative space: {shot.negative_space}")
        for line in meta:
            story.append(Paragraph(f"• {line}", styles["small"]))
        story.append(Spacer(1, 0.08 * inch))

    if optional:
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph("Optional shots", styles["h2"]))
        for shot in optional:
            story.append(
                Paragraph(f"{shot.sequence_order}. {shot.description}", styles["body"])
            )

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Simple storyboard order", styles["h2"]))
    story.append(
        Paragraph(
            " → ".join(s.shot_id.replace("_", " ") for s in shots) or "Hero → detail → CTA plate",
            styles["body"],
        )
    )
    if session and session.notes:
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(session.notes, styles["muted"]))
    story.append(_page_break())

    # PAGE 3 — Publishing plan
    story.append(Paragraph("PUBLISHING PLAN", styles["eyebrow"]))
    story.append(Paragraph("Sequence by window", styles["h1"]))
    story.append(Spacer(1, 0.1 * inch))

    plan = intel.publishing_plan
    if not plan:
        plan_rows = [
            ["Window", "Platform", "Format", "Role", "CTA"],
            ["Day 1", "Instagram", "Reel", "Awareness", "Join the waitlist"],
            ["Day 2–3", "Pinterest", "Video Pin", "Familiarity", "Join the waitlist"],
            ["Day 4–5", "Pinterest", "Static Pin", "Familiarity", "First Edition"],
            ["Day 6–7", "Instagram", "Carousel", "Education", "Join the waitlist"],
        ]
    else:
        plan_rows = [["Window", "Platform", "Format", "Role", "CTA"]]
        for item in plan[:10]:
            plan_rows.append(
                [
                    item.window_label,
                    item.platform,
                    item.format_name,
                    item.campaign_role,
                    item.cta,
                ]
            )
    story.append(_grid_table(plan_rows))
    story.append(Spacer(1, 0.15 * inch))
    story.append(
        Paragraph(
            "Cadence is a planning recommendation based on campaign needs and current "
            "assumptions — not an optimized or proven schedule.",
            styles["muted"],
        )
    )

    # PAGE 4 — Deadlines (optional but included when alerts exist)
    alerts = [a for a in intel.alerts if a.high_value][:4]
    opportunities = [o for o in intel.opportunities if o.included][:3]
    if alerts or opportunities:
        story.append(_page_break())
        story.append(Paragraph("DEADLINES AND OPPORTUNITIES", styles["eyebrow"]))
        story.append(Paragraph("What matters now", styles["h1"]))
        story.append(Spacer(1, 0.1 * inch))
        for alert in alerts:
            story.append(
                Paragraph(
                    f"<b>{alert.alert_type.value.upper()}: {alert.title}</b>",
                    styles["body"],
                )
            )
            story.append(Paragraph(alert.detail, styles["small"]))
            story.append(
                Paragraph(
                    f"Action: {alert.recommended_action}"
                    + (
                        f" · Start by {_fmt_date(alert.start_by)}"
                        if alert.start_by
                        else ""
                    )
                    + f" · {alert.hardness.value} · confidence {alert.confidence}",
                    styles["muted"],
                )
            )
            story.append(Spacer(1, 0.1 * inch))
        if opportunities:
            story.append(Paragraph("Relevant moments", styles["h2"]))
            for opp in opportunities:
                when = _fmt_date(opp.occurrence_date) or "date unconfirmed"
                uncertain = " (confirm date)" if opp.date_uncertain else ""
                story.append(
                    Paragraph(
                        f"• {opp.name} — {when}{uncertain}. {opp.reason}",
                        styles["small"],
                    )
                )

    # PAGE 5 — Creative Director notes
    story.append(_page_break())
    story.append(Paragraph("CREATIVE DIRECTOR NOTES", styles["eyebrow"]))
    story.append(Paragraph("Highest-impact advice", styles["h1"]))
    story.append(Spacer(1, 0.1 * inch))
    notes = [
        "Prioritize the page-turn and hero ritual shots — they feed the most formats.",
        "When time is limited, drop optional lifestyle before shared hero coverage.",
        "Do not film novelty setups that break the quiet reading-hour identity.",
        "Fallback: one strong Reel + two Pins still supports a short waitlist window.",
        "Runway expands when one hero sequence yields clean loop and still-frame crops.",
    ]
    for note in notes:
        story.append(Paragraph(f"• {note}", styles["body"]))
    story.append(Spacer(1, 0.2 * inch))
    if deliverable:
        story.append(Paragraph("Assumptions that change the estimate", styles["h2"]))
        for assumption in deliverable.assumptions:
            story.append(Paragraph(f"• {assumption}", styles["small"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return doc.page


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(0.7 * inch, 0.55 * inch, letter[0] - 0.7 * inch, 0.55 * inch)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.7 * inch, 0.35 * inch, "BettyOS · Production Brief")
    canvas.drawRightString(letter[0] - 0.7 * inch, 0.35 * inch, f"{doc.page}")
    canvas.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=JADE,
            tracking=1.5,
            spaceAfter=4,
        ),
        "hero": ParagraphStyle(
            "hero",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=INK,
            leading=26,
            spaceAfter=6,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=INK,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=JADE,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=INK,
            leading=14,
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=MUTED,
            leading=12,
            leftIndent=8,
            spaceAfter=1,
        ),
        "muted": ParagraphStyle(
            "muted",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            leading=11,
            spaceAfter=4,
        ),
    }


def _page_break():
    from reportlab.platypus import PageBreak

    return PageBreak()


def _kv_table(rows: list[list[str]]) -> Table:
    data = []
    for label, value in rows:
        data.append(
            [
                Paragraph(f"<b>{label}</b>", ParagraphStyle("k", fontSize=9, textColor=MUTED)),
                Paragraph(str(value), ParagraphStyle("v", fontSize=10, textColor=INK, leading=13)),
            ]
        )
    table = Table(data, colWidths=[2.1 * inch, 4.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
            ]
        )
    )
    return table


def _grid_table(rows: list[list[str]]) -> Table:
    styles_body = ParagraphStyle("cell", fontSize=8, textColor=INK, leading=10)
    styles_head = ParagraphStyle("head", fontSize=8, textColor=JADE, fontName="Helvetica-Bold")
    data = []
    for index, row in enumerate(rows):
        style = styles_head if index == 0 else styles_body
        data.append([Paragraph(str(cell), style) for cell in row])
    table = Table(data, colWidths=[1.1 * inch, 1.1 * inch, 1.3 * inch, 1.3 * inch, 1.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#EFE6D9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
            ]
        )
    )
    return table


def _portfolio_line(intel: CampaignIntelligence) -> str:
    parts = []
    for rec in intel.recommendations:
        if rec.decision.value in {"dismiss", "not_now"}:
            continue
        parts.append(f"{rec.campaign_name} ({rec.role.value.replace('_', ' ')})")
    return "; ".join(parts) or "Primary campaign"


def _cadence_line(intel: CampaignIntelligence) -> str:
    if not intel.cadence:
        return "—"
    return "; ".join(
        f"{c.platform}: {c.min_per_week}–{c.max_per_week}/week" for c in intel.cadence
    )


def _range_label(range_obj, *, unit: str | None = None) -> str:
    if range_obj is None:
        return "—"
    use_unit = unit or getattr(range_obj, "unit", "days")
    if range_obj.min_days == range_obj.max_days:
        if use_unit == "assets":
            return f"{range_obj.min_days}"
        singular = use_unit.rstrip("s")
        label = singular if range_obj.min_days == 1 else use_unit
        return f"{range_obj.min_days} {label}"
    if use_unit == "assets":
        return f"{range_obj.min_days} to {range_obj.max_days}"
    return f"{range_obj.min_days} to {range_obj.max_days} {use_unit}"


def _minutes_label(range_obj) -> str | None:
    if range_obj is None:
        return None
    if range_obj.min_days == range_obj.max_days:
        return f"{range_obj.min_days} minutes"
    return f"{range_obj.min_days} to {range_obj.max_days} minutes"


def _fmt_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _brief_summary(intel: CampaignIntelligence) -> dict[str, Any]:
    deliverable = intel.deliverable_estimate
    runway = intel.current_runway()
    return {
        "final_assets": (
            f"{_range_label(deliverable.final_assets, unit='assets')} final assets"
            if deliverable
            else None
        ),
        "filming": _minutes_label(deliverable.filming_minutes) if deliverable else None,
        "runway": f"Approximately {_range_label(runway.days)}" if runway else None,
        "confidence": deliverable.confidence if deliverable else "medium",
    }


def _publishing_csv(intel: CampaignIntelligence) -> str:
    lines = ["day_offset,window,platform,format,role,cta"]
    for item in intel.publishing_plan:
        lines.append(
            ",".join(
                [
                    str(item.day_offset),
                    _csv(item.window_label),
                    _csv(item.platform),
                    _csv(item.format_name),
                    _csv(item.campaign_role),
                    _csv(item.cta),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _csv(value: str) -> str:
    text = value.replace('"', '""')
    return f'"{text}"'
