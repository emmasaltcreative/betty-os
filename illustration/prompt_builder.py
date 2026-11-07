"""Precedence-aware prompt composition.

Builds both the provider payload and the human-readable *generation brief* shown
in the UI before anything is sent to a paid API.

Precedence (brief §4) — when sources disagree, the earlier wins:

    official exact file > verified product spec > approved character anchor
    > approved style anchor > user scene instruction > generic invention

A newer explicit user instruction supersedes older *general styling*, but never
an official mark or a verified product fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.common import DEFAULT_BRAND_ID
from illustration import canon, vault
from illustration.models import (
    CHARACTER_LABELS,
    IllustrationBrief,
    ProductTruth,
    ReferenceSelection,
    VaultAsset,
)

# Always-on negative guidance distilled from the brand north star (brief §2).
GLOBAL_PROHIBITIONS: tuple[str, ...] = (
    "plastic skin",
    "generic beige AI luxury aesthetics",
    "cartoon eyes",
    "floating props",
    "heavy floral clutter",
    "gibberish lettering",
    "fake or re-drawn logos",
    "repetitive near-identical faces",
    "monochrome sepia or heavy aged-paper treatment",
    "baked-in marketing copy",
)


@dataclass
class ConflictNote:
    """A disagreement between sources, surfaced before approval."""

    field: str
    detail: str
    winner: str
    severity: str = "warning"   # warning | blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "detail": self.detail,
            "winner": self.winner,
            "severity": self.severity,
        }


@dataclass
class GenerationBrief:
    """What will be sent, in words the owner can audit."""

    prompt: str
    negative_prompt: str
    non_negotiable_facts: list[str] = field(default_factory=list)
    reference_tray: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[ConflictNote] = field(default_factory=list)
    canvas: str = "shopify_pdp_square"
    canvas_size: tuple[int, int] = (2048, 2048)
    deterministic_layers: list[str] = field(default_factory=list)
    human_readable: str = ""

    @property
    def is_blocked(self) -> bool:
        return any(c.severity == "blocking" for c in self.conflicts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "non_negotiable_facts": list(self.non_negotiable_facts),
            "reference_tray": list(self.reference_tray),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "canvas": self.canvas,
            "canvas_size": list(self.canvas_size),
            "deterministic_layers": list(self.deterministic_layers),
            "human_readable": self.human_readable,
        }


def _character_block(character_ids: list[str], brand_id: str) -> list[str]:
    anchors = canon.character_anchors(brand_id)
    shared = canon.shared_features(brand_id)
    lines: list[str] = []
    if not character_ids:
        return lines

    lines.append(
        "CHARACTER CANON — one composite muse, not unrelated women. The same "
        "Betty is a composite of Emma and both of her grandmothers. Shared "
        "features across every expression: " + "; ".join(shared) + "."
    )
    for cid in character_ids:
        anchor = anchors.get(cid)
        if anchor is None:
            continue
        parts = [f"{anchor.display_name} ({anchor.inspiration}): {anchor.description}"]
        if anchor.distinct_features:
            parts.append("Distinct: " + ", ".join(anchor.distinct_features) + ".")
        if anchor.wardrobe_notes:
            parts.append(anchor.wardrobe_notes)
        if anchor.signature_props:
            parts.append("Signature: " + ", ".join(anchor.signature_props) + ".")
        lines.append(" ".join(parts))

    if len(character_ids) >= 5:
        lines.extend(canon.group_rules(brand_id))
    return lines


def _product_block(truth: ProductTruth) -> tuple[list[str], list[str]]:
    """Return (prompt lines, non-negotiable facts)."""
    facts = list(truth.immutable_facts)
    lines = [
        f"PRODUCT — {truth.display_name}: {truth.size} {truth.form_factor} in "
        f"{truth.glass_color} glass with {truth.hardware_finish}-finished hardware "
        + ("at BOTH ends" if truth.hardware_both_ends else "")
        + ". Mechanisms: " + "; ".join(truth.mechanisms) + "."
    ]
    if truth.botanicals:
        lines.append(
            "Scent-context botanicals, supporting rather than dominating: "
            + ", ".join(truth.botanicals)
            + "."
        )
    lines.append(
        "This is a real physical product, not an invented prop. Do not alter the "
        "mechanism, proportions or colour."
    )
    return lines, facts


def _reference_tray(
    references: list[ReferenceSelection], brand_id: str
) -> tuple[list[dict[str, Any]], list[ConflictNote]]:
    tray: list[dict[str, Any]] = []
    conflicts: list[ConflictNote] = []
    for ref in references:
        asset = vault.get_asset(ref.asset_id, brand_id)
        if asset is None:
            conflicts.append(
                ConflictNote(
                    field="reference",
                    detail=f"Reference {ref.asset_id} is no longer in the vault.",
                    winner="none",
                    severity="blocking",
                )
            )
            continue
        if asset.state == "rejected":
            conflicts.append(
                ConflictNote(
                    field="reference",
                    detail=(
                        f"{asset.display_name} is marked rejected and must not "
                        "anchor a new generation."
                    ),
                    winner="none",
                    severity="blocking",
                )
            )
            continue
        tray.append(
            {
                "asset_id": asset.asset_id,
                "display_name": asset.display_name,
                "category": asset.category,
                "role": ref.role,
                "precedence": ref.precedence,
                "state": asset.state,
                "proves": _what_it_proves(ref.role),
                "is_private": asset.is_private,
                "api_opt_in": asset.third_party_api_opt_in,
                "note": ref.note,
            }
        )
        # A style board must not be asked to prove product facts.
        if ref.role == "style_only" and ref.precedence == "verified_product_spec":
            conflicts.append(
                ConflictNote(
                    field="reference_role",
                    detail=(
                        f"{asset.display_name} is labelled style_only but was "
                        "selected as a product spec source."
                    ),
                    winner="verified_product_spec",
                )
            )
    return tray, conflicts


def _what_it_proves(role: str) -> str:
    return {
        "style_only": "palette, texture and handling only — no product or face facts",
        "composition_reference": "layout and placement only",
        "character_reference": "identity and facial consistency",
        "product_reference": "product geometry and finish",
        "mark_source": "exact official artwork (composited, never generated)",
    }.get(role, "unspecified")


def _privacy_conflicts(tray: list[dict[str, Any]]) -> list[ConflictNote]:
    """Private references need explicit opt-in before reaching a third party."""
    notes: list[ConflictNote] = []
    for row in tray:
        if row.get("is_private") and not row.get("api_opt_in"):
            notes.append(
                ConflictNote(
                    field="privacy",
                    detail=(
                        f"{row['display_name']} is a private asset without "
                        "third-party API opt-in. Grant consent in the Vault or "
                        "remove it from the tray."
                    ),
                    winner="withhold",
                    severity="blocking",
                )
            )
    return notes


def build(
    brief: IllustrationBrief,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    enforce_privacy_opt_in: bool = True,
) -> GenerationBrief:
    """Compose the full generation brief for one request."""
    tpl = canon.template(brief.template_id, brand_id)
    sections: list[str] = []
    facts: list[str] = []
    conflicts: list[ConflictNote] = []
    deterministic: list[str] = []

    # 1. Brand style (approved style anchor tier).
    sections.append(
        "STYLE — Modern Heirloom Editorial: a timeless mid-century fashion "
        "illustration seen through a modern New York literary atelier. Delicate "
        "but confident dark ink linework; slightly expressive doe eyes; "
        "painterly hand-illustrated shading; warm ivory stock with restrained "
        "tactile grain; dark navy, jade/olive, coffee brown, espresso and subtle "
        "gold; generous negative space. Cool-neutral, not sepia. It should read "
        "as an illustrator commissioned for a sophisticated literary fashion "
        "publication, never a vintage advertising parody."
    )
    if brief.style_notes:
        sections.append(f"STYLE ADDENDUM — {brief.style_notes}")

    # 2. Template recipe.
    if tpl.prompt_blocks:
        sections.append("COMPOSITION — " + " ".join(tpl.prompt_blocks))
    if tpl.mood:
        sections.append(f"MOOD — {tpl.mood}.")
    if tpl.palette:
        sections.append("PALETTE — " + ", ".join(tpl.palette) + ".")

    # 3. Character canon (above style, below product truth).
    sections.extend(_character_block(brief.character_ids, brand_id))

    # 4. Product truth (above characters and style).
    truth: ProductTruth | None = None
    if brief.product_id:
        truth = canon.product(brief.product_id, brand_id)
        product_lines, product_facts = _product_block(truth)
        sections.extend(product_lines)
        facts.extend(product_facts)
        if truth.accuracy_status == "requires_product_verification":
            conflicts.append(
                ConflictNote(
                    field="product_accuracy",
                    detail=(
                        f"{truth.display_name} has no verified current mockup "
                        f"({', '.join(truth.unverified_fields)}). The draft can be "
                        "made, but accuracy must be flagged Requires product "
                        "verification, never Verified."
                    ),
                    winner="requires_product_verification",
                )
            )
        # The label and marks are never generated — they are composited later.
        deterministic.extend(
            [
                "product_label (transparent, amber shows through)",
                "ghost_motif_repeat (alpha ~0.5)",
                "house_mark (exact locked artwork, aspect preserved)",
                "house_signature (exact locked artwork, below EDP text)",
            ]
        )
        sections.append(
            "DO NOT render the printed label text, the house flower mark or the "
            "handwritten signature. Leave the bottle's label area clear and "
            "unlettered — exact artwork is composited afterwards from the "
            "official source files."
        )

    # 5. User scene instruction (newest explicit wins over general styling).
    if brief.scene_text.strip():
        sections.append(f"SCENE — {brief.scene_text.strip()}")

    # 6. Canvas and safe area.
    width, height = brief.canvas_size()
    sections.append(
        f"CANVAS — compose natively for {width}×{height}px ({brief.canvas}). Keep "
        f"every face, the bottle's ends and the label clear of the outer "
        f"{brief.safe_area_percent:.0f}% on all sides so a mobile crop cannot cut "
        "them. Leave no baked-in marketing copy."
    )

    # 7. References.
    tray, ref_conflicts = _reference_tray(brief.references, brand_id)
    conflicts.extend(ref_conflicts)
    if enforce_privacy_opt_in:
        conflicts.extend(_privacy_conflicts(tray))
    if tray:
        sections.append(
            "REFERENCES — "
            + "; ".join(f"{r['display_name']} ({r['proves']})" for r in tray)
            + "."
        )
    if brief.character_ids and not any(
        r["role"] == "character_reference" for r in tray
    ):
        conflicts.append(
            ConflictNote(
                field="character_reference",
                detail=(
                    "No character reference is attached. The canon requires a "
                    "chosen character reference in every generation or revision "
                    "for face consistency."
                ),
                winner="approved_character_anchor",
            )
        )

    # 8. Prohibitions.
    prohibitions = list(GLOBAL_PROHIBITIONS) + list(tpl.prohibited_substitutions)
    if truth is not None:
        prohibitions.extend(truth.prohibited_substitutions)
    for cid in brief.character_ids:
        anchor = canon.character_anchors(brand_id).get(cid)
        if anchor:
            prohibitions.extend(anchor.prohibited)
    prohibitions.extend(brief.prohibitions)
    # Stable de-duplication.
    seen: set[str] = set()
    negative = [p for p in prohibitions if not (p in seen or seen.add(p))]

    prompt = "\n\n".join(s for s in sections if s.strip())
    generation = GenerationBrief(
        prompt=prompt,
        negative_prompt="Avoid: " + "; ".join(negative) + ".",
        non_negotiable_facts=facts,
        reference_tray=tray,
        conflicts=conflicts,
        canvas=brief.canvas,
        canvas_size=(width, height),
        deterministic_layers=deterministic,
    )
    generation.human_readable = render_human_readable(generation, brief)
    return generation


def render_human_readable(generation: GenerationBrief, brief: IllustrationBrief) -> str:
    """Markdown the owner reads before a paid call is made."""
    lines: list[str] = [
        "### Generation brief",
        "",
        f"**Template** {brief.template_id} · **Canvas** {generation.canvas} "
        f"({generation.canvas_size[0]}×{generation.canvas_size[1]})",
    ]
    if brief.character_ids:
        lines.append(
            "**Characters** "
            + ", ".join(
                CHARACTER_LABELS.get(c, c) for c in brief.character_ids
            )
        )
    if brief.product_id:
        lines.append(f"**Product** {brief.product_id}")
    lines.append("")

    if generation.non_negotiable_facts:
        lines.append("**Non-negotiable product facts**")
        lines.extend(f"- {fact}" for fact in generation.non_negotiable_facts)
        lines.append("")

    lines.append("**Reference tray**")
    if generation.reference_tray:
        for row in generation.reference_tray:
            consent = "" if row.get("api_opt_in") else " · ⚠ no API opt-in"
            lines.append(
                f"- `{row['asset_id']}` {row['display_name']} — {row['role']} "
                f"({row['state']}); proves {row['proves']}{consent}"
            )
    else:
        lines.append("- _none selected_")
    lines.append("")

    if generation.deterministic_layers:
        lines.append("**Composited deterministically afterwards — never generated**")
        lines.extend(f"- {layer}" for layer in generation.deterministic_layers)
        lines.append("")

    if generation.conflicts:
        lines.append("**Conflicts and flags**")
        for conflict in generation.conflicts:
            mark = "⛔" if conflict.severity == "blocking" else "⚠"
            lines.append(f"- {mark} *{conflict.field}* — {conflict.detail}")
        lines.append("")

    lines.extend(["**Prompt sent to the provider**", "", "```text", generation.prompt, "```", ""])
    lines.extend(["**Negative guidance**", "", generation.negative_prompt])
    return "\n".join(lines)


def auto_references(
    brief: IllustrationBrief, *, brand_id: str = DEFAULT_BRAND_ID
) -> list[ReferenceSelection]:
    """Assemble the default reference tray from saved vault assets.

    The owner never re-uploads: the highest-precedence approved asset for each
    slot is selected automatically and can be swapped in the UI.
    """
    selections: list[ReferenceSelection] = []
    seen: set[str] = set()

    def add(asset: VaultAsset | None, role: str, precedence: str, note: str = "") -> None:
        if asset is None or asset.asset_id in seen:
            return
        seen.add(asset.asset_id)
        selections.append(
            ReferenceSelection(
                asset_id=asset.asset_id, role=role, precedence=precedence, note=note
            )
        )

    # Locked marks first — these drive the deterministic layer, not the model.
    for tag in ("quatrefoil", "signature"):
        add(
            vault.locked_mark(brand_id, tag=tag),
            "mark_source",
            "official_exact_file",
            note=f"exact {tag} artwork",
        )

    # Verified product truth.
    if brief.product_id:
        add(
            vault.best_asset(
                brand_id,
                categories=["product_truth"],
                product_id=brief.product_id,
            ),
            "product_reference",
            "verified_product_spec",
            note="most recent approved product mockup",
        )

    # Character anchors.
    for cid in brief.character_ids:
        add(
            vault.best_asset(
                brand_id, categories=["character_masters"], character_id=cid
            ),
            "character_reference",
            "approved_character_anchor",
            note=f"face anchor for {CHARACTER_LABELS.get(cid, cid)}",
        )

    # Style and composition anchor.
    add(
        vault.best_asset(brand_id, categories=["style_anchors"]),
        "style_only",
        "approved_style_anchor",
        note="approved editorial board",
    )
    return selections
