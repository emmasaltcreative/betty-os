"""Orchestration for the Illustration Studio.

Order of operations (brief §6):

    gather references → draft scene → position/verify product geometry
    → place locked logo and label layers → QA preview → approval → export

The deterministic truth layer is applied *after* the generated scene, and
re-applied after any grading or crop, so a later step can never damage a
verified mark.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from src.common import DEFAULT_BRAND_ID
from src.data_dir import illustration_dir, relative_to_data_root
from src.persistence import atomic_write_json
from illustration import canon, compositor, prompt_builder, qa, vault, versions
from illustration.compositor import LabelGeometry
from illustration.models import (
    GenerationVersion,
    IllustrationBrief,
    LayerManifest,
    ProductTruth,
    ReferenceSelection,
    utc_now_iso,
)
from illustration.provider import (
    CostEstimate,
    ImageProvider,
    ImageRequest,
    ProviderError,
    ProviderUnavailable,
    get_provider,
)


class ServiceError(Exception):
    """Illustration workflow failed."""


@dataclass
class DraftPlan:
    """What a Generate click would do, shown before anything is spent."""

    brief: IllustrationBrief
    generation: prompt_builder.GenerationBrief
    provider_name: str
    provider_configured: bool
    unavailable_reason: str = ""
    cost: CostEstimate = field(default_factory=CostEstimate)

    @property
    def can_generate(self) -> bool:
        return self.provider_configured and not self.generation.is_blocked

    def blockers(self) -> list[str]:
        reasons: list[str] = []
        if not self.provider_configured:
            reasons.append(self.unavailable_reason or "No image provider configured.")
        reasons.extend(
            c.detail for c in self.generation.conflicts if c.severity == "blocking"
        )
        return reasons


# --- brief assembly -------------------------------------------------------------


def build_brief(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    template_id: str | None = None,
    scene_text: str = "",
    character_ids: list[str] | None = None,
    product_id: str | None = None,
    canvas: str | None = None,
    references: list[ReferenceSelection] | None = None,
    variations: int = 1,
    style_notes: str = "",
) -> IllustrationBrief:
    """Assemble a brief, auto-selecting saved references so nothing is re-uploaded."""
    template = (
        canon.template(template_id, brand_id)
        if template_id
        else canon.default_template(brand_id)
    )
    brief = IllustrationBrief(
        brief_id=f"brf_{uuid4().hex[:10]}",
        brand_id=brand_id,
        template_id=template.template_id,
        scene_text=scene_text or " ".join(template.prompt_blocks),
        character_ids=list(
            character_ids if character_ids is not None else template.character_ids
        ),
        product_id=product_id if product_id is not None else template.product_id,
        canvas=canvas or template.canvas,
        variations=max(1, min(4, int(variations))),
        style_notes=style_notes,
        prohibitions=list(template.prohibited_substitutions),
    )
    brief.references = (
        list(references)
        if references is not None
        else prompt_builder.auto_references(brief, brand_id=brand_id)
    )
    return brief


def plan_draft(
    brief: IllustrationBrief,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    provider: ImageProvider | None = None,
    enforce_privacy_opt_in: bool = True,
) -> DraftPlan:
    """Human-readable brief, blockers and a cost estimate, before any spend."""
    generation = prompt_builder.build(
        brief, brand_id=brand_id, enforce_privacy_opt_in=enforce_privacy_opt_in
    )
    engine = provider or get_provider()
    width, height = brief.canvas_size()
    request = ImageRequest(
        prompt=generation.prompt,
        negative_prompt=generation.negative_prompt,
        width=width,
        height=height,
        n=brief.variations,
    )
    return DraftPlan(
        brief=brief,
        generation=generation,
        provider_name=engine.name,
        provider_configured=engine.is_configured(),
        unavailable_reason=getattr(engine, "unavailable_reason", lambda: "")(),
        cost=engine.estimate_cost(request),
    )


# --- generation -----------------------------------------------------------------


def _reference_paths(
    brief: IllustrationBrief, brand_id: str, *, require_opt_in: bool = True
) -> list[Path]:
    """Only assets cleared for third-party use are ever sent off the machine."""
    paths: list[Path] = []
    for ref in brief.references:
        asset = vault.get_asset(ref.asset_id, brand_id)
        if asset is None or ref.role == "mark_source":
            # Marks are composited locally; they never need to go to the model.
            continue
        if asset.is_private and require_opt_in and not asset.third_party_api_opt_in:
            continue
        path = vault.asset_path(asset)
        if path.is_file():
            paths.append(path)
    return paths


def generate_draft(
    brief: IllustrationBrief,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    provider: ImageProvider | None = None,
    apply_truth_layer: bool = True,
    enforce_privacy_opt_in: bool = True,
) -> list[GenerationVersion]:
    """Generate one or more drafts and persist them as immutable versions."""
    plan = plan_draft(
        brief,
        brand_id=brand_id,
        provider=provider,
        enforce_privacy_opt_in=enforce_privacy_opt_in,
    )
    if not plan.can_generate:
        raise ProviderUnavailable("; ".join(plan.blockers()))

    engine = provider or get_provider()
    width, height = brief.canvas_size()
    request = ImageRequest(
        prompt=plan.generation.prompt,
        negative_prompt=plan.generation.negative_prompt,
        width=width,
        height=height,
        n=brief.variations,
        reference_paths=_reference_paths(
            brief, brand_id, require_opt_in=enforce_privacy_opt_in
        ),
    )

    try:
        result = engine.generate(request)
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(f"Image generation failed: {exc}") from exc

    created: list[GenerationVersion] = []
    for index, payload in enumerate(result.images):
        version_id = versions.next_version_id(brand_id)
        stored = versions.save_bytes(
            version_id, f"{version_id}_draft_{index + 1}.png", payload, brand_id
        )
        with Image.open(io.BytesIO(payload)) as img:
            source_size = img.size

        version = GenerationVersion(
            version_id=version_id,
            brand_id=brand_id,
            brief=brief,
            status="draft",
            provider=result.provider,
            model=result.model,
            model_params=dict(result.params),
            source_image_path=stored,
            source_width=source_size[0],
            source_height=source_size[1],
        )
        version = versions.append_version(version, brand_id)
        if apply_truth_layer:
            version = apply_truth_layer_to(version.version_id, brand_id=brand_id)
        else:
            version = run_qa(version.version_id, brand_id=brand_id)
        created.append(version)
    return created


# --- deterministic truth layer ---------------------------------------------------


def _mark_images(
    brief: IllustrationBrief, brand_id: str
) -> tuple[Image.Image | None, Image.Image | None, list[str]]:
    """Load the locked quatrefoil and signature from their source files."""
    notes: list[str] = []
    mark = signature = None
    for ref in brief.references:
        if ref.role != "mark_source":
            continue
        asset = vault.get_asset(ref.asset_id, brand_id)
        if asset is None:
            continue
        path = vault.asset_path(asset)
        tags = {t.lower() for t in asset.tags} | {asset.display_name.lower()}
        try:
            if any("signature" in t for t in tags) and signature is None:
                signature = compositor.load_mark(path, target_width=900)
            elif mark is None:
                mark = compositor.load_mark(path, target_width=512)
        except compositor.CompositorError as exc:
            notes.append(str(exc))
    return mark, signature, notes


def apply_truth_layer_to(
    version_id: str,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    bottle_box: tuple[int, int, int, int] | None = None,
    use_schematic: bool = True,
) -> GenerationVersion:
    """Composite exact label and mark artwork over a generated draft."""
    version = versions.require_version(version_id, brand_id)
    source = versions.resolve(version.source_image_path)
    if source is None or not source.is_file():
        raise ServiceError(f"{version_id} has no stored draft image to composite onto.")

    product: ProductTruth | None = (
        canon.product(version.brief.product_id, brand_id)
        if version.brief.product_id
        else None
    )
    manifest = LayerManifest()
    base = Image.open(source).convert("RGBA")
    notes: list[str] = []

    if product is not None:
        mark, signature, load_notes = _mark_images(version.brief, brand_id)
        notes.extend(load_notes)
        if mark is None and signature is None:
            notes.append(
                "No locked mark artwork is attached, so no label was composited. "
                "Add the official SVGs to the vault and re-apply."
            )
        else:
            height = max(240, int(base.height * 0.18))
            geometry = LabelGeometry(
                width=int(height * 1.73),
                height=height,
                ghost_tile_px=max(12, int(height * product.label.ghost_tile_ratio)),
                margin_px=max(8, int(height * 0.06)),
            )
            label = compositor.build_label(
                product, geometry, mark=mark, signature=signature, manifest=manifest
            )
            if bottle_box is None and use_schematic:
                # No verified mockup: preview the label on a schematic cylinder
                # composited into the scene. Never a product-accurate claim.
                bottle, box = compositor.render_bottle_schematic(
                    product,
                    size=(int(base.width * 0.22), int(base.height * 0.55)),
                    manifest=manifest,
                )
                bottle = compositor.place_label_lengthwise(
                    bottle, label, bottle_box=box, manifest=manifest
                )
                base.alpha_composite(
                    bottle,
                    (
                        int(base.width * 0.60),
                        int(base.height * 0.38),
                    ),
                )
                notes.append(
                    "Bottle rendered as a deterministic schematic because no "
                    "verified current mockup is attached. Treat it as a label "
                    "geometry preview, not product photography."
                )
            elif bottle_box is not None:
                base = compositor.place_label_lengthwise(
                    base, label, bottle_box=bottle_box, manifest=manifest
                )

    out_dir = versions.version_dir(version_id, brand_id)
    composited = out_dir / f"{version_id}_composited.png"
    base.convert("RGBA").save(composited, "PNG")

    version = versions.update_version(
        version_id,
        brand_id,
        composited_path=relative_to_data_root(composited),
        layer_manifest=manifest.to_dict(),
        notes="\n".join(notes),
    )
    return run_qa(version_id, brand_id=brand_id)


# --- QA and status ---------------------------------------------------------------


def run_qa(version_id: str, *, brand_id: str = DEFAULT_BRAND_ID) -> GenerationVersion:
    version = versions.require_version(version_id, brand_id)
    product = (
        canon.product(version.brief.product_id, brand_id)
        if version.brief.product_id
        else None
    )
    image_paths: dict[str, Path] = {}
    for kind, stored in version.export_paths.items():
        path = versions.resolve(stored)
        if path:
            image_paths[kind] = path
    if not image_paths:
        candidate = versions.resolve(version.composited_path or version.source_image_path)
        if candidate:
            image_paths["working"] = candidate

    report = qa.preflight(
        version, brand_id=brand_id, product=product, image_paths=image_paths
    )
    checklist = version.human_checklist or qa.human_checklist(version, product=product)
    status = version.status
    if status in {"draft", "needs_accuracy_review"}:
        status = qa.gate_status(report, status)
    return versions.update_version(
        version_id,
        brand_id,
        qa_results=report.to_list(),
        human_checklist=checklist,
        status=status,
        accuracy_status=(
            product.accuracy_status if product else version.accuracy_status
        ),
    )


# --- revision --------------------------------------------------------------------


def revise(
    version_id: str,
    instruction: str,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    region: str | None = None,
    mask_path: Path | None = None,
    provider: ImageProvider | None = None,
    reapply_truth_layer: bool = True,
) -> GenerationVersion:
    """Targeted revision. Always a NEW version; the parent is never overwritten."""
    parent = versions.require_version(version_id, brand_id)
    source = versions.resolve(parent.composited_path or parent.source_image_path)
    if source is None or not source.is_file():
        raise ServiceError(f"{version_id} has no stored image to revise.")

    engine = provider or get_provider()
    if not engine.is_configured():
        raise ProviderUnavailable(
            getattr(engine, "unavailable_reason", lambda: "")()
            or "No image provider configured."
        )
    if mask_path is not None and not engine.supports_mask():
        raise ProviderUnavailable(
            f"The {engine.name} adapter does not support mask editing."
        )

    generation = prompt_builder.build(parent.brief, brand_id=brand_id)
    scope = f" Change only the {region}." if region else ""
    prompt = (
        f"{generation.prompt}\n\n"
        f"REVISION — {instruction.strip()}{scope} Preserve everything else in the "
        "image exactly: the same faces and identities, the same composition, "
        "palette and lighting. Do not restyle or re-render untouched areas."
    )

    width, height = parent.brief.canvas_size()
    request = ImageRequest(
        prompt=prompt,
        negative_prompt=generation.negative_prompt,
        width=width,
        height=height,
        n=1,
        source_path=source,
        mask_path=mask_path,
    )
    result = engine.generate(request)
    if not result.images:
        raise ServiceError("The provider returned no revised image.")

    child_id = versions.next_version_id(brand_id)
    stored = versions.save_bytes(
        child_id, f"{child_id}_revision.png", result.images[0], brand_id
    )
    with Image.open(io.BytesIO(result.images[0])) as img:
        source_size = img.size

    child = GenerationVersion(
        version_id=child_id,
        brand_id=brand_id,
        brief=parent.brief,
        status="draft",
        provider=result.provider,
        model=result.model,
        model_params=dict(result.params),
        source_image_path=stored,
        source_width=source_size[0],
        source_height=source_size[1],
        parent_version_id=parent.version_id,
        revision_instruction=instruction.strip(),
        masked_region=region,
    )
    versions.append_version(child, brand_id)
    # A generative edit can disturb neighbouring pixels, so locked layers are
    # re-applied afterwards rather than trusted to survive.
    if reapply_truth_layer:
        return apply_truth_layer_to(child_id, brand_id=brand_id)
    return run_qa(child_id, brand_id=brand_id)


def deterministic_overlay_revision(
    version_id: str,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    note: str = "",
) -> GenerationVersion:
    """Re-apply exact artwork locally — no model call, no neighbouring drift.

    This is the honest answer when the requested change is a logo or wording.
    """
    parent = versions.require_version(version_id, brand_id)
    child_id = versions.next_version_id(brand_id)
    source = versions.resolve(parent.source_image_path)
    if source is None or not source.is_file():
        raise ServiceError(f"{version_id} has no stored draft image.")
    stored = versions.save_bytes(
        child_id, f"{child_id}_source.png", source.read_bytes(), brand_id
    )
    child = GenerationVersion(
        version_id=child_id,
        brand_id=brand_id,
        brief=parent.brief,
        status="draft",
        provider="deterministic",
        model="compositor",
        source_image_path=stored,
        source_width=parent.source_width,
        source_height=parent.source_height,
        parent_version_id=parent.version_id,
        revision_instruction=note or "Re-applied exact brand artwork locally.",
    )
    versions.append_version(child, brand_id)
    return apply_truth_layer_to(child_id, brand_id=brand_id)


# --- export ----------------------------------------------------------------------


def _slug(text: str) -> str:
    cleaned = "".join(
        ch.lower() if ch.isalnum() else "_" for ch in (text or "").strip()
    )
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "untitled"


def export_basename(version: GenerationVersion) -> str:
    """``OBJ_<product_slug>_<character_or_scene>_<size>_vNNN``."""
    product = _slug(version.brief.product_id or "no_product")
    if len(version.brief.character_ids) == 1:
        scene = _slug(version.brief.character_ids[0])
    elif version.brief.character_ids:
        scene = _slug(version.brief.template_id)
    else:
        scene = _slug(version.brief.template_id)
    width, _ = version.brief.canvas_size()
    number = version.version_id.rsplit("_v", 1)[-1]
    number = number if number.isdigit() else "001"
    return f"OBJ_{product}_{scene}_{width}_v{number}"


def export_version(
    version_id: str,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    canvas: str | None = None,
    include_webp: bool = False,
    fit_mode: str = "contain",
) -> GenerationVersion:
    """Render real JPG and PNG at the exact canvas size and record them."""
    version = versions.require_version(version_id, brand_id)
    source = versions.resolve(version.composited_path or version.source_image_path)
    if source is None or not source.is_file():
        raise ServiceError(f"{version_id} has no image to export.")

    target_canvas = canvas or version.brief.canvas
    manifest = version.layer_manifest
    with Image.open(source) as img:
        img.load()
        fitted = compositor.fit_to_canvas(img, target_canvas, mode=fit_mode)

    out_dir = versions.version_dir(version_id, brand_id) / "exports"
    written = compositor.export(
        fitted,
        out_dir,
        export_basename(version),
        canvas=target_canvas,
        include_webp=include_webp,
        manifest=manifest,
    )
    export_paths = dict(version.export_paths)
    export_paths.update({k: relative_to_data_root(v) for k, v in written.items()})

    versions.update_version(
        version_id,
        brand_id,
        export_paths=export_paths,
        layer_manifest=manifest.to_dict(),
        status="exported"
        if version.status == "approved_for_editorial_use"
        else version.status,
    )
    return run_qa(version_id, brand_id=brand_id)


def export_bundle(
    version_ids: list[str],
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    bundle_name: str = "illustration_handoff",
) -> Path:
    """ZIP of approved outputs plus a manifest describing the real files."""
    manifest = versions.export_manifest(version_ids, brand_id)
    out_dir = illustration_dir(brand_id) / "_bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"{bundle_name}_{utc_now_iso().replace(':', '').replace('-', '')}.zip"

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for version_id in version_ids:
            version = versions.require_version(version_id, brand_id)
            for stored in version.export_paths.values():
                path = versions.resolve(stored)
                if path and path.is_file():
                    zf.write(path, arcname=f"{version_id}/{path.name}")
        import json

        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    atomic_write_json(out_dir / "last_manifest.json", manifest)
    return bundle


# --- reuse -----------------------------------------------------------------------


def promote_to_vault(
    version_id: str,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    category: str = "finished_works",
    roles: list[str] | None = None,
    display_name: str = "",
    state: str = "approved",
    character_ids: list[str] | None = None,
) -> Any:
    """``Save as Style Reference`` / ``Save Betty Character Reference``."""
    version = versions.require_version(version_id, brand_id)
    source = versions.resolve(version.composited_path or version.source_image_path)
    if source is None or not source.is_file():
        raise ServiceError(f"{version_id} has no image to promote.")
    return vault.import_asset(
        source,
        brand_id=brand_id,
        category=category,
        display_name=display_name or f"{version.brief.template_id} {version.version_id}",
        roles=list(roles or ["style_only"]),
        state=state,
        character_ids=list(character_ids or version.brief.character_ids),
        product_ids=[version.brief.product_id] if version.brief.product_id else [],
        tags=["from_illustration_studio", version.version_id],
        dedupe=False,
    )
