"""Typed records for the Illustration Studio.

Dataclasses with ``to_dict``/``from_dict`` mirror ``studio.models`` so the
persistence idiom (``src.persistence.atomic_write_json``) stays uniform.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from studio.models import utc_now_iso  # re-exported for callers

__all__ = [
    "utc_now_iso",
    "VAULT_CATEGORIES",
    "REFERENCE_ROLES",
    "VERIFICATION_STATES",
    "CHARACTER_IDS",
    "CHARACTER_LABELS",
    "ILLUSTRATION_STATUSES",
    "ACCURACY_STATUSES",
    "REFERENCE_PRECEDENCE",
    "CANVAS_PRESETS",
    "VaultAsset",
    "CharacterAnchor",
    "LabelSpec",
    "ProductTruth",
    "ReferenceSelection",
    "IllustrationBrief",
    "LayerManifest",
    "GenerationVersion",
]


# --- Vault taxonomy (brief §4) -------------------------------------------------

VAULT_CATEGORIES: tuple[str, ...] = (
    "official_marks",      # 1. exact locked SVG/print art — never model-generated
    "character_masters",   # 2. lineage board, portraits, face anchors
    "style_anchors",       # 3. approved editorial boards
    "product_truth",       # 4. real product/packaging photos, mockups, label art
    "botanical",           # 5. Iris pallida, rose, jasmine, pear
    "scene_elements",      # 6. note paper, books, jade velvet, scarf tile
    "templates",           # 7. saved composition recipes
    "finished_works",      # 8. drafts, approved, rejected, lineage
)

# What an image is allowed to prove. A style board must not define product facts.
REFERENCE_ROLES: tuple[str, ...] = (
    "style_only",
    "composition_reference",
    "character_reference",
    "product_reference",
    "mark_source",
)

VERIFICATION_STATES: tuple[str, ...] = (
    "locked",      # exact source art; use byte-for-byte
    "approved",
    "draft",
    "rejected",
    "unverified",  # present but not confirmed against the physical product
)

# Conceptual roles, not literal portraits (brief §3).
CHARACTER_IDS: tuple[str, ...] = (
    "young_betty",
    "present_betty",
    "timeless_betty",
    "golden_betty",
    "betty_remembered",
)

CHARACTER_LABELS: dict[str, str] = {
    "young_betty": "Young Betty",
    "present_betty": "Present Betty",
    "timeless_betty": "Timeless Betty",
    "golden_betty": "Golden Betty",
    "betty_remembered": "Betty Remembered",
}

# Status ladder (brief §10). Accuracy is tracked separately from editorial use.
ILLUSTRATION_STATUSES: tuple[str, ...] = (
    "draft",
    "needs_accuracy_review",
    "approved_for_editorial_use",
    "exported",
    "rejected",
)

ACCURACY_STATUSES: tuple[str, ...] = (
    "requires_product_verification",
    "product_accurate_verified",
)

# Precedence (brief §4). Lower index wins when sources disagree.
REFERENCE_PRECEDENCE: tuple[str, ...] = (
    "official_exact_file",     # locked SVG / print file
    "verified_product_spec",   # verified mockup or spec
    "approved_character_anchor",
    "approved_style_anchor",
    "user_scene_instruction",
    "generic_invention",       # never authoritative
)

CANVAS_PRESETS: dict[str, tuple[int, int]] = {
    "shopify_pdp_square": (2048, 2048),
    "pdp_portrait": (1638, 2048),       # 4:5
    "pinterest_pin": (1365, 2048),      # 2:3
    "instagram_feed": (1638, 2048),     # 4:5
    "editorial_wide": (2048, 1152),     # 16:9
}


# --- Records -------------------------------------------------------------------


def _from_dict(cls, data: dict[str, Any]):
    known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class VaultAsset:
    """A durable, reusable reference. Uploaded once, selectable forever."""

    asset_id: str
    brand_id: str
    category: str
    display_name: str
    file_path: str                 # relative to the private data root
    sha256: str
    mime_type: str
    original_filename: str = ""
    roles: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    has_alpha: bool = False
    tags: list[str] = field(default_factory=list)
    product_ids: list[str] = field(default_factory=list)
    character_ids: list[str] = field(default_factory=list)
    botanical_names: list[str] = field(default_factory=list)
    usage_scope: str = "internal"
    reference_priority: int = 50   # lower sorts first within a category
    state: str = "draft"
    version: int = 1
    parent_id: str | None = None
    thumbnail_path: str | None = None
    license_note: str = ""
    is_private: bool = True        # family photo / proprietary master
    third_party_api_opt_in: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    archived: bool = False

    @property
    def is_locked(self) -> bool:
        return self.state == "locked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultAsset:
        return _from_dict(cls, data)


@dataclass
class CharacterAnchor:
    """Face anchor / character sheet for one of the five conceptual roles."""

    character_id: str
    display_name: str
    inspiration: str               # e.g. "living paternal grandmother"
    description: str
    shared_features: list[str] = field(default_factory=list)
    distinct_features: list[str] = field(default_factory=list)
    wardrobe_notes: str = ""
    signature_props: list[str] = field(default_factory=list)
    prohibited: list[str] = field(default_factory=list)
    anchor_asset_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterAnchor:
        return _from_dict(cls, data)


@dataclass
class LabelSpec:
    """The real printed label. Composited, never generated (brief §5)."""

    transparent: bool = True
    ghost_motif_opacity: float = 0.5
    # Colour of the ghosted repeat behind the text. Defaults to the house gold
    # so the motif never inherits whatever colour the source file happens to be.
    ghost_motif_color: str = "#C9A227"
    ghost_tile_ratio: float = 0.17   # tile edge as a fraction of label height
    title_color: str = "#FFFFFF"
    subtitle_color: str = "#FFFFFF"
    mark_color: str = "#C9A227"      # gold
    signature_color: str = "#C9A227"
    signature_below_edp: bool = True
    copy_orientation: str = "lengthwise"   # along the cylinder's long axis
    title_text: str = "A Woman Remembered"
    subtitle_lines: list[str] = field(default_factory=lambda: ["EAU DE PARFUM", "10 mL"])
    notes_line: str | None = None    # None => approved label has none; never invent
    label_art_asset_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LabelSpec:
        return _from_dict(cls, data)


@dataclass
class ProductTruth:
    """Physical product facts. Illustrations must not contradict these."""

    product_id: str
    display_name: str
    size: str = ""
    form_factor: str = ""
    glass_color: str = ""
    hardware_finish: str = ""
    hardware_both_ends: bool = False
    mechanisms: list[str] = field(default_factory=list)
    label: LabelSpec = field(default_factory=LabelSpec)
    botanicals: list[str] = field(default_factory=list)
    prohibited_substitutions: list[str] = field(default_factory=list)
    immutable_facts: list[str] = field(default_factory=list)
    mockup_asset_ids: list[str] = field(default_factory=list)
    spec_verified: bool = False
    unverified_fields: list[str] = field(default_factory=list)

    @property
    def accuracy_status(self) -> str:
        return (
            "product_accurate_verified"
            if self.spec_verified and self.mockup_asset_ids
            else "requires_product_verification"
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["label"] = self.label.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductTruth:
        payload = dict(data)
        label = payload.get("label")
        payload["label"] = (
            LabelSpec.from_dict(label) if isinstance(label, dict) else LabelSpec()
        )
        return _from_dict(cls, payload)


@dataclass
class ReferenceSelection:
    """One reference handed to the provider, with what it is allowed to prove."""

    asset_id: str
    role: str
    precedence: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferenceSelection:
        return _from_dict(cls, data)


@dataclass
class IllustrationBrief:
    """Everything that defines one generation request."""

    brief_id: str
    brand_id: str
    template_id: str
    scene_text: str
    character_ids: list[str] = field(default_factory=list)
    product_id: str | None = None
    canvas: str = "shopify_pdp_square"
    references: list[ReferenceSelection] = field(default_factory=list)
    prohibitions: list[str] = field(default_factory=list)
    style_notes: str = ""
    safe_area_percent: float = 9.0
    variations: int = 1
    created_at: str = field(default_factory=utc_now_iso)

    def canvas_size(self) -> tuple[int, int]:
        return CANVAS_PRESETS.get(self.canvas, CANVAS_PRESETS["shopify_pdp_square"])

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["references"] = [r.to_dict() for r in self.references]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IllustrationBrief:
        payload = dict(data)
        refs = payload.get("references") or []
        payload["references"] = [
            ReferenceSelection.from_dict(r) for r in refs if isinstance(r, dict)
        ]
        return _from_dict(cls, payload)


@dataclass
class LayerManifest:
    """What the deterministic compositor actually placed, for QA to assert on."""

    layers: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, **meta: Any) -> None:
        entry = {"name": name}
        entry.update(meta)
        self.layers.append(entry)

    def names(self) -> list[str]:
        return [str(layer.get("name")) for layer in self.layers]

    def find(self, name: str) -> dict[str, Any] | None:
        for layer in self.layers:
            if layer.get("name") == name:
                return layer
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"layers": list(self.layers)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayerManifest:
        layers = data.get("layers") if isinstance(data, dict) else None
        return cls(layers=[l for l in (layers or []) if isinstance(l, dict)])


@dataclass
class GenerationVersion:
    """Immutable record of one draft or revision. Parents are never overwritten."""

    version_id: str
    brand_id: str
    brief: IllustrationBrief
    status: str = "draft"
    accuracy_status: str = "requires_product_verification"
    provider: str = ""
    model: str = ""
    model_params: dict[str, Any] = field(default_factory=dict)
    source_image_path: str | None = None     # raw provider output
    composited_path: str | None = None       # after the truth layer
    export_paths: dict[str, str] = field(default_factory=dict)
    layer_manifest: LayerManifest = field(default_factory=LayerManifest)
    qa_results: list[dict[str, Any]] = field(default_factory=list)
    human_checklist: list[dict[str, Any]] = field(default_factory=list)
    parent_version_id: str | None = None
    revision_instruction: str = ""
    masked_region: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    notes: str = ""
    error: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["brief"] = self.brief.to_dict()
        data["layer_manifest"] = self.layer_manifest.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationVersion:
        payload = dict(data)
        brief = payload.get("brief")
        payload["brief"] = (
            IllustrationBrief.from_dict(brief)
            if isinstance(brief, dict)
            else IllustrationBrief(
                brief_id="unknown", brand_id=payload.get("brand_id", ""),
                template_id="unknown", scene_text="",
            )
        )
        manifest = payload.get("layer_manifest")
        payload["layer_manifest"] = (
            LayerManifest.from_dict(manifest) if isinstance(manifest, dict) else LayerManifest()
        )
        return _from_dict(cls, payload)
