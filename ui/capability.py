"""Honest capability reporting.

The template registry records an intended `renderer_status`. For several
templates that intent is ahead of the code: dispatch lets the render start and
it either fails outright or produces generic output. This module is the single
place that knows the difference, so the interface never claims more than
BettyOS can do.

Nothing here writes to disk. Evidence timestamps are read from existing
artifacts so "last successful run" is observed, not asserted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.common import OUTPUTS_DIR
from src.templates.registry import LEGACY_FOLDER_TO_TEMPLATE, TEMPLATE_TO_LEGACY_FOLDER, list_templates

# Video templates with a real code path. Every other video template raises
# before rendering (renderers/video.py:47-51), so its button must be disabled.
IMPLEMENTED_VIDEO_TEMPLATES = {"cinematic_multi_clip_reel", "single_clip_atmospheric_loop"}

MEDIA_SUFFIXES = {".mp4", ".mov", ".png", ".jpg", ".jpeg", ".md"}


@dataclass(frozen=True)
class Renderability:
    can_render: bool
    reason: str = ""


@dataclass
class Capability:
    name: str
    tier: str  # "working" | "partial" | "unavailable"
    summary: str = ""
    works: str = ""
    does_not_work: str = ""
    reason: str = ""
    next_step: str = ""
    evidence: str = ""


# --- What a template really does --------------------------------------------

# Keyed by template_id. Only templates whose behaviour differs from what the
# registry description implies need an entry.
_TEMPLATE_NOTES: dict[str, str] = {
    "single_clip_atmospheric_loop": (
        "Renders a fixed studio clip. The source clip you choose is not used yet."
    ),
    "product_detail_reel": "No renderer exists for this template.",
    "narrative_text_reel": "No renderer exists for this template.",
    "contrast_reel": "No renderer exists for this template.",
    "slideshow_reel": "No renderer exists for this template.",
    "text_led_editorial_pin": "Places your headline at the top. Quote text is not read separately.",
    "product_feature_pin": "Produces a standard pin. Product name and price are not laid out.",
    "pinterest_collage_pin": "Needs two or more images for a collage. With one it falls back to a single image.",
    "product_reveal": "Produces a standard announcement card. Product name and price are not laid out.",
    "bundle_overview": "Produces a standard announcement card. The item list is not laid out.",
    "waitlist_announcement": "Produces a standard announcement card. Launch date is not laid out.",
    "launch_countdown": "Produces a standard card. There is no countdown layout.",
    "testimonial_social_proof": "Produces a standard card. Testimonial and attribution are not laid out.",
    "faq_creative": "Produces a standard card. Question and answer pairs are not laid out.",
    "square_editorial_post": "Produces a standard square image from your first source asset.",
    "story_frame": "Produces a standard vertical image. Overlay text and stickers are not laid out.",
    "editorial_carousel": "Produces three slides with standard copy. Your slide copy is not used yet.",
    "product_detail_carousel": "Produces three slides with standard copy. Your slide copy is not used yet.",
    "letter_carousel": "Produces three slides with standard copy. Letter text is not used yet.",
    "story_sequence": "Produces three vertical slides with standard copy. Your slide copy is not used yet.",
    "product_description": "Writes a plain markdown draft from the copy fields you supply.",
    "website_announcement": "Writes a plain markdown draft from the copy fields you supply.",
    "founder_note": "Writes a letter-style markdown draft. Works the same as Email Letter.",
}

# Templates whose registry status overstates the code. Value is the honest key.
_STATUS_CORRECTIONS: dict[str, str] = {
    # Renders, but ignores the clip the user picked.
    "single_clip_atmospheric_loop": "partial",
    # Four carousel templates share one generic three-slide layout.
    "editorial_carousel": "partial",
    "product_detail_carousel": "partial",
    "story_sequence": "partial",
    # Static templates share one generic canvas; template-specific fields unused.
    "editorial_static_pin": "partial",
    "text_led_editorial_pin": "partial",
    "product_feature_pin": "partial",
    "pinterest_collage_pin": "partial",
    "waitlist_announcement": "partial",
    "product_reveal": "partial",
    "bundle_overview": "partial",
    # Copy templates write a usable markdown draft from supplied fields only.
    "product_description": "partial",
    "website_announcement": "partial",
    # Registry under-rates this one: same implementation as Email Letter.
    "founder_note": "ready",
}


def template_note(template_id: str) -> str | None:
    """Plain-language description of what actually happens, if it differs."""
    return _TEMPLATE_NOTES.get(template_id)


def effective_status(template_id: str, registry_status: str) -> str:
    """Registry status corrected against the renderer code."""
    if registry_status in {"planned", "manual_only"}:
        return registry_status
    return _STATUS_CORRECTIONS.get(template_id, registry_status)


def renderability(template_id: str, registry_status: str, renderer_module: str) -> Renderability:
    """Whether a render can succeed at all, and why not when it cannot."""
    if registry_status == "planned":
        return Renderability(False, "This template is described but has no renderer yet.")
    if registry_status == "manual_only":
        return Renderability(False, "This template is finished by hand outside BettyOS.")
    if renderer_module == "video" and template_id not in IMPLEMENTED_VIDEO_TEMPLATES:
        return Renderability(False, "No video renderer exists for this template yet.")
    return Renderability(True)


# What BettyOS can do about a recommendation is decided by
# `services.revision_classifier`, which reads the recommendation in context
# against what the renderers actually accept.


# --- Evidence gathered from disk --------------------------------------------

def _fmt(moment: datetime | None) -> str:
    if moment is None:
        return ""
    return moment.strftime("%-d %b %Y, %H:%M")


def to_naive(moment: datetime | None) -> datetime | None:
    """Local naive time, so stored ISO stamps and file mtimes stay comparable."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone().replace(tzinfo=None)


def parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return to_naive(datetime.fromisoformat(value))
    except ValueError:
        return None


_parse_iso = parse_iso


def _newest(paths: list[Path]) -> datetime | None:
    stamps = [
        datetime.fromtimestamp(p.stat().st_mtime) for p in paths if p.is_file()
    ]
    return max(stamps) if stamps else None


def _campaign_dirs() -> list[Path]:
    if not OUTPUTS_DIR.is_dir():
        return []
    return sorted(p for p in OUTPUTS_DIR.glob("*_campaign") if p.is_dir())


def folder_names_for_template(template_id: str) -> list[str]:
    """Canonical folder plus the legacy folder migration left behind."""
    names = [template_id]
    legacy = TEMPLATE_TO_LEGACY_FOLDER.get(template_id)
    if legacy:
        names.append(legacy)
    return names


def last_render_at(template_id: str) -> datetime | None:
    """Newest render output for a template across every campaign."""
    candidates: list[Path] = []
    for campaign in _campaign_dirs():
        for folder_name in folder_names_for_template(template_id):
            folder = campaign / folder_name
            if not folder.is_dir():
                continue
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
                    candidates.append(path)
    return _newest(candidates)


def last_review_at() -> datetime | None:
    return _newest([OUTPUTS_DIR / "latest_scores.json"])


def last_approval_save_at() -> datetime | None:
    stamps: list[datetime] = []
    for campaign in _campaign_dirs():
        path = campaign / "approvals.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        moment = _parse_iso((data or {}).get("updated_at"))
        if moment:
            stamps.append(moment)
    return max(stamps) if stamps else None


def last_assignment_save_at() -> datetime | None:
    stamps: list[datetime] = []
    for path in OUTPUTS_DIR.glob("*.assignments.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        moment = _parse_iso((data or {}).get("updated_at"))
        if moment:
            stamps.append(moment)
    return max(stamps) if stamps else None


def last_revision_run_at() -> datetime | None:
    """Newest revision actually applied, across every campaign's revision store."""
    stamps: list[datetime] = []

    for campaign in _campaign_dirs():
        path = campaign / "revisions" / "revision_requests.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for request in (data or {}).get("requests") or []:
            if not isinstance(request, dict) or request.get("status") != "applied":
                continue
            moment = _parse_iso(request.get("applied_at")) or _parse_iso(request.get("updated_at"))
            if moment:
                stamps.append(moment)

    return max(stamps) if stamps else None


def exports_dir() -> Path:
    return OUTPUTS_DIR / "exports"


def last_export_at() -> datetime | None:
    folder = exports_dir()
    if not folder.is_dir():
        return None
    return _newest(sorted(folder.glob("*.zip")))


# --- Capability panel -------------------------------------------------------

def _evidence(label: str, moment: datetime | None, empty: str) -> str:
    return f"{label} {_fmt(moment)}" if moment else empty


def capability_report() -> dict[str, list[Capability]]:
    """Grouped Working / Partial / Not Available capability rows."""
    templates = list_templates()
    by_id = {t.template_id: t for t in templates}

    working: list[Capability] = []
    partial: list[Capability] = []
    unavailable: list[Capability] = []

    reel = by_id.get("cinematic_multi_clip_reel")
    if reel is not None:
        working.append(
            Capability(
                name=reel.display_name,
                tier="working",
                summary="Stitches your selected clips into one vertical video with a caption.",
                evidence=_evidence(
                    "Last successful render:", last_render_at(reel.template_id), "Not run yet"
                ),
            )
        )

    working.append(
        Capability(
            name="Creative Review",
            tier="working",
            summary="Scores the campaign and proposes specific improvements.",
            evidence=_evidence("Last successful run:", last_review_at(), "Not run yet"),
        )
    )
    working.append(
        Capability(
            name="Approval saving",
            tier="working",
            summary="Approval decisions and notes are written to disk and read back to confirm.",
            evidence=_evidence("Last successful save:", last_approval_save_at(), "Not saved yet"),
        )
    )
    working.append(
        Capability(
            name="Template assignment saving",
            tier="working",
            summary="Template choices persist across restarts.",
            evidence=_evidence("Last successful save:", last_assignment_save_at(), "Not saved yet"),
        )
    )
    working.append(
        Capability(
            name="Export packaging",
            tier="working",
            summary="Collects approved renders into a downloadable ZIP.",
            evidence=_evidence("Last package created:", last_export_at(), "Not created yet"),
        )
    )

    loop = by_id.get("single_clip_atmospheric_loop")
    if loop is not None:
        partial.append(
            Capability(
                name=loop.display_name,
                tier="partial",
                works="Renders a finished vertical loop with a caption.",
                does_not_work="Ignores the source clip you select and always uses one fixed studio clip.",
                evidence=_evidence(
                    "Last successful render:", last_render_at(loop.template_id), "Not run yet"
                ),
            )
        )

    static_count = sum(1 for t in templates if t.renderer_module == "static")
    partial.append(
        Capability(
            name="Still image templates",
            tier="partial",
            works=(
                f"All {static_count} still templates produce a branded image and caption "
                "from your first source asset."
            ),
            does_not_work=(
                "Template-specific fields are not laid out — product name, price, quote, "
                "testimonial, launch date and question/answer pairs are ignored."
            ),
            evidence=_evidence(
                "Last successful render:", last_render_at("editorial_static_pin"), "Not run yet"
            ),
        )
    )

    carousel_count = sum(1 for t in templates if t.renderer_module == "carousel")
    partial.append(
        Capability(
            name="Carousel templates",
            tier="partial",
            works=f"All {carousel_count} carousel templates produce three slides and a caption.",
            does_not_work=(
                "Every carousel uses the same three-slide layout and standard copy. "
                "Your own slide copy is not used, and slide count is fixed at three."
            ),
            evidence=_evidence(
                "Last successful render:", last_render_at("editorial_carousel"), "Not run yet"
            ),
        )
    )

    copy_count = sum(1 for t in templates if t.renderer_module == "copy")
    partial.append(
        Capability(
            name="Copy templates",
            tier="partial",
            works=f"All {copy_count} copy templates write a markdown draft you can edit.",
            does_not_work=(
                "Copy is assembled from the fields you supply. It is not written from the "
                "Brand Guide, and several templates share one generic layout."
            ),
            evidence=_evidence(
                "Last successful render:", last_render_at("instagram_caption"), "Not run yet"
            ),
        )
    )

    working.append(
        Capability(
            name="AI-assisted copy revisions",
            tier="working",
            summary=(
                "Proposes replacement wording from the Brand Guide for on-screen copy, "
                "captions, calls to action, email copy and Pinterest metadata. Every "
                "option is checked against the Brand Guide before you see it, and nothing "
                "is applied until you approve it."
            ),
            evidence=_evidence("Last suggestion applied:", last_revision_run_at(), "Not run yet"),
        )
    )

    partial.append(
        Capability(
            name="Applying a revision as a new version",
            tier="partial",
            works=(
                "Rebuilds the Cinematic Multi-Clip Reel with revised on-screen copy, clips, "
                "duration or CTA timing, and writes new versions of copy documents. The "
                "version it came from is never touched."
            ),
            does_not_work=(
                "Still images, carousels and the Single-Clip Atmospheric Loop cannot be "
                "rebuilt from a revision, and no renderer accepts a changed font size, "
                "text position, crop or transition."
            ),
            evidence=_evidence("Last successful run:", last_revision_run_at(), "Not run yet"),
        )
    )

    missing_video = [
        by_id[tid].display_name
        for tid in ("product_detail_reel", "narrative_text_reel", "contrast_reel", "slideshow_reel")
        if tid in by_id
    ]
    if missing_video:
        unavailable.append(
            Capability(
                name=", ".join(missing_video),
                tier="unavailable",
                reason="No video renderer has been written for these templates.",
                next_step="A renderer must be added to the video family before they can run.",
            )
        )

    planned = [t.display_name for t in templates if t.renderer_status == "planned"]
    if planned:
        unavailable.append(
            Capability(
                name=", ".join(planned),
                tier="unavailable",
                reason="Described in the template list but no renderer exists.",
                next_step="A renderer must be written before these can produce output.",
            )
        )

    manual_only = [t.display_name for t in templates if t.renderer_status == "manual_only"]
    if manual_only:
        unavailable.append(
            Capability(
                name=", ".join(manual_only),
                tier="unavailable",
                reason="Intended to be finished by hand.",
                next_step="Produce these outside BettyOS and add them to the campaign folder.",
            )
        )

    unavailable.append(
        Capability(
            name="Automatic template creation",
            tier="unavailable",
            reason="BettyOS does not write renderer code for a new template.",
            next_step="New templates are added by a developer, then appear in the template list.",
        )
    )

    # Studio capabilities — Ready only with persisted successful tests
    try:
        from studio.capabilities import capability_rows

        for row in capability_rows():
            status = row.get("status") or "Planned"
            evidence_bits = []
            if row.get("last_successful_test"):
                evidence_bits.append(
                    f"Last success: {row['last_successful_test'].get('at', '')} "
                    f"{row['last_successful_test'].get('note', '')}".strip()
                )
            if row.get("last_failure"):
                evidence_bits.append(
                    f"Last failure: {row['last_failure'].get('at', '')} "
                    f"{row['last_failure'].get('note', '')}".strip()
                )
            evidence = " · ".join(evidence_bits) if evidence_bits else "Not tested yet"
            cap = Capability(
                name=f"Studio · {row['name']}",
                tier=(
                    "working"
                    if status == "Ready"
                    else "partial"
                    if status in {"Partial", "Setup Required"}
                    else "unavailable"
                ),
                summary=row.get("implementation_note") or "",
                works=row.get("implementation_note") or "",
                does_not_work=row.get("known_limitation") or "",
                reason="" if status == "Ready" else (row.get("known_limitation") or status),
                next_step="" if status == "Ready" else "Exercise this control end-to-end in Studio.",
                evidence=evidence,
            )
            if cap.tier == "working":
                working.append(cap)
            elif cap.tier == "partial":
                partial.append(cap)
            else:
                unavailable.append(cap)
    except Exception:  # noqa: BLE001
        unavailable.append(
            Capability(
                name="Studio capability reporting",
                tier="unavailable",
                reason="Studio capability store could not be loaded.",
            )
        )

    return {"working": working, "partial": partial, "unavailable": unavailable}


# --- Render output discovery -------------------------------------------------

_VERSION_RE = re.compile(r"_v(\d+)\.")


def version_in_filename(name: str) -> int | None:
    match = _VERSION_RE.search(name)
    return int(match.group(1)) if match else None


def canonical_template_for_folder(folder_name: str) -> str:
    """Canonical template id for a render folder, legacy names included."""
    return LEGACY_FOLDER_TO_TEMPLATE.get(folder_name, folder_name)
