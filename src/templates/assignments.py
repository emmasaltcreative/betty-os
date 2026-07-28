"""Persistent content-piece → template assignments."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.common import OUTPUTS_DIR
from src.persistence import atomic_write_json, load_json
from src.templates.classifier import classify_content_piece
from src.templates.models import ContentPieceRecord, PieceAssignment


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def assignments_path_for_package(package_path: Path) -> Path:
    return package_path.with_suffix("").with_name(package_path.stem + ".assignments.json")


def load_assignments(package_path: Path) -> dict[str, Any]:
    path = assignments_path_for_package(package_path)
    data = load_json(path, default=None)
    if not isinstance(data, dict):
        return {
            "package": package_path.name,
            "updated_at": None,
            "pieces": {},
        }
    data.setdefault("package", package_path.name)
    data.setdefault("pieces", {})
    return data


def save_assignments(package_path: Path, data: dict[str, Any]) -> Path:
    path = assignments_path_for_package(package_path)
    payload = {
        "package": package_path.name,
        "updated_at": _now(),
        "pieces": data.get("pieces") or {},
    }
    return atomic_write_json(path, payload)


def set_piece_template(
    package_path: Path,
    *,
    piece_id: str,
    template_id: str,
    classification: dict[str, Any] | None = None,
    override: bool = True,
) -> PieceAssignment:
    data = load_assignments(package_path)
    pieces = dict(data.get("pieces") or {})
    existing = dict(pieces.get(piece_id) or {})
    class_payload = classification or {}
    assignment = PieceAssignment(
        piece_id=piece_id,
        template_id=template_id,
        primary_template_id=str(
            class_payload.get("primary_template_id")
            or existing.get("primary_template_id")
            or template_id
        ),
        confidence=float(
            class_payload.get("confidence", existing.get("confidence", 1.0 if override else 0.0))
        ),
        rationale=str(
            class_payload.get("rationale")
            or existing.get("rationale")
            or ("User override" if override else "")
        ),
        alternative_template_ids=list(
            class_payload.get("alternative_template_ids")
            or existing.get("alternative_template_ids")
            or []
        ),
        missing_requirements=list(
            class_payload.get("missing_requirements")
            or existing.get("missing_requirements")
            or []
        ),
        override=override,
        updated_at=_now(),
    )
    pieces[piece_id] = assignment.model_dump()
    data["pieces"] = pieces
    save_assignments(package_path, data)
    # Reload to confirm persistence.
    reloaded = load_assignments(package_path)
    saved = (reloaded.get("pieces") or {}).get(piece_id)
    if not isinstance(saved, dict) or saved.get("template_id") != template_id:
        raise RuntimeError(f"Failed to persist template assignment for {piece_id}")
    return PieceAssignment.model_validate(saved)


def ensure_assignments_for_pieces(
    package_path: Path,
    pieces: list[ContentPieceRecord],
) -> dict[str, PieceAssignment]:
    """Classify any unassigned pieces and persist; honor overrides."""
    data = load_assignments(package_path)
    pieces_map = dict(data.get("pieces") or {})
    changed = False
    result: dict[str, PieceAssignment] = {}
    for piece in pieces:
        existing = pieces_map.get(piece.piece_id)
        if isinstance(existing, dict) and existing.get("template_id"):
            result[piece.piece_id] = PieceAssignment.model_validate(existing)
            continue
        classification = classify_content_piece(piece)
        assignment = PieceAssignment(
            piece_id=piece.piece_id,
            template_id=classification.primary_template_id,
            primary_template_id=classification.primary_template_id,
            confidence=classification.confidence,
            rationale=classification.rationale,
            alternative_template_ids=classification.alternative_template_ids,
            missing_requirements=classification.missing_requirements,
            override=False,
            updated_at=_now(),
        )
        pieces_map[piece.piece_id] = assignment.model_dump()
        result[piece.piece_id] = assignment
        changed = True
    if changed:
        data["pieces"] = pieces_map
        save_assignments(package_path, data)
    return result


def latest_package_assignments() -> tuple[Path | None, dict[str, Any]]:
    packages = sorted(OUTPUTS_DIR.glob("*_content_package.md"), reverse=True)
    if not packages:
        return None, {"package": None, "pieces": {}}
    path = packages[0]
    return path, load_assignments(path)
