"""Loaders for the brand's illustration canon, product truth and templates.

These are *text* specifications tracked in the repository. Reference imagery
lives in the private vault. Nothing here is coupled to
``src.brand.BRAND_BRAIN_FILES``, so the existing Brand Brain loader keeps its
current required-file contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.common import BRANDS_DIR, DEFAULT_BRAND_ID, BettyOSError
from src.persistence import load_json
from illustration.models import (
    CHARACTER_IDS,
    CharacterAnchor,
    ProductTruth,
)

STYLE_FILE = "illustration_style.md"
CANON_FILE = "illustration_canon.json"
PRODUCTS_FILE = "illustration_products.json"
TEMPLATES_FILE = "illustration_templates.json"


def _brand_dir(brand_id: str) -> Path:
    path = BRANDS_DIR / brand_id
    if not path.is_dir():
        raise BettyOSError(
            f"Brand not found: brands/{brand_id}/",
            hint="Expected a brand directory with illustration_*.json files.",
        )
    return path


@dataclass
class CompositionTemplate:
    template_id: str
    display_name: str
    canvas: str = "shopify_pdp_square"
    is_default: bool = False
    character_ids: list[str] = field(default_factory=list)
    product_id: str | None = None
    product_verification_policy: str = "require_mockup_or_flag"
    mood: str = ""
    palette: list[str] = field(default_factory=list)
    composition_zones: list[str] = field(default_factory=list)
    prompt_blocks: list[str] = field(default_factory=list)
    prohibited_substitutions: list[str] = field(default_factory=list)
    reference_notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompositionTemplate:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def style_notes(brand_id: str = DEFAULT_BRAND_ID) -> str:
    path = _brand_dir(brand_id) / STYLE_FILE
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=8)
def _canon_raw(brand_id: str) -> dict:
    data = load_json(_brand_dir(brand_id) / CANON_FILE, default={})
    return data if isinstance(data, dict) else {}


def shared_features(brand_id: str = DEFAULT_BRAND_ID) -> list[str]:
    return list(_canon_raw(brand_id).get("shared_features") or [])


def group_rules(brand_id: str = DEFAULT_BRAND_ID) -> list[str]:
    return list(_canon_raw(brand_id).get("group_rules") or [])


def character_anchors(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, CharacterAnchor]:
    """The five conceptual roles, keyed by character_id."""
    anchors: dict[str, CharacterAnchor] = {}
    shared = shared_features(brand_id)
    for entry in _canon_raw(brand_id).get("characters") or []:
        if not isinstance(entry, dict):
            continue
        anchor = CharacterAnchor.from_dict(entry)
        if not anchor.shared_features:
            anchor.shared_features = list(shared)
        anchors[anchor.character_id] = anchor
    return anchors


def character(character_id: str, brand_id: str = DEFAULT_BRAND_ID) -> CharacterAnchor:
    anchors = character_anchors(brand_id)
    if character_id not in anchors:
        raise BettyOSError(
            f"Unknown character role: {character_id}",
            hint=f"Known roles: {', '.join(CHARACTER_IDS)}",
        )
    return anchors[character_id]


def all_characters(brand_id: str = DEFAULT_BRAND_ID) -> list[CharacterAnchor]:
    anchors = character_anchors(brand_id)
    ordered = [anchors[cid] for cid in CHARACTER_IDS if cid in anchors]
    extras = [a for cid, a in anchors.items() if cid not in CHARACTER_IDS]
    return ordered + extras


@lru_cache(maxsize=8)
def _products_raw(brand_id: str) -> dict:
    data = load_json(_brand_dir(brand_id) / PRODUCTS_FILE, default={})
    return data if isinstance(data, dict) else {}


def products(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, ProductTruth]:
    result: dict[str, ProductTruth] = {}
    for entry in _products_raw(brand_id).get("products") or []:
        if isinstance(entry, dict):
            truth = ProductTruth.from_dict(entry)
            result[truth.product_id] = truth
    return result


def product(product_id: str, brand_id: str = DEFAULT_BRAND_ID) -> ProductTruth:
    found = products(brand_id).get(product_id)
    if found is None:
        raise BettyOSError(
            f"Unknown product: {product_id}",
            hint=f"Add it to brands/{brand_id}/{PRODUCTS_FILE}.",
        )
    return found


@lru_cache(maxsize=8)
def _templates_raw(brand_id: str) -> dict:
    data = load_json(_brand_dir(brand_id) / TEMPLATES_FILE, default={})
    return data if isinstance(data, dict) else {}


def templates(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, CompositionTemplate]:
    result: dict[str, CompositionTemplate] = {}
    for entry in _templates_raw(brand_id).get("templates") or []:
        if isinstance(entry, dict):
            tpl = CompositionTemplate.from_dict(entry)
            result[tpl.template_id] = tpl
    return result


def template(template_id: str, brand_id: str = DEFAULT_BRAND_ID) -> CompositionTemplate:
    found = templates(brand_id).get(template_id)
    if found is None:
        raise BettyOSError(
            f"Unknown template: {template_id}",
            hint=f"Add it to brands/{brand_id}/{TEMPLATES_FILE}.",
        )
    return found


def default_template(brand_id: str = DEFAULT_BRAND_ID) -> CompositionTemplate:
    all_templates = templates(brand_id)
    for tpl in all_templates.values():
        if tpl.is_default:
            return tpl
    if not all_templates:
        raise BettyOSError(
            f"No illustration templates defined for {brand_id}.",
            hint=f"Add brands/{brand_id}/{TEMPLATES_FILE}.",
        )
    return next(iter(all_templates.values()))


def reset_cache() -> None:
    """Drop cached canon after an on-disk edit."""
    _canon_raw.cache_clear()
    _products_raw.cache_clear()
    _templates_raw.cache_clear()
