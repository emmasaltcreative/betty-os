"""QA — visibly separating what is *verified* from what is *artistic*.

Two distinct layers:

``preflight``
    Deterministic, mechanical checks. Files decode, dimensions and aspect are
    exact, alpha is intact, the official mark asset ids actually used are the
    locked ones, the signature really sits below the EDP text, no notes line was
    invented, and the gold end components exist as real render layers.

``human_checklist``
    Everything that requires a person to look. This module deliberately does
    **not** pretend to settle visual semantics — whether five Bettys are
    recognisable, whether a flower is jasmine and not gardenia, or whether the
    art reads as Modern Heirloom Editorial — with pixel statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from src.common import DEFAULT_BRAND_ID
from illustration import vault
from illustration.models import (
    CANVAS_PRESETS,
    CHARACTER_LABELS,
    GenerationVersion,
    LayerManifest,
    ProductTruth,
)

OUTCOMES = ("pass", "warning", "fail", "needs_human")


@dataclass
class Check:
    check_id: str
    label: str
    outcome: str
    detail: str = ""
    deterministic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "label": self.label,
            "outcome": self.outcome,
            "detail": self.detail,
            "deterministic": self.deterministic,
        }


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, *args: Any, **kwargs: Any) -> None:
        self.checks.append(Check(*args, **kwargs))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == "fail"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == "warning"]

    @property
    def needs_human(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == "needs_human"]

    @property
    def passed(self) -> bool:
        return not self.failed

    def to_list(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.checks]


# --- deterministic preflight ----------------------------------------------------


def preflight(
    version: GenerationVersion,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    product: ProductTruth | None = None,
    image_paths: dict[str, Path] | None = None,
) -> PreflightReport:
    report = PreflightReport()
    manifest = version.layer_manifest

    _check_files(report, version, image_paths)
    _check_canvas(report, version, image_paths)
    _check_marks_are_locked(report, version, manifest, brand_id)
    _check_label_geometry(report, manifest, product)
    _check_hardware_layers(report, manifest, product)
    _check_references(report, version)
    _check_accuracy_claim(report, version, product)
    return report


def _check_files(
    report: PreflightReport,
    version: GenerationVersion,
    image_paths: dict[str, Path] | None,
) -> None:
    paths = image_paths or {}
    if not paths:
        report.add(
            "files_present",
            "Export files exist",
            "warning",
            "No exported files to check yet.",
        )
        return
    for kind, path in paths.items():
        path = Path(path)
        if not path.is_file():
            report.add(
                f"file_{kind}",
                f"{kind.upper()} file exists",
                "fail",
                f"The UI reported {path.name} but no such file is on disk.",
            )
            continue
        try:
            with Image.open(path) as img:
                img.load()
                size, mode = img.size, img.mode
        except Exception as exc:  # noqa: BLE001
            report.add(
                f"file_{kind}",
                f"{kind.upper()} decodes",
                "fail",
                f"{path.name} could not be decoded: {exc}",
            )
            continue
        report.add(
            f"file_{kind}",
            f"{kind.upper()} decodes",
            "pass",
            f"{path.name} — {size[0]}×{size[1]} {mode}, "
            f"{path.stat().st_size // 1024} KB.",
        )


def _check_canvas(
    report: PreflightReport,
    version: GenerationVersion,
    image_paths: dict[str, Path] | None,
) -> None:
    canvas = version.brief.canvas
    expected = CANVAS_PRESETS.get(canvas)
    if expected is None:
        report.add("canvas_known", "Canvas preset known", "fail", f"Unknown canvas {canvas}.")
        return
    for kind, path in (image_paths or {}).items():
        path = Path(path)
        if not path.is_file():
            continue
        try:
            with Image.open(path) as img:
                actual = img.size
                has_alpha = img.mode in {"RGBA", "LA"}
        except Exception:  # noqa: BLE001
            continue
        outcome = "pass" if actual == expected else "fail"
        report.add(
            f"canvas_{kind}",
            f"{kind.upper()} is exactly {expected[0]}×{expected[1]}",
            outcome,
            f"Measured {actual[0]}×{actual[1]}.",
        )
        if has_alpha:
            try:
                with Image.open(path) as img:
                    alpha_min = img.convert("RGBA").getchannel("A").getextrema()[0]
                report.add(
                    f"alpha_{kind}",
                    f"{kind.upper()} transparency intact",
                    "pass" if alpha_min is not None else "warning",
                    f"Minimum alpha {alpha_min}.",
                )
            except Exception as exc:  # noqa: BLE001
                report.add(
                    f"alpha_{kind}",
                    f"{kind.upper()} transparency intact",
                    "warning",
                    str(exc),
                )

    # Upscaling honesty: record, never claim recovered detail.
    if version.source_width and expected:
        if version.source_width < expected[0]:
            report.add(
                "source_resolution",
                "Source resolution recorded",
                "warning",
                f"The provider draft was {version.source_width}×"
                f"{version.source_height}; the export is {expected[0]}×{expected[1]}. "
                "Resampling does not recover detail that was never captured.",
            )
        else:
            report.add(
                "source_resolution",
                "Source resolution recorded",
                "pass",
                f"Draft {version.source_width}×{version.source_height}.",
            )


def _check_marks_are_locked(
    report: PreflightReport,
    version: GenerationVersion,
    manifest: LayerManifest,
    brand_id: str,
) -> None:
    """Official marks must come from locked source files, not the model."""
    mark_layers = [
        name for name in ("house_mark", "house_signature", "ghost_motif_repeat")
        if manifest.find(name) is not None
    ]
    if not mark_layers:
        report.add(
            "marks_composited",
            "Official marks composited from source",
            "warning",
            "No official mark layers were composited onto this version.",
        )
        return

    mark_refs = [r for r in version.brief.references if r.role == "mark_source"]
    if not mark_refs:
        report.add(
            "marks_composited",
            "Official marks composited from source",
            "fail",
            f"Layers {', '.join(mark_layers)} were drawn but no mark_source "
            "asset is attached. A mark must never be model-generated.",
        )
        return

    unlocked: list[str] = []
    for ref in mark_refs:
        asset = vault.get_asset(ref.asset_id, brand_id)
        if asset is None:
            unlocked.append(f"{ref.asset_id} (missing)")
        elif asset.state not in {"locked", "approved"}:
            unlocked.append(f"{asset.display_name} ({asset.state})")
    if unlocked:
        report.add(
            "marks_locked",
            "Mark artwork is locked/approved",
            "fail",
            "Not exact source art: " + "; ".join(unlocked),
        )
    else:
        report.add(
            "marks_locked",
            "Mark artwork is locked/approved",
            "pass",
            "Marks used: " + ", ".join(r.asset_id for r in mark_refs),
        )

    for name in ("house_mark", "house_signature"):
        layer = manifest.find(name)
        if layer and layer.get("aspect_preserved") is not True:
            report.add(
                f"{name}_aspect",
                f"{name.replace('_', ' ').title()} aspect preserved",
                "fail",
                "The mark was scaled without preserving its aspect ratio.",
            )
        elif layer:
            report.add(
                f"{name}_aspect",
                f"{name.replace('_', ' ').title()} aspect preserved",
                "pass",
            )


def _check_label_geometry(
    report: PreflightReport,
    manifest: LayerManifest,
    product: ProductTruth | None,
) -> None:
    base = manifest.find("label_base")
    if base is None:
        return

    # Transparency: amber must show through the negative space.
    if base.get("alpha_in_negative_space") == 0 and base.get("transparent"):
        report.add(
            "label_transparent",
            "Label is transparent (amber shows through)",
            "pass",
            "Alpha is 0 in the label's negative space.",
        )
    else:
        report.add(
            "label_transparent",
            "Label is transparent (amber shows through)",
            "fail",
            "The label base is not fully transparent; the glass would be hidden.",
        )

    ghost = manifest.find("ghost_motif_repeat")
    if ghost is not None:
        opacity = float(ghost.get("opacity") or 0)
        ok = 0.4 <= opacity <= 0.6
        report.add(
            "ghost_alpha",
            "Ghost motif repeat near 50% alpha",
            "pass" if ok else "warning",
            f"Recorded opacity {opacity:.2f} (expected ≈0.50), "
            f"colour {ghost.get('color')}.",
        )

    signature = manifest.find("house_signature")
    subtitles = manifest.find("label_subtitles")
    if signature is not None and subtitles is not None:
        below = bool(signature.get("below_edp"))
        report.add(
            "signature_below_edp",
            "Signature sits below the EAU DE PARFUM / size text",
            "pass" if below else "fail",
            f"Signature y={signature.get('y')}, EDP block ends at "
            f"{subtitles.get('bottom_y')}.",
        )

    notes = manifest.find("label_notes_line")
    if notes is not None:
        approved_has_notes = bool(product and product.label.notes_line)
        drawn = notes.get("text")
        if drawn and not approved_has_notes:
            report.add(
                "notes_line_not_invented",
                "No invented notes line",
                "fail",
                f"A notes line '{drawn}' was drawn but the approved label has none.",
            )
        else:
            report.add(
                "notes_line_not_invented",
                "No invented notes line",
                "pass",
                "No notes line drawn." if not drawn else "Notes line matches the approved label.",
            )

    placement = manifest.find("product_label")
    if placement is not None:
        orientation = placement.get("orientation")
        expected = product.label.copy_orientation if product else "lengthwise"
        report.add(
            "label_orientation",
            "Label copy runs lengthwise along the cylinder",
            "pass" if orientation == expected else "fail",
            f"Recorded orientation '{orientation}' "
            f"(rotated {placement.get('rotated_degrees')}°).",
        )
        if placement.get("geometric_accuracy") == "approximate":
            report.add(
                "label_geometry_confidence",
                "Label geometry confirmed against the real bottle",
                "needs_human",
                "The label was placed with a cylindrical shading approximation, "
                "not anchored to a verified product mockup. Confirm placement "
                "visually before claiming product accuracy.",
                deterministic=False,
            )


def _check_hardware_layers(
    report: PreflightReport,
    manifest: LayerManifest,
    product: ProductTruth | None,
) -> None:
    """Assert both gold end components exist where geometry makes it possible."""
    if product is None or not product.hardware_both_ends:
        return
    top = manifest.find("gold_end_top")
    bottom = manifest.find("gold_end_bottom")
    if top is None and bottom is None:
        report.add(
            "gold_ends",
            "Gold hardware at both ends",
            "needs_human",
            "This render has no deterministic bottle layers, so both gold ends "
            "cannot be asserted mechanically. Confirm visually that both ends "
            "show gold hardware and that neither cap is duplicated or missing.",
            deterministic=False,
        )
        return
    present = [
        name
        for name, layer in (("top", top), ("bottom", bottom))
        if layer is not None and layer.get("present")
    ]
    if len(present) == 2:
        report.add(
            "gold_ends",
            "Gold hardware at both ends",
            "pass",
            f"Both end layers present: {top.get('mechanism')} / "
            f"{bottom.get('mechanism')}.",
        )
    else:
        report.add(
            "gold_ends",
            "Gold hardware at both ends",
            "fail",
            f"Only these end layers were rendered: {', '.join(present) or 'none'}.",
        )


def _check_references(report: PreflightReport, version: GenerationVersion) -> None:
    if version.brief.character_ids:
        has_character_ref = any(
            r.role == "character_reference" for r in version.brief.references
        )
        report.add(
            "character_reference_attached",
            "A character reference is attached",
            "pass" if has_character_ref else "warning",
            "The canon requires a chosen character reference in every "
            "generation or revision."
            if not has_character_ref
            else "",
        )
    missing_fields = [
        name
        for name, value in (
            ("template_id", version.brief.template_id),
            ("canvas", version.brief.canvas),
        )
        if not value
    ]
    report.add(
        "required_fields",
        "Required brief fields present",
        "pass" if not missing_fields else "fail",
        "Missing: " + ", ".join(missing_fields) if missing_fields else "",
    )


def _check_accuracy_claim(
    report: PreflightReport,
    version: GenerationVersion,
    product: ProductTruth | None,
) -> None:
    if product is None:
        return
    claimed = version.accuracy_status == "product_accurate_verified"
    allowed = product.accuracy_status == "product_accurate_verified"
    if claimed and not allowed:
        report.add(
            "accuracy_claim",
            "Accuracy claim is supported",
            "fail",
            "This version claims Product-Accurate Verified, but the product "
            f"profile is still unverified ({', '.join(product.unverified_fields)}). "
            "Attach an approved current mockup first.",
        )
    elif not allowed:
        report.add(
            "accuracy_claim",
            "Accuracy claim is supported",
            "warning",
            "Flagged Requires product verification — no verified current mockup "
            "is attached.",
        )
    else:
        report.add("accuracy_claim", "Accuracy claim is supported", "pass")


# --- human checklist ------------------------------------------------------------


def human_checklist(
    version: GenerationVersion, *, product: ProductTruth | None = None
) -> list[dict[str, Any]]:
    """The questions a person must answer before approval (brief §10)."""
    characters = ", ".join(
        CHARACTER_LABELS.get(c, c) for c in version.brief.character_ids
    ) or "the selected characters"
    botanicals = ", ".join(product.botanicals) if product else "the scent botanicals"

    items = [
        ("identify_bettys", f"Can I identify {characters}, without unrelated faces appearing?"),
        (
            "roles_correct",
            "Are Young, Present, Timeless, Golden and Remembered playing their "
            "correct conceptual roles, with Golden and Remembered not swapped?",
        ),
        (
            "style_cool_neutral",
            "Does the art match approved cool-neutral Modern Heirloom Editorial "
            "rather than generic AI sepia?",
        ),
        (
            "marks_exact",
            "Are the four-petal motifs and the house signature the exact locked "
            "source art?",
        ),
        (
            "bottle_correct",
            "Does the perfume have amber glass, gold ends on both sides, correct "
            "dual-function hardware, a transparent label with ~50% ghost flowers, "
            "white text, gold logo and signature, and lengthwise copy?",
        ),
        ("botanicals_correct", f"Do the botanicals read as {botanicals} — not gardenia?"),
        (
            "storytelling_not_spec",
            "Is this a storytelling illustration, not an allegedly exact product "
            "photograph?",
        ),
        (
            "mobile_clean",
            "Does the 2048 square preview look clean on mobile and sit well on "
            "the current cream site background?",
        ),
    ]
    return [
        {"item_id": key, "question": text, "answer": None, "note": ""}
        for key, text in items
    ]


def summarize(report: PreflightReport) -> str:
    counts = {outcome: 0 for outcome in OUTCOMES}
    for check in report.checks:
        counts[check.outcome] = counts.get(check.outcome, 0) + 1
    return (
        f"{counts['pass']} passed · {counts['warning']} warnings · "
        f"{counts['fail']} failed · {counts['needs_human']} need a human look"
    )


def gate_status(report: PreflightReport, current_status: str) -> str:
    """Where the status ladder should sit after preflight."""
    if report.failed:
        return "needs_accuracy_review"
    if report.warnings or report.needs_human:
        return "needs_accuracy_review"
    return current_status
