"""Template coverage analysis for the Renders page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common import ROOT, find_latest_content_package
from src.package_parse import list_content_pieces

COVERAGE_STATUSES = (
    "ready_to_render",
    "template_needed",
    "missing_source_asset",
    "invalid_configuration",
)

COVERAGE_STATUS_LABELS = {
    "ready_to_render": "Ready to Render",
    "template_needed": "Template Needed",
    "missing_source_asset": "Missing Source Asset",
    "invalid_configuration": "Invalid Configuration",
}

# Human labels for reusable template categories when a piece is unsupported.
FORMAT_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    (r"static|still|feed|pin|4:5|2:3", "Static Image Template"),
    (r"carousel|multi[- ]image", "Carousel Template"),
    (r"story|stories", "Stories Template"),
    (r"reel|9:16|vertical video", "Short-Form Video Template"),
    (r"loop|page\s*turn", "Looping Clip Template"),
    (r"ritual", "Multi-Clip Ritual Reel Template"),
)


@dataclass
class SupportedTemplateView:
    template_name: str
    content_formats: list[str]
    latest_successful_render: str | None
    status: str
    piece_title: str | None = None
    folder_name: str = ""
    piece_id: str = ""


@dataclass
class UnsupportedPieceView:
    piece_title: str
    platform: str
    requested_format: str
    proposed_template_category: str
    reason: str
    related_piece_titles: list[str] = field(default_factory=list)
    status: str = "template_needed"
    piece_number: str = ""


@dataclass
class TemplateCoverageView:
    content_piece_note: str
    content_format_note: str
    renderer_note: str
    render_output_note: str
    supported: list[SupportedTemplateView]
    unsupported: list[UnsupportedPieceView]
    package_name: str | None = None


def _field_after(section: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(
            rf"\*\*{re.escape(label)}:?\*\*\s*[:\-]?\s*(.*?)(?=\n\*\*[A-Z]|\n### |\n## |\Z)",
            section,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return ""


def _clean(text: str) -> str:
    lines = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            stripped = stripped[1:].strip()
        lines.append(stripped)
    return "\n".join(lines).strip()


def _propose_category(title: str, platform: str, fmt: str) -> str:
    blob = f"{title} {platform} {fmt}".lower()
    for pattern, label in FORMAT_CATEGORY_HINTS:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            return label
    return "Custom Format Template"


def _extract_asset_paths(body: str) -> list[str]:
    raw = _field_after(body, ("Exact Asset File Paths", "Assets"))
    paths: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("**"):
            continue
        cleaned = re.sub(r"^[-*\s]+", "", cleaned)
        cleaned = cleaned.replace("`", "")
        cleaned = re.split(r"\s+[—\-]\s+", cleaned, maxsplit=1)[0].strip()
        if cleaned:
            paths.append(cleaned)
    return paths


def _latest_render_label(render_dir: Path | None) -> str | None:
    if render_dir is None or not render_dir.is_dir():
        return None
    videos = sorted(render_dir.glob("*.mp4")) + sorted(render_dir.glob("*.mov"))
    if not videos:
        return None
    # Prefer versioned outputs when present.
    versioned = [p for p in videos if re.search(r"_v\d+\.", p.name)]
    chosen = sorted(versioned, key=lambda p: p.name)[-1] if versioned else videos[0]
    settings_path = render_dir / "render_settings.json"
    stamp = ""
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            version = (settings.get("versioning") or {}).get("version")
            if version:
                stamp = f" · v{version}"
        except json.JSONDecodeError:
            pass
    try:
        rel = chosen.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        rel = chosen.name
    return f"{chosen.stem.replace('_', ' ')}{stamp} ({rel})"


def _template_formats(piece_id: str) -> list[str]:
    if piece_id == "ritual-reel":
        return ["Instagram Reels (9:16)", "Multi-clip vertical video"]
    if piece_id == "page-turn-loop":
        return ["Short looping clip", "Pinterest / Reels loop"]
    return ["Supported draft format"]


def _related_titles(
    piece: dict[str, str],
    skipped: list[dict[str, str]],
    category: str,
) -> list[str]:
    related: list[str] = []
    for other in skipped:
        if other["title"] == piece["title"]:
            continue
        other_cat = other.get("category") or ""
        if other_cat == category:
            related.append(other["title"])
    return related


def build_template_coverage(
    *,
    package_text: str | None = None,
    package_path: Path | None = None,
    campaign_dir: Path | None = None,
) -> TemplateCoverageView:
    """Build supported/unsupported coverage for the Renders page."""
    from main import SUPPORTED_RENDER_TEMPLATES, match_supported_render_queue

    text = package_text
    pkg_name = package_path.name if package_path else None
    if text is None:
        try:
            path = package_path or find_latest_content_package()
            text = path.read_text(encoding="utf-8")
            pkg_name = path.name
        except Exception:  # noqa: BLE001 — coverage can render empty state
            text = ""
            pkg_name = None

    queued, skipped_raw = match_supported_render_queue(text) if text else ([], [])
    pieces_by_title = {p["title"]: p for p in list_content_pieces(text)} if text else {}

    supported: list[SupportedTemplateView] = []
    claimed_ids = {job["piece_id"] for job in queued}

    for job in queued:
        folder_name = str(job["folder_name"])
        render_dir = (campaign_dir / folder_name) if campaign_dir else None
        status = "ready_to_render"
        missing = False
        piece = pieces_by_title.get(str(job["piece_title"]))
        if piece:
            for asset in _extract_asset_paths(piece["body"]):
                if not (ROOT / asset).exists():
                    missing = True
                    break
        if missing:
            status = "missing_source_asset"
        elif render_dir and render_dir.is_dir() and not any(render_dir.glob("*.mp4")):
            status = "invalid_configuration"

        supported.append(
            SupportedTemplateView(
                template_name=str(job["label"]),
                content_formats=_template_formats(str(job["piece_id"])),
                latest_successful_render=_latest_render_label(render_dir),
                status=status,
                piece_title=str(job.get("piece_title") or ""),
                folder_name=folder_name,
                piece_id=str(job["piece_id"]),
            )
        )

    # Templates that exist but were not matched in this package still appear.
    for template in SUPPORTED_RENDER_TEMPLATES:
        if template["piece_id"] in claimed_ids:
            continue
        folder_name = str(template["folder_name"])
        render_dir = (campaign_dir / folder_name) if campaign_dir else None
        supported.append(
            SupportedTemplateView(
                template_name=str(template["label"]),
                content_formats=_template_formats(str(template["piece_id"])),
                latest_successful_render=_latest_render_label(render_dir),
                status="ready_to_render"
                if _latest_render_label(render_dir)
                else "ready_to_render",
                piece_title=None,
                folder_name=folder_name,
                piece_id=str(template["piece_id"]),
            )
        )

    skipped_enriched: list[dict[str, str]] = []
    for item in skipped_raw:
        piece = pieces_by_title.get(item["title"])
        body = piece["body"] if piece else ""
        platform = _clean(_field_after(body, ("Platform",))) or "—"
        fmt = _clean(
            _field_after(
                body,
                ("Suggested Duration/Format", "Suggested Format", "Format", "Duration"),
            )
        ) or "—"
        category = _propose_category(item["title"], platform, fmt)
        asset_paths = _extract_asset_paths(body) if body else []
        status = "template_needed"
        reason = item.get("reason") or "No supported render template"
        if asset_paths and any(not (ROOT / p).exists() for p in asset_paths):
            status = "missing_source_asset"
            reason = "Source asset path missing on disk"
        skipped_enriched.append(
            {
                **item,
                "platform": platform,
                "format": fmt,
                "category": category,
                "status": status,
                "reason": reason,
                "number": piece["number"] if piece else "",
            }
        )

    unsupported: list[UnsupportedPieceView] = []
    for item in skipped_enriched:
        unsupported.append(
            UnsupportedPieceView(
                piece_title=item["title"],
                platform=item["platform"],
                requested_format=item["format"],
                proposed_template_category=item["category"],
                reason=item["reason"],
                related_piece_titles=_related_titles(
                    {"title": item["title"]}, skipped_enriched, item["category"]
                ),
                status=item["status"],
                piece_number=item.get("number") or "",
            )
        )

    return TemplateCoverageView(
        content_piece_note="A content piece is one planned unit in the content package.",
        content_format_note="A content format is the intended shape (Reels, static pin, feed still).",
        renderer_note="A renderer/template is the Production Brain recipe BettyOS knows how to execute.",
        render_output_note="A render output is the versioned draft video or still BettyOS wrote to disk.",
        supported=supported,
        unsupported=unsupported,
        package_name=pkg_name,
    )
