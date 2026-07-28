"""Template registry loader and helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.common import ROOT
from src.persistence import atomic_write_json, load_json
from src.templates.models import TemplateRecord

TEMPLATES_DIR = ROOT / "templates"
REGISTRY_PATH = TEMPLATES_DIR / "template_registry.json"

LEGACY_FOLDER_TO_TEMPLATE = {
    "ritual_reel": "cinematic_multi_clip_reel",
    "page_turn_loop": "single_clip_atmospheric_loop",
}

TEMPLATE_TO_LEGACY_FOLDER = {v: k for k, v in LEGACY_FOLDER_TO_TEMPLATE.items()}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_registry(path: Path | None = None) -> dict[str, Any]:
    target = path or REGISTRY_PATH
    data = load_json(target, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("templates"), list):
        raise FileNotFoundError(f"Template registry missing or invalid: {target}")
    return data


def list_templates(
    *,
    category: str | None = None,
    status: str | None = None,
    platform: str | None = None,
    path: Path | None = None,
) -> list[TemplateRecord]:
    data = load_registry(path)
    out: list[TemplateRecord] = []
    for raw in data.get("templates") or []:
        if not isinstance(raw, dict):
            continue
        rec = TemplateRecord.model_validate(raw)
        if category and rec.category != category:
            continue
        if status and rec.renderer_status != status:
            continue
        if platform:
            platforms = [p.lower() for p in rec.supported_platforms]
            if platform.lower() not in platforms and "all" not in platforms:
                continue
        out.append(rec)
    return out


def get_template(template_id: str, path: Path | None = None) -> TemplateRecord | None:
    for rec in list_templates(path=path):
        if rec.template_id == template_id:
            return rec
    return None


def templates_by_id(path: Path | None = None) -> dict[str, TemplateRecord]:
    return {t.template_id: t for t in list_templates(path=path)}


def save_registry(data: dict[str, Any], path: Path | None = None) -> Path:
    target = path or REGISTRY_PATH
    data = dict(data)
    data["updated_at"] = _now()
    return atomic_write_json(target, data)


def upsert_template(record: dict[str, Any], path: Path | None = None) -> TemplateRecord:
    data = load_registry(path)
    templates = list(data.get("templates") or [])
    tid = str(record["template_id"])
    record = dict(record)
    record.setdefault("created_at", _now())
    record["updated_at"] = _now()
    replaced = False
    for index, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("template_id") == tid:
            merged = dict(existing)
            merged.update(record)
            templates[index] = merged
            replaced = True
            break
    if not replaced:
        templates.append(record)
    data["templates"] = templates
    save_registry(data, path)
    return TemplateRecord.model_validate(
        next(t for t in templates if t.get("template_id") == tid)
    )


def display_name_for(template_id: str) -> str:
    rec = get_template(template_id)
    return rec.display_name if rec else template_id.replace("_", " ").title()


def legacy_folder_for_template(template_id: str) -> str | None:
    return TEMPLATE_TO_LEGACY_FOLDER.get(template_id)


def template_id_for_legacy_folder(folder_name: str) -> str | None:
    return LEGACY_FOLDER_TO_TEMPLATE.get(folder_name)
