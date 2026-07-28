"""Build ContentPieceRecord list from a content package markdown file."""

from __future__ import annotations

import re
from pathlib import Path

from src.package_parse import list_content_pieces
from src.templates.models import ContentPieceRecord


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


def _assets(body: str) -> list[str]:
    raw = _field_after(body, ("Exact Asset File Paths", "Assets"))
    paths: list[str] = []
    for line in raw.splitlines():
        cleaned = re.sub(r"^[-*\s]+", "", line.strip()).replace("`", "")
        cleaned = re.split(r"\s+[—\-]\s+", cleaned, maxsplit=1)[0].strip()
        if cleaned and not cleaned.startswith("**"):
            paths.append(cleaned)
    return paths


def piece_id_for(number: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    slug = slug[:40] or "piece"
    return f"piece_{number.zfill(3)}_{slug}"


def parse_content_piece_records(package_text: str) -> list[ContentPieceRecord]:
    records: list[ContentPieceRecord] = []
    for piece in list_content_pieces(package_text):
        body = piece["body"]
        records.append(
            ContentPieceRecord(
                piece_id=piece_id_for(piece["number"], piece["title"]),
                title=piece["title"],
                platform=_clean(_field_after(body, ("Platform",))),
                objective=_clean(_field_after(body, ("Objective",))),
                format=_clean(
                    _field_after(
                        body,
                        (
                            "Suggested Duration/Format",
                            "Suggested Format",
                            "Format",
                            "Duration",
                        ),
                    )
                ),
                source_assets=_assets(body),
                body_markdown=body,
                number=piece["number"],
            )
        )
    return records


def load_package_pieces(package_path: Path) -> list[ContentPieceRecord]:
    return parse_content_piece_records(package_path.read_text(encoding="utf-8"))
