"""The revision vocabulary.

Three questions are answered here, and only here:

1. What kind of change is this? — `RevisionType`
2. Which piece of the campaign does it touch? — `RevisionField`
3. Could a renderer in this repository actually make that change? —
   `renderer_support`

Capability is never asserted by a type on its own. A copy rewrite is only
AI_ASSISTED if there is a field to write it into and a renderer that can carry
it into a new version; otherwise it falls to HUMAN_INPUT_REQUIRED with a named
reason. Keeping that judgement in one table is what stops the interface from
promising work the code cannot do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Capability levels ------------------------------------------------------

READY_TO_APPLY = "READY_TO_APPLY"
AI_ASSISTED = "AI_ASSISTED"
HUMAN_INPUT_REQUIRED = "HUMAN_INPUT_REQUIRED"

CAPABILITIES: tuple[str, ...] = (READY_TO_APPLY, AI_ASSISTED, HUMAN_INPUT_REQUIRED)

CAPABILITY_LABELS: dict[str, str] = {
    READY_TO_APPLY: "Ready to Apply",
    AI_ASSISTED: "AI Suggestion Available",
    HUMAN_INPUT_REQUIRED: "Human Input Required",
}

# Actions a revision request can offer, by capability.
GENERATE_ACTIONS: tuple[str, ...] = (
    "generate_options",
    "apply_selected_option",
    "rerender",
)
DETERMINISTIC_ACTIONS: tuple[str, ...] = ("apply_change", "rerender")
HUMAN_ACTIONS: tuple[str, ...] = ("supply_input",)


# --- Fields a revision can change -------------------------------------------

@dataclass(frozen=True)
class RevisionField:
    """One addressable value in a campaign, and the limits it must respect."""

    key: str
    label: str
    kind: str  # "text_lines" | "text" | "markdown" | "seconds" | "clip_list" | "slide_order"
    max_words: int | None = None
    max_chars: int | None = None
    note: str = ""

    @property
    def is_copy(self) -> bool:
        return self.kind in {"text_lines", "text", "markdown"}


# On-screen word budget comes from production/global_defaults.json
# (maximum_words_per_screen: 12). Platform character limits are the published
# ceilings, kept deliberately below the maximum so nothing truncates.
FIELDS: dict[str, RevisionField] = {
    "overlay_hook": RevisionField(
        "overlay_hook", "On-screen hook", "text_lines", max_words=12,
        note="First line a viewer reads. Rendered into the video.",
    ),
    "overlay_supporting": RevisionField(
        "overlay_supporting", "On-screen supporting copy", "text_lines", max_words=12,
        note="Second on-screen line. Rendered into the video.",
    ),
    "overlay_cta": RevisionField(
        "overlay_cta", "On-screen call to action", "text", max_words=8,
        note="Rendered into the video at the CTA timing.",
    ),
    "instagram_caption": RevisionField(
        "instagram_caption", "Instagram caption", "markdown", max_chars=2200,
    ),
    "pinterest_caption": RevisionField(
        "pinterest_caption", "Pinterest caption", "markdown", max_chars=500,
    ),
    "pinterest_title": RevisionField(
        "pinterest_title", "Pinterest metadata title", "text", max_chars=100,
    ),
    "pinterest_description": RevisionField(
        "pinterest_description", "Pinterest metadata description", "markdown", max_chars=500,
    ),
    "pinterest_cta": RevisionField(
        "pinterest_cta", "Pinterest call to action", "text", max_words=12,
    ),
    "email_subject": RevisionField(
        "email_subject", "Email subject", "text", max_chars=60,
    ),
    "email_preview": RevisionField(
        "email_preview", "Email preview text", "text", max_chars=90,
    ),
    "email_body": RevisionField(
        "email_body", "Email body", "markdown", max_chars=2000,
    ),
    "email_cta": RevisionField(
        "email_cta", "Email call to action", "text", max_words=14,
    ),
    "product_copy": RevisionField(
        "product_copy", "Product copy", "markdown", max_chars=1200,
    ),
    "cta_timing": RevisionField(
        "cta_timing", "Call-to-action timing", "seconds",
        note="Second at which the CTA overlay appears.",
    ),
    "overlay_timing": RevisionField(
        "overlay_timing", "Overlay timing", "seconds",
        note="Second at which on-screen copy appears.",
    ),
    "clip_list": RevisionField(
        "clip_list", "Source clips", "clip_list",
        note="Which clips are used, and in what order.",
    ),
    "duration": RevisionField(
        "duration", "Total duration", "seconds",
    ),
    "slide_order": RevisionField(
        "slide_order", "Slide order", "slide_order",
    ),
}


def field_for(key: str) -> RevisionField | None:
    return FIELDS.get(key)


# --- Revision types ---------------------------------------------------------

@dataclass(frozen=True)
class RevisionType:
    """A named kind of change, with the fields it is allowed to touch."""

    key: str
    label: str
    family: str  # "copy" | "render" | "human"
    natural_capability: str
    default_field: str | None = None
    allowed_fields: tuple[str, ...] = ()
    instruction_hint: str = ""
    requirement: str = ""

    def fields(self) -> tuple[str, ...]:
        if self.allowed_fields:
            return self.allowed_fields
        return (self.default_field,) if self.default_field else ()


COPY_FIELDS_ANY: tuple[str, ...] = (
    "overlay_hook",
    "overlay_supporting",
    "overlay_cta",
    "instagram_caption",
    "pinterest_caption",
    "pinterest_title",
    "pinterest_description",
    "pinterest_cta",
    "email_subject",
    "email_preview",
    "email_body",
    "email_cta",
    "product_copy",
)

_TYPES: tuple[RevisionType, ...] = (
    # --- Copy: a rewrite an LLM can propose and a person approves -----------
    RevisionType(
        "hook_rewrite", "Rewrite the hook", "copy", AI_ASSISTED,
        default_field="overlay_hook",
        instruction_hint=(
            "Rewrite the on-screen hook so it names a specific recognisable moment "
            "instead of gesturing at one."
        ),
    ),
    RevisionType(
        "supporting_copy_rewrite", "Rewrite the supporting copy", "copy", AI_ASSISTED,
        default_field="overlay_supporting",
        instruction_hint=(
            "Rewrite the supporting on-screen copy to name the emotional feeling the "
            "viewer recognises before introducing the reading ritual."
        ),
    ),
    RevisionType(
        "cta_rewrite", "Rewrite the call to action", "copy", AI_ASSISTED,
        default_field="overlay_cta",
        allowed_fields=("overlay_cta", "pinterest_cta", "email_cta"),
        instruction_hint=(
            "Rewrite the call to action so it invites rather than instructs, in Betty's voice."
        ),
    ),
    RevisionType(
        "caption_rewrite", "Rewrite the caption", "copy", AI_ASSISTED,
        default_field="instagram_caption",
        allowed_fields=("instagram_caption", "pinterest_caption"),
        instruction_hint=(
            "Rewrite the caption so the specific emotional detail arrives first and the "
            "brand is introduced only after the feeling is established."
        ),
    ),
    RevisionType(
        "email_rewrite", "Rewrite the email copy", "copy", AI_ASSISTED,
        default_field="email_body",
        allowed_fields=("email_subject", "email_preview", "email_body", "email_cta"),
        instruction_hint="Rewrite this email section in Betty's voice, warm and unhurried.",
    ),
    RevisionType(
        "pinterest_metadata_rewrite", "Rewrite the Pinterest metadata", "copy", AI_ASSISTED,
        default_field="pinterest_description",
        allowed_fields=(
            "pinterest_title", "pinterest_description", "pinterest_caption", "pinterest_cta",
        ),
        instruction_hint=(
            "Replace the keyword string with one thoughtful sentence that names the ritual "
            "and invites the waitlist."
        ),
    ),
    RevisionType(
        "product_copy_rewrite", "Rewrite the product copy", "copy", AI_ASSISTED,
        default_field="product_copy",
        instruction_hint="Rewrite the product copy without adding any new product claim.",
    ),
    RevisionType(
        "shorten_copy", "Shorten the copy", "copy", AI_ASSISTED,
        allowed_fields=COPY_FIELDS_ANY,
        instruction_hint="Shorten this copy while keeping the specific detail that earns it.",
    ),
    RevisionType(
        "expand_copy", "Expand the copy", "copy", AI_ASSISTED,
        allowed_fields=COPY_FIELDS_ANY,
        instruction_hint="Give this copy a little more room without adding filler.",
    ),
    RevisionType(
        "voice_alignment", "Align the copy to the Brand Guide", "copy", AI_ASSISTED,
        allowed_fields=COPY_FIELDS_ANY,
        instruction_hint="Bring this copy into Betty's voice as the Brand Guide describes it.",
    ),
    RevisionType(
        "clarity_improvement", "Make the copy clearer", "copy", AI_ASSISTED,
        allowed_fields=COPY_FIELDS_ANY,
        instruction_hint="Make this copy clearer without making it plainer.",
    ),
    RevisionType(
        "emotional_specificity", "Make the copy emotionally specific", "copy", AI_ASSISTED,
        allowed_fields=COPY_FIELDS_ANY,
        instruction_hint=(
            "Replace the general feeling with one specific observed detail the reader recognises."
        ),
    ),
    RevisionType(
        "seo_keyword_revision", "Revise the search wording", "copy", AI_ASSISTED,
        allowed_fields=(
            "pinterest_title", "pinterest_description", "pinterest_caption", "product_copy",
        ),
        instruction_hint=(
            "Rework the searchable wording so it reads as a sentence, not a keyword list."
        ),
    ),

    # --- Deterministic render changes ---------------------------------------
    RevisionType(
        "overlay_timing_change", "Change the overlay timing", "render", READY_TO_APPLY,
        default_field="overlay_timing",
    ),
    RevisionType(
        "cta_timing_change", "Change the CTA timing", "render", READY_TO_APPLY,
        default_field="cta_timing",
    ),
    RevisionType(
        "clip_reorder", "Reorder the clips", "render", READY_TO_APPLY,
        default_field="clip_list",
    ),
    RevisionType(
        "clip_remove", "Remove a clip", "render", READY_TO_APPLY,
        default_field="clip_list",
    ),
    RevisionType(
        "source_asset_replace", "Replace a source asset", "render", READY_TO_APPLY,
        default_field="clip_list",
    ),
    RevisionType(
        "duration_change", "Change the duration", "render", READY_TO_APPLY,
        default_field="duration",
    ),
    RevisionType(
        "font_size_change", "Change the font size", "render", READY_TO_APPLY,
    ),
    RevisionType(
        "text_position_change", "Move the text", "render", READY_TO_APPLY,
    ),
    RevisionType(
        "crop_change", "Change the crop", "render", READY_TO_APPLY,
    ),
    RevisionType(
        "transition_change", "Change the transition", "render", READY_TO_APPLY,
    ),
    RevisionType(
        "slide_reorder", "Reorder the slides", "render", READY_TO_APPLY,
        default_field="slide_order",
    ),

    # --- Genuinely human ----------------------------------------------------
    RevisionType(
        "new_photography", "New photograph needed", "human", HUMAN_INPUT_REQUIRED,
        requirement="A new photograph that does not exist yet.",
    ),
    RevisionType(
        "new_video_footage", "New footage needed", "human", HUMAN_INPUT_REQUIRED,
        requirement="A new video clip that does not exist yet.",
    ),
    RevisionType(
        "product_reshoot", "Product reshoot needed", "human", HUMAN_INPUT_REQUIRED,
        requirement="A fresh shoot of the product.",
    ),
    RevisionType(
        "new_physical_asset", "New physical asset needed", "human", HUMAN_INPUT_REQUIRED,
        requirement="Something that has to be made or bought first.",
    ),
    RevisionType(
        "missing_logo_file", "Logo file missing", "human", HUMAN_INPUT_REQUIRED,
        requirement="A clean logo file.",
    ),
    RevisionType(
        "missing_product_image", "Product image missing", "human", HUMAN_INPUT_REQUIRED,
        requirement="A product image that is not in the library.",
    ),
    RevisionType(
        "packaging_redesign", "Packaging redesign needed", "human", HUMAN_INPUT_REQUIRED,
        requirement="A packaging decision made outside BettyOS.",
    ),
    RevisionType(
        "unsupported_renderer_feature", "Not supported by any renderer", "human",
        HUMAN_INPUT_REQUIRED,
        requirement="A renderer capability BettyOS does not have.",
    ),
)

TYPES: dict[str, RevisionType] = {t.key: t for t in _TYPES}

COPY_TYPES: tuple[str, ...] = tuple(t.key for t in _TYPES if t.family == "copy")
RENDER_TYPES: tuple[str, ...] = tuple(t.key for t in _TYPES if t.family == "render")
HUMAN_TYPES: tuple[str, ...] = tuple(t.key for t in _TYPES if t.family == "human")
ALL_TYPES: tuple[str, ...] = tuple(TYPES)


def revision_type(key: str) -> RevisionType | None:
    return TYPES.get(key)


def type_label(key: str) -> str:
    entry = TYPES.get(key)
    return entry.label if entry else key.replace("_", " ").capitalize()


# --- What the renderers in this repository can really do ---------------------

@dataclass(frozen=True)
class Support:
    """Whether a field can be changed on a template, and why not when it cannot."""

    supported: bool
    reason: str = ""
    requires_rerender: bool = False


# Video: only two templates have a code path (renderers/video.py). The
# multi-clip reel reads its overlay text, clip list, duration and CTA timing
# from its render configuration, so all four can be revised. The atmospheric
# loop ignores the clip you pick, so its clip list cannot honestly be changed.
_REEL_FIELDS: dict[str, Support] = {
    "overlay_hook": Support(True, requires_rerender=True),
    "overlay_supporting": Support(True, requires_rerender=True),
    "overlay_cta": Support(True, requires_rerender=True),
    "instagram_caption": Support(True),
    "pinterest_caption": Support(True),
    "cta_timing": Support(True, requires_rerender=True),
    "clip_list": Support(True, requires_rerender=True),
    "duration": Support(True, requires_rerender=True),
    "overlay_timing": Support(
        False,
        "Overlay timing follows the clip boundaries and has no separate setting.",
    ),
    "slide_order": Support(False, "This template has no slides."),
}

_LOOP_FIELDS: dict[str, Support] = {
    "instagram_caption": Support(True),
    "pinterest_caption": Support(True),
    "overlay_hook": Support(
        False, "The single-clip loop renderer does not accept revised overlay text."
    ),
    "overlay_supporting": Support(
        False, "The single-clip loop renderer does not accept revised overlay text."
    ),
    "overlay_cta": Support(
        False, "The single-clip loop renderer does not accept revised overlay text."
    ),
    "clip_list": Support(
        False, "This template always uses one fixed studio clip; the clip cannot be swapped."
    ),
}

_COPY_FIELDS: dict[str, Support] = {
    "instagram_caption": Support(True),
    "pinterest_caption": Support(True),
    "pinterest_title": Support(True),
    "pinterest_description": Support(True),
    "pinterest_cta": Support(True),
    "email_subject": Support(True),
    "email_preview": Support(True),
    "email_body": Support(True),
    "email_cta": Support(True),
    "product_copy": Support(True),
}

# Stills and carousels lay out one generic canvas; the template-specific text
# fields are never read, so rewriting them would change nothing on the image.
_IMAGE_FIELDS: dict[str, Support] = {
    "instagram_caption": Support(True),
    "pinterest_caption": Support(True),
    "overlay_hook": Support(
        False, "This template's renderer does not lay out revised on-image text."
    ),
    "overlay_supporting": Support(
        False, "This template's renderer does not lay out revised on-image text."
    ),
    "overlay_cta": Support(
        False, "This template's renderer does not lay out revised on-image text."
    ),
    "slide_order": Support(
        False, "Carousel slides are generated in a fixed order that cannot be rearranged."
    ),
}

_UNSUPPORTED_EVERYWHERE: dict[str, str] = {
    "font_size_change": "No renderer accepts a per-render font size.",
    "text_position_change": "Text position comes from the Production Brain layout, not per render.",
    "crop_change": "Crop strategy is a global production setting, not a per-render option.",
    "transition_change": "Every renderer uses the one transition style in the Production Brain.",
}


def _field_table(template_id: str, renderer_module: str) -> dict[str, Support]:
    if template_id == "cinematic_multi_clip_reel":
        return _REEL_FIELDS
    if template_id == "single_clip_atmospheric_loop":
        return _LOOP_FIELDS
    if renderer_module == "copy":
        return _COPY_FIELDS
    if renderer_module in {"static", "carousel"}:
        return _IMAGE_FIELDS
    return {}


def renderer_support(
    *,
    template_id: str,
    renderer_module: str,
    field_key: str,
    revision_type_key: str = "",
) -> Support:
    """Can this template's renderer carry a change to this field into a new version?"""
    blocked = _UNSUPPORTED_EVERYWHERE.get(revision_type_key)
    if blocked:
        return Support(False, blocked)
    table = _field_table(template_id, renderer_module)
    if not table:
        return Support(
            False,
            f"No renderer in BettyOS produces `{template_id}`, so nothing can be revised.",
        )
    support = table.get(field_key)
    if support is None:
        return Support(
            False,
            f"The {template_id.replace('_', ' ')} renderer has no setting for "
            f"{FIELDS[field_key].label.lower()}."
            if field_key in FIELDS
            else "That field does not exist on this template.",
        )
    return support


def supported_fields(*, template_id: str, renderer_module: str) -> list[str]:
    return [
        key
        for key, support in _field_table(template_id, renderer_module).items()
        if support.supported
    ]


def capability_summary(*, template_id: str, renderer_module: str) -> dict[str, str]:
    """Plain-language capability list, for prompts and for the interface."""
    table = _field_table(template_id, renderer_module)
    out: dict[str, str] = {}
    for key, support in table.items():
        label = FIELDS[key].label if key in FIELDS else key
        out[label] = "can be revised" if support.supported else support.reason
    for key, reason in _UNSUPPORTED_EVERYWHERE.items():
        out[type_label(key)] = reason
    return out


# --- Human requirements -----------------------------------------------------

@dataclass
class Requirement:
    """What is missing, in the words of the person who has to supply it."""

    headline: str
    specifics: list[str] = field(default_factory=list)
    action: str = "Add Source Asset"
    unlocks: str = ""
    accepts: tuple[str, ...] = (".mp4", ".mov", ".png", ".jpg", ".jpeg")


_REQUIREMENTS: dict[str, Requirement] = {
    "new_video_footage": Requirement(
        "New footage needed",
        [
            "One 5–8 second vertical clip",
            "Natural window light",
            "Book opening in frame",
            "No visible product prototype errors",
        ],
        action="Add Source Asset",
        unlocks="Once the clip is in the library, BettyOS can build a new reel version with it.",
        accepts=(".mp4", ".mov"),
    ),
    "new_photography": Requirement(
        "New photograph needed",
        [
            "One vertical lifestyle photograph",
            "Natural light, no flash",
            "The reading hour in progress, not staged",
            "Minimum 1600 × 2000 pixels",
        ],
        action="Upload Asset",
        unlocks="Once the photograph exists, BettyOS can render a still or pin from it.",
        accepts=(".png", ".jpg", ".jpeg"),
    ),
    "missing_product_image": Requirement(
        "Product image missing",
        [
            "Vertical product image",
            "Minimum 1600 × 2000 pixels",
            "Jade cover visible",
            "Cream lining visible",
        ],
        action="Upload Asset",
        unlocks="Once the image is supplied, BettyOS can place it in a product render.",
        accepts=(".png", ".jpg", ".jpeg"),
    ),
    "product_reshoot": Requirement(
        "Product reshoot needed",
        [
            "The finished prototype, not the sample",
            "Vertical framing, natural light",
            "Cover and lining both legible",
        ],
        action="Upload Asset",
        unlocks="Once reshot frames exist, BettyOS can rebuild the product pieces.",
    ),
    "missing_logo_file": Requirement(
        "Logo file missing",
        [
            "Unwatermarked logo",
            "Transparent background PNG or SVG",
            "Full wordmark, not the monogram alone",
        ],
        action="Upload Asset",
        unlocks="Once the logo is supplied, it can be placed on renders that call for it.",
        accepts=(".png", ".svg"),
    ),
    "new_physical_asset": Requirement(
        "Physical item needed first",
        ["The item has to exist before it can be photographed or filmed."],
        action="Add Source Asset",
        unlocks="Once it exists and is photographed, the render can be built.",
    ),
    "packaging_redesign": Requirement(
        "Packaging decision needed",
        [
            "A packaging direction chosen outside BettyOS",
            "Then artwork or photography of the chosen packaging",
        ],
        action="Add Source Asset",
        unlocks="Once the decision and artwork exist, packaging renders become possible.",
    ),
    "unsupported_renderer_feature": Requirement(
        "Not supported by any renderer",
        ["This change needs a renderer capability BettyOS does not have."],
        action="",
        unlocks="A developer would need to add the capability before this can run.",
    ),
}


def requirement_for(revision_type_key: str, *, reason: str = "") -> Requirement:
    base = _REQUIREMENTS.get(revision_type_key)
    if base is None:
        return Requirement(
            "Human input needed",
            [reason] if reason else ["BettyOS cannot make this change safely on its own."],
            action="",
            unlocks="",
        )
    if reason and revision_type_key == "unsupported_renderer_feature":
        return Requirement(base.headline, [reason], action="", unlocks=base.unlocks)
    return Requirement(
        base.headline, list(base.specifics), base.action, base.unlocks, base.accepts
    )
