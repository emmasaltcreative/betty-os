"""The Revision Capability Classifier.

A recommendation is read in context — the asset it points at, that asset's
current copy and render configuration, the source assets that exist, the Brand
Guide, the campaign objective, the platform, and what the renderer for that
template can actually do — and comes back as one of three capability levels.

The model supplies the reading. The gate below supplies the truth: whatever the
model proposes is checked against `services.revision_types.renderer_support`
and against the configuration on disk, and is demoted to
HUMAN_INPUT_REQUIRED when BettyOS could not really carry the change through.
That ordering matters. It is why a copy rewrite is never called manual work,
and why a change no renderer can make is never called ready.

Classifications are cached per campaign against a fingerprint of the
recommendation, so an edited recommendation is reclassified and an unchanged one
never costs a second model call.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from services import revision_types as rt
from services.llm import GenerationError, complete_json
from services.revision_context import (
    AssetTarget,
    RenderConfig,
    available_source_assets,
    campaign_objective,
    current_value,
    list_asset_targets,
    load_render_config,
    platform_for,
    renderer_capabilities,
    resolve_asset,
    revisions_dir,
)
from src.persistence import atomic_write_json, load_json

CLASSIFICATIONS_FILE = "classifications.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --- Result -----------------------------------------------------------------

@dataclass
class Classification:
    recommendation_id: str
    capability: str
    revision_type: str
    confidence: float
    rationale: str
    target_field: str | None = None
    required_inputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    supported_actions: list[str] = field(default_factory=list)
    asset_id: str | None = None
    asset_name: str = ""
    render_version_id: str | None = None
    original_value: str = ""
    default_instruction: str = ""
    proposed_change: dict[str, Any] = field(default_factory=dict)
    requirement: dict[str, Any] = field(default_factory=dict)
    source: str = "rules"
    fingerprint: str = ""
    classified_at: str = field(default_factory=_now)

    @property
    def label(self) -> str:
        return rt.CAPABILITY_LABELS.get(self.capability, self.capability)

    @property
    def is_ai_assisted(self) -> bool:
        return self.capability == rt.AI_ASSISTED

    @property
    def is_ready(self) -> bool:
        return self.capability == rt.READY_TO_APPLY

    @property
    def needs_human(self) -> bool:
        return self.capability == rt.HUMAN_INPUT_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "capability": self.capability,
            "revision_type": self.revision_type,
            "target_field": self.target_field,
            "confidence": round(float(self.confidence), 2),
            "rationale": self.rationale,
            "required_inputs": list(self.required_inputs),
            "missing_inputs": list(self.missing_inputs),
            "supported_actions": list(self.supported_actions),
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "render_version_id": self.render_version_id,
            "original_value": self.original_value,
            "default_instruction": self.default_instruction,
            "proposed_change": dict(self.proposed_change),
            "requirement": dict(self.requirement),
            "source": self.source,
            "fingerprint": self.fingerprint,
            "classified_at": self.classified_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Classification":
        return cls(
            recommendation_id=str(data.get("recommendation_id") or ""),
            capability=str(data.get("capability") or rt.HUMAN_INPUT_REQUIRED),
            revision_type=str(data.get("revision_type") or "unsupported_renderer_feature"),
            confidence=float(data.get("confidence") or 0.0),
            rationale=str(data.get("rationale") or ""),
            target_field=data.get("target_field") or None,
            required_inputs=[str(x) for x in data.get("required_inputs") or []],
            missing_inputs=[str(x) for x in data.get("missing_inputs") or []],
            supported_actions=[str(x) for x in data.get("supported_actions") or []],
            asset_id=data.get("asset_id") or None,
            asset_name=str(data.get("asset_name") or ""),
            render_version_id=data.get("render_version_id") or None,
            original_value=str(data.get("original_value") or ""),
            default_instruction=str(data.get("default_instruction") or ""),
            proposed_change=dict(data.get("proposed_change") or {}),
            requirement=dict(data.get("requirement") or {}),
            source=str(data.get("source") or "rules"),
            fingerprint=str(data.get("fingerprint") or ""),
            classified_at=str(data.get("classified_at") or _now()),
        )


# --- Fingerprint ------------------------------------------------------------

def fingerprint(recommendation: dict[str, Any]) -> str:
    """Changes when the recommendation changes, so an edit is reclassified."""
    payload = "|".join(
        str(recommendation.get(key) or "")
        for key in ("title", "full_instruction", "recommendation_type", "affected_asset")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --- Deterministic reading of the recommendation ----------------------------

_HUMAN_SIGNALS: tuple[tuple[str, str], ...] = (
    (r"\bfilm\b.*\b(footage|clip|video)\b|\bnew (video )?footage\b|\bshoot (new|fresh) (video|footage)\b",
     "new_video_footage"),
    (r"\breshoot\b|\bre-shoot\b|\bphotograph the (finished )?prototype\b", "product_reshoot"),
    (r"\b(take|shoot|capture) a new (lifestyle )?(photograph|photo|image)\b|\bnew photography\b",
     "new_photography"),
    (r"\bunwatermarked\b|\blogo file\b|\bprovide .*logo\b", "missing_logo_file"),
    (r"\bproduct image (is )?missing\b|\bmissing product image\b", "missing_product_image"),
    (r"\bpackaging\b.*\b(redesign|rework)\b", "packaging_redesign"),
    (r"\bcreate a missing source asset\b|\bmissing source asset\b", "new_physical_asset"),
    (r"\bunsupported renderer\b|\bimplement an unsupported\b", "unsupported_renderer_feature"),
)

_RENDER_SIGNALS: tuple[tuple[str, str], ...] = (
    (r"\b(move|shift|bring)\b.*\bcta\b.*\bsecond\b|\bcta\b.*\bfrom second\b|\bcta timing\b",
     "cta_timing_change"),
    (r"\bremove\b.*\b(img_\d+|clip)\b|\bcut\b.*\b(img_\d+|clip)\b|\bdrop\b.*\bclip\b",
     "clip_remove"),
    (r"\breorder\b.*\bclips?\b|\bswap the order\b.*\bclips?\b", "clip_reorder"),
    (r"\breorder\b.*\bslides?\b", "slide_reorder"),
    (r"\b(use|swap in|substitute)\b.*\b(another|different|existing)\b.*\b(image|clip|asset)\b|\breplace\b.*\b(img_\d+)\b",
     "source_asset_replace"),
    (r"\b(change|set|make)\b.*\bduration\b|\b\d+\s*seconds?\s*(long|total)\b|\breel duration\b",
     "duration_change"),
    (r"\bmove\b.*\boverlay\b.*\b(up|down|upward|downward|higher|lower)\b|\btext position\b",
     "text_position_change"),
    (r"\b(font size|type size)\b", "font_size_change"),
    (r"\bcrop\b", "crop_change"),
    (r"\btransition\b", "transition_change"),
    (r"\boverlay timing\b|\b(move|shift)\b.*\boverlay\b.*\bsecond\b", "overlay_timing_change"),
)

_COPY_SIGNALS: tuple[tuple[str, tuple[str, str | None]], ...] = (
    (r"\bsupporting (on-screen )?copy\b|\bon-screen supporting\b",
     ("supporting_copy_rewrite", "overlay_supporting")),
    (r"\bsubject line\b", ("email_rewrite", "email_subject")),
    (r"\bpreview text\b", ("email_rewrite", "email_preview")),
    (r"\bemail\b", ("email_rewrite", "email_body")),
    (r"\bpinterest\b.*\b(description|metadata|title|caption|pin)\b|\bpin description\b",
     ("pinterest_metadata_rewrite", "pinterest_description")),
    (r"\bproduct (copy|description)\b", ("product_copy_rewrite", "product_copy")),
    (r"\bon-screen (hook|copy)\b|\bhook\b", ("hook_rewrite", "overlay_hook")),
    (r"\bcta\b|\bcall to action\b", ("cta_rewrite", "overlay_cta")),
    (r"\bcaption\b", ("caption_rewrite", "instagram_caption")),
    (r"\bshorten\b|\btighten\b|\btrim the copy\b", ("shorten_copy", None)),
    (r"\bexpand\b|\bgive .* more room\b", ("expand_copy", None)),
    (r"\b(brand guide|brand voice|betty'?s voice|voice guidelines)\b", ("voice_alignment", None)),
    (r"\bless generic\b|\bgeneric\b", ("voice_alignment", None)),
    (r"\bemotionally specific\b|\bemotional specificity\b|\bname the feeling\b",
     ("emotional_specificity", None)),
    (r"\bclearer\b|\bclarity\b", ("clarity_improvement", None)),
    (r"\b(seo|keyword)\b", ("seo_keyword_revision", "pinterest_description")),
)

_TYPE_TO_COPY_DEFAULT: dict[str, tuple[str, str | None]] = {
    "revise_copy": ("caption_rewrite", "instagram_caption"),
    "change_cta": ("cta_rewrite", "overlay_cta"),
    "change_timing": ("cta_timing_change", "cta_timing"),
    "change_duration": ("duration_change", "duration"),
    "remove_asset": ("clip_remove", "clip_list"),
    "replace_asset": ("source_asset_replace", "clip_list"),
    "rerender": ("clip_reorder", "clip_list"),
}


def _text_of(recommendation: dict[str, Any]) -> str:
    return " ".join(
        str(recommendation.get(key) or "")
        for key in ("title", "full_instruction", "expected_changes", "rationale")
    ).lower()


def _title_of(recommendation: dict[str, Any]) -> str:
    return str(recommendation.get("title") or "").lower()


def _seconds_in(text: str) -> float | None:
    """The second a change should land on: `to second 9` beats `from second 12`."""
    for pattern in (
        r"\bto (?:second|sec)\s*(\d+(?:\.\d+)?)",
        r"\bat (?:second|sec)\s*(\d+(?:\.\d+)?)",
        r"\bseconds?\s*(\d+(?:\.\d+)?)\s*[–\-]\s*\d+",
        r"\b(\d+(?:\.\d+)?)\s*seconds?\b",
    ):
        matches = re.findall(pattern, text)
        if matches:
            return float(matches[-1] if pattern.startswith(r"\bto ") else matches[0])
    return None


def _clip_names_in(text: str) -> list[str]:
    names: list[str] = []
    for name in re.findall(r"img_\d+", text, flags=re.IGNORECASE):
        upper = name.upper()
        if upper not in names:
            names.append(upper)
    return names


def classify_by_rules(recommendation: dict[str, Any]) -> tuple[str, str | None]:
    """Revision type and target field from the recommendation and its category.

    Used when the model is unavailable, and as the safety net whenever the model
    proposes something outside the vocabulary.

    The title is read before the body. A recommendation titled "revise the
    caption" that goes on to discuss the call to action is about the caption; the
    body mentions the CTA only as context.
    """
    title = _title_of(recommendation)
    text = _text_of(recommendation)
    rec_type = str(recommendation.get("recommendation_type") or "")

    for pattern, type_key in _HUMAN_SIGNALS:
        if re.search(pattern, text):
            return type_key, None

    if rec_type != "revise_copy":
        for scope in (title, text):
            for pattern, type_key in _RENDER_SIGNALS:
                if re.search(pattern, scope):
                    entry = rt.revision_type(type_key)
                    return type_key, entry.default_field if entry else None

    for scope in (title, text):
        for pattern, (type_key, field_key) in _COPY_SIGNALS:
            if re.search(pattern, scope):
                return type_key, field_key

    if rec_type in _TYPE_TO_COPY_DEFAULT:
        return _TYPE_TO_COPY_DEFAULT[rec_type]
    if rec_type == "manual_review":
        return "unsupported_renderer_feature", None
    return "voice_alignment", None


def proposed_change_by_rules(
    revision_type_key: str,
    recommendation: dict[str, Any],
    config: RenderConfig | None,
) -> dict[str, Any]:
    """The exact deterministic setting change a render recommendation asks for."""
    text = _text_of(recommendation)
    if revision_type_key in {"cta_timing_change", "overlay_timing_change"}:
        seconds = _seconds_in(text)
        return {"cta_appear_at_seconds": seconds} if seconds is not None else {}
    if revision_type_key == "duration_change":
        seconds = _seconds_in(text)
        return {"target_duration_seconds": seconds} if seconds is not None else {}
    if revision_type_key == "clip_remove":
        names = _clip_names_in(text)
        return {"remove_clips": names} if names else {}
    if revision_type_key == "source_asset_replace":
        names = _clip_names_in(text)
        return {"replace_clips": names} if names else {}
    if revision_type_key in {"clip_reorder", "slide_reorder"} and config is not None:
        names = _clip_names_in(text)
        if len(names) >= 2:
            return {"clip_order": names}
    return {}


# --- The gate ---------------------------------------------------------------

def _resolve_field(
    type_entry: rt.RevisionType,
    proposed_field: str | None,
    target: AssetTarget,
) -> str | None:
    """The field this change should land on, given what the renderer supports."""
    candidates: list[str] = []
    if proposed_field and proposed_field in rt.FIELDS:
        candidates.append(proposed_field)
    candidates.extend(f for f in type_entry.fields() if f)
    if type_entry.family == "copy" and not type_entry.default_field:
        # Transformations (shorten, voice alignment) have no home field of their
        # own; fall back to whichever copy field this template really exposes.
        candidates.extend(rt.supported_fields(
            template_id=target.template_id, renderer_module=target.renderer_module
        ))

    seen: set[str] = set()
    ordered = [c for c in candidates if not (c in seen or seen.add(c))]
    for candidate in ordered:
        support = rt.renderer_support(
            template_id=target.template_id,
            renderer_module=target.renderer_module,
            field_key=candidate,
            revision_type_key=type_entry.key,
        )
        if support.supported:
            return candidate
    return ordered[0] if ordered else None


def _host_for(
    campaign_dir: Path,
    type_entry: rt.RevisionType,
    proposed_field: str | None,
    target: AssetTarget,
) -> tuple[AssetTarget, str, str] | None:
    """The asset and field that can really host this change, and a note if it moved.

    A review can file a copy note against the wrong piece — an email subject
    against the reel, say — because it is describing the campaign rather than the
    folder layout. When that happens, look for the asset that actually holds that
    copy instead of calling the change manual work.
    """
    candidates: list[AssetTarget] = [target]
    if type_entry.family == "copy":
        candidates.extend(
            other
            for other in list_asset_targets(campaign_dir)
            if other.render_folder != target.render_folder
        )

    for candidate in candidates:
        field_key = _resolve_field(type_entry, proposed_field, candidate)
        if field_key is None:
            continue
        support = rt.renderer_support(
            template_id=candidate.template_id,
            renderer_module=candidate.renderer_module,
            field_key=field_key,
            revision_type_key=type_entry.key,
        )
        if not support.supported:
            continue
        if type_entry.family == "copy":
            config = load_render_config(campaign_dir, candidate)
            if not current_value(campaign_dir, candidate, field_key, config=config).strip():
                continue
        moved = (
            ""
            if candidate.render_folder == target.render_folder
            else (
                f"The recommendation names {target.asset_name}, but the "
                f"{rt.FIELDS[field_key].label.lower()} lives on {candidate.asset_name}, "
                "so BettyOS will revise it there."
            )
        )
        return candidate, field_key, moved
    return None


@dataclass
class ChangeCheck:
    """The outcome of checking a deterministic change against what is on disk.

    The distinction between the two lists is the whole point. `choices` are
    decisions a person makes from values that already exist, so BettyOS is still
    ready to apply the change once one is picked. `blocking` means something
    needed does not exist at all, which is the only honest reason to send a
    render change to Human Input Required.
    """

    change: dict[str, Any]
    choices: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)


def _validate_change(
    revision_type_key: str,
    change: dict[str, Any],
    config: RenderConfig,
    available: list[str],
) -> ChangeCheck:
    """Check a deterministic change against the configuration on disk."""
    resolved = dict(change)
    choices: list[str] = []
    blocking: list[str] = []

    if revision_type_key in {"cta_timing_change", "overlay_timing_change"}:
        seconds = resolved.get("cta_appear_at_seconds")
        if seconds is None or float(seconds) < 0:
            resolved.pop("cta_appear_at_seconds", None)
            choices.append("The second the call to action should appear")

    if revision_type_key == "duration_change":
        seconds = resolved.get("target_duration_seconds")
        if seconds is None or float(seconds) <= 1:
            resolved.pop("target_duration_seconds", None)
            choices.append("The total duration in seconds")

    if revision_type_key in {"clip_remove", "clip_reorder", "source_asset_replace"}:
        present = config.clip_names()
        if not present:
            blocking.append("A render configuration that records which clips were used.")
        key = {
            "clip_remove": "remove_clips",
            "clip_reorder": "clip_order",
            "source_asset_replace": "replace_clips",
        }[revision_type_key]
        named = [str(n).upper() for n in resolved.get(key) or []]
        # Drop names the recommendation invented; the interface offers the real ones.
        recognised = [n for n in named if any(n in p.upper() for p in present)]
        if recognised != named:
            resolved[key] = recognised

        if revision_type_key == "clip_remove":
            if not recognised:
                choices.append("Which clip to remove")
            elif len(present) - len(recognised) < 1:
                resolved[key] = []
                choices.append("Which clip to remove, leaving at least one in the reel")
        elif revision_type_key == "clip_reorder":
            if len(recognised) < 2:
                resolved[key] = []
                choices.append("The order the clips should play in")
        else:
            if not recognised:
                choices.append("Which clip to replace")
            replacement = str(resolved.get("replacement_asset") or "")
            if replacement and replacement not in available:
                resolved.pop("replacement_asset", None)
                replacement = ""
            if not replacement:
                if available:
                    choices.append("Which existing source asset to use instead")
                else:
                    blocking.append("A source asset in the library to use instead.")

    return ChangeCheck(resolved, choices, blocking)


def _gate(
    *,
    recommendation: dict[str, Any],
    revision_type_key: str,
    proposed_field: str | None,
    confidence: float,
    rationale: str,
    proposed_change: dict[str, Any],
    campaign_dir: Path,
    target: AssetTarget | None,
    source: str,
) -> Classification:
    """Turn a proposed reading into a capability BettyOS can stand behind."""
    rec_id = str(recommendation.get("recommendation_id") or "")
    stamp = fingerprint(recommendation)
    asset_label = str(recommendation.get("affected_asset") or "this asset")

    type_entry = rt.revision_type(revision_type_key)
    if type_entry is None:
        revision_type_key, proposed_field = classify_by_rules(recommendation)
        type_entry = rt.revision_type(revision_type_key) or rt.TYPES["unsupported_renderer_feature"]

    def human(
        type_key: str, reason: str, *, missing: list[str] | None = None
    ) -> Classification:
        requirement = rt.requirement_for(type_key, reason=reason)
        return Classification(
            recommendation_id=rec_id,
            capability=rt.HUMAN_INPUT_REQUIRED,
            revision_type=type_key,
            target_field=proposed_field,
            confidence=confidence,
            rationale=reason,
            required_inputs=list(requirement.specifics),
            missing_inputs=missing or list(requirement.specifics),
            supported_actions=list(rt.HUMAN_ACTIONS) if requirement.action else [],
            asset_id=target.asset_id if target else None,
            asset_name=target.asset_name if target else asset_label,
            render_version_id=target.render_version_id if target else None,
            requirement={
                "headline": requirement.headline,
                "specifics": list(requirement.specifics),
                "action": requirement.action,
                "unlocks": requirement.unlocks,
                "accepts": list(requirement.accepts),
            },
            source=source,
            fingerprint=stamp,
        )

    if type_entry.family == "human":
        return human(type_entry.key, type_entry.requirement or rationale)

    if target is None:
        return human(
            "unsupported_renderer_feature",
            f"BettyOS could not find a render for {asset_label} in this campaign, so there "
            "is nothing to revise yet.",
            missing=[f"A rendered version of {asset_label}."],
        )

    host = _host_for(campaign_dir, type_entry, proposed_field, target)
    if host is None:
        fallback_field = _resolve_field(type_entry, proposed_field, target)
        support = rt.renderer_support(
            template_id=target.template_id,
            renderer_module=target.renderer_module,
            field_key=fallback_field or "",
            revision_type_key=type_entry.key,
        )
        if not support.supported and support.reason:
            return human("unsupported_renderer_feature", support.reason)
        label = (
            rt.FIELDS[fallback_field].label.lower()
            if fallback_field in rt.FIELDS
            else "copy this change would rewrite"
        )
        return human(
            "unsupported_renderer_feature",
            f"Nothing in this campaign holds the {label} yet, so there is nothing to revise.",
            missing=[f"Existing {label} on an asset in this campaign."],
        )

    target, field_key, moved_note = host
    config = load_render_config(campaign_dir, target)
    original = current_value(campaign_dir, target, field_key, config=config)
    revision_field = rt.FIELDS[field_key]

    def explain(default: str) -> str:
        return " ".join(part for part in (moved_note, rationale or default) if part)

    if type_entry.family == "copy":
        return Classification(
            recommendation_id=rec_id,
            capability=rt.AI_ASSISTED,
            revision_type=type_entry.key,
            target_field=field_key,
            confidence=confidence,
            rationale=explain(
                f"The {revision_field.label.lower()} already exists and the "
                f"{target.asset_name} renderer accepts revised wording, so BettyOS can "
                "propose replacements for you to approve."
            ),
            required_inputs=[],
            missing_inputs=[],
            supported_actions=list(rt.GENERATE_ACTIONS),
            asset_id=target.asset_id,
            asset_name=target.asset_name,
            render_version_id=target.render_version_id,
            original_value=original,
            default_instruction=default_instruction(
                recommendation, type_entry, revision_field
            ),
            source=source,
            fingerprint=stamp,
        )

    proposed = proposed_change or proposed_change_by_rules(
        type_entry.key, recommendation, config
    )
    check = _validate_change(
        type_entry.key, proposed, config, available_source_assets(campaign_dir)
    )
    if check.blocking:
        return human(
            "unsupported_renderer_feature",
            f"BettyOS can make this kind of change to {target.asset_name}, but something "
            "it needs is not there yet.",
            missing=check.blocking,
        )

    if check.choices:
        settled = (
            f"BettyOS can apply this to {target.asset_name} directly. The recommendation "
            "does not say exactly what to change it to, so confirm the value below."
        )
    else:
        settled = (
            f"This is a single setting on {target.asset_name} that the renderer reads "
            "directly, so BettyOS can apply it without any creative judgement."
        )

    return Classification(
        recommendation_id=rec_id,
        capability=rt.READY_TO_APPLY,
        revision_type=type_entry.key,
        target_field=field_key,
        confidence=confidence,
        rationale=explain(settled),
        required_inputs=list(check.choices),
        missing_inputs=[],
        supported_actions=list(rt.DETERMINISTIC_ACTIONS),
        asset_id=target.asset_id,
        asset_name=target.asset_name,
        render_version_id=target.render_version_id,
        original_value=original,
        default_instruction=default_instruction(recommendation, type_entry, revision_field),
        proposed_change=check.change,
        source=source,
        fingerprint=stamp,
    )


def default_instruction(
    recommendation: dict[str, Any],
    type_entry: rt.RevisionType,
    revision_field: rt.RevisionField,
) -> str:
    """The editable instruction BettyOS proposes before generating anything."""
    expected = str(recommendation.get("expected_changes") or "").strip()
    if type_entry.instruction_hint:
        base = type_entry.instruction_hint
    elif expected:
        base = expected
    else:
        base = f"Revise the {revision_field.label.lower()} as the recommendation describes."
    if type_entry.default_field is None and revision_field.key:
        return f"{base} Apply this to the {revision_field.label.lower()}."
    return base


# --- The model pass ---------------------------------------------------------

_INSTRUCTIONS = """
You are classifying creative-review recommendations for a production system.

For each recommendation decide which of three capability levels it belongs to:

READY_TO_APPLY — one concrete setting change with no creative judgement, and the
recommendation already states the exact new value.
AI_ASSISTED — a writing change. A language model can propose replacement wording
from the Brand Guide and campaign context for a person to approve. Any rewrite of
on-screen copy, captions, calls to action, email copy, Pinterest metadata or
product copy belongs here. Never call a writing change human work.
HUMAN_INPUT_REQUIRED — the change needs a source asset that does not exist, new
photography or footage, physical production, or a capability the renderers listed
below do not have.

Read the recommendation in context. Do not classify from single keywords: a
recommendation that mentions a clip may still be a copy rewrite, and one that
mentions copy may still need footage that does not exist.

Choose revision_type from exactly this list:
COPY: hook_rewrite, supporting_copy_rewrite, cta_rewrite, caption_rewrite,
email_rewrite, pinterest_metadata_rewrite, product_copy_rewrite, shorten_copy,
expand_copy, voice_alignment, clarity_improvement, emotional_specificity,
seo_keyword_revision
RENDER: overlay_timing_change, cta_timing_change, clip_reorder, clip_remove,
source_asset_replace, duration_change, font_size_change, text_position_change,
crop_change, transition_change, slide_reorder
HUMAN: new_photography, new_video_footage, product_reshoot, new_physical_asset,
missing_logo_file, missing_product_image, packaging_redesign,
unsupported_renderer_feature

Choose target_field from exactly this list, or null:
overlay_hook, overlay_supporting, overlay_cta, instagram_caption,
pinterest_caption, pinterest_title, pinterest_description, pinterest_cta,
email_subject, email_preview, email_body, email_cta, product_copy, cta_timing,
overlay_timing, clip_list, duration, slide_order

For a RENDER type, put the exact new value in proposed_change using one of:
{"cta_appear_at_seconds": 9.0} | {"target_duration_seconds": 14.0} |
{"remove_clips": ["IMG_2549"]} | {"clip_order": ["IMG_2545", "IMG_2547"]} |
{"replace_clips": ["IMG_2549"], "replacement_asset": "assets/.../IMG_2551.mov"}
Leave proposed_change as {} for copy and human types.

rationale is one or two sentences explaining the capability decision to the
person reading it. Write it for them, not about the schema.

Return ONLY valid JSON (no markdown fences, no preamble):

{"classifications": [
  {"recommendation_id": "...", "capability": "AI_ASSISTED",
   "revision_type": "supporting_copy_rewrite", "target_field": "overlay_supporting",
   "confidence": 0.94, "rationale": "...", "required_inputs": [], "missing_inputs": [],
   "proposed_change": {}}
]}
""".strip()


def _context_block(
    campaign_dir: Path,
    recommendation: dict[str, Any],
    target: AssetTarget | None,
) -> str:
    lines = [
        f"### Recommendation {recommendation.get('recommendation_id')}",
        f"Title: {recommendation.get('title')}",
        f"Category: {recommendation.get('recommendation_type')}",
        f"Affected asset (as written): {recommendation.get('affected_asset')}",
        f"Instruction: {recommendation.get('full_instruction')}",
        f"Expected changes: {recommendation.get('expected_changes') or 'not stated'}",
    ]
    if target is None:
        lines.append(
            "Resolved asset: none — no render folder in this campaign matches this asset."
        )
        return "\n".join(lines)

    config = load_render_config(campaign_dir, target)
    lines.extend(
        [
            f"Resolved asset: {target.asset_name} (template `{target.template_id}`, "
            f"current version v{target.current_version})",
            f"Render configuration source: {config.source}",
            f"Current clips: {', '.join(config.clip_names()) or 'none recorded'}",
            f"Current duration: {config.target_duration_seconds or 'not set'} seconds",
            f"Current CTA appears at: {config.cta_appear_at_seconds or 'not set'} seconds",
            f"Platform: {platform_for(target, 'overlay_supporting')}",
            "Current copy on this asset:",
        ]
    )
    for field_key in (
        "overlay_hook",
        "overlay_supporting",
        "overlay_cta",
        "instagram_caption",
        "pinterest_caption",
        "pinterest_description",
        "email_subject",
        "email_body",
    ):
        value = current_value(campaign_dir, target, field_key, config=config)
        if value.strip():
            trimmed = value.strip().replace("\n", " ")
            if len(trimmed) > 320:
                trimmed = trimmed[:317] + "…"
            lines.append(f"  - {rt.FIELDS[field_key].label}: {trimmed}")
    lines.append("What this template's renderer can and cannot change:")
    for label, note in renderer_capabilities(target).items():
        lines.append(f"  - {label}: {note}")
    return "\n".join(lines)


def build_prompt(
    campaign_dir: Path,
    recommendations: list[dict[str, Any]],
    *,
    brand_guide: str,
    objective: str,
    targets: dict[str, AssetTarget | None],
) -> str:
    blocks = [
        _context_block(campaign_dir, rec, targets.get(str(rec.get("recommendation_id"))))
        for rec in recommendations
    ]
    return "\n\n".join(
        [
            _INSTRUCTIONS,
            "## Campaign objective",
            objective,
            "## Brand Guide",
            brand_guide.strip(),
            "## Source assets already available",
            "\n".join(f"- {path}" for path in available_source_assets(campaign_dir)[:40])
            or "- none indexed",
            "## Recommendations to classify",
            *blocks,
        ]
    )


# --- Public API -------------------------------------------------------------

def classify(
    *,
    campaign_dir: Path,
    recommendations: list[dict[str, Any]],
    brand_guide: str | None = None,
    objective: str | None = None,
    use_model: bool = True,
    api_key: str | None = None,
) -> dict[str, Classification]:
    """Classify recommendations. Falls back to rules if the model is unavailable."""
    if not recommendations:
        return {}

    targets: dict[str, AssetTarget | None] = {}
    for rec in recommendations:
        rec_id = str(rec.get("recommendation_id") or "")
        targets[rec_id] = resolve_asset(
            campaign_dir,
            affected_asset=str(rec.get("affected_asset") or ""),
            affected_files=[str(f) for f in rec.get("affected_files") or []],
        )

    model_readings: dict[str, dict[str, Any]] = {}
    if use_model:
        try:
            from src.brand import load_brand_brain

            prompt = build_prompt(
                campaign_dir,
                recommendations,
                brand_guide=brand_guide if brand_guide is not None else load_brand_brain(),
                objective=objective or campaign_objective(),
                targets=targets,
            )
            payload = complete_json(prompt, key=api_key, max_tokens=3000)
            items = payload.get("classifications") if isinstance(payload, dict) else payload
            for item in items or []:
                if isinstance(item, dict) and item.get("recommendation_id"):
                    model_readings[str(item["recommendation_id"])] = item
        except Exception:  # noqa: BLE001 — the rule classifier covers every failure
            model_readings = {}

    results: dict[str, Classification] = {}
    for rec in recommendations:
        rec_id = str(rec.get("recommendation_id") or "")
        reading = model_readings.get(rec_id)
        if reading:
            type_key = str(reading.get("revision_type") or "")
            field_key = reading.get("target_field") or None
            try:
                confidence = float(reading.get("confidence") or 0.8)
            except (TypeError, ValueError):
                confidence = 0.8
            rationale = str(reading.get("rationale") or "").strip()
            change = reading.get("proposed_change")
            source = "model"
        else:
            type_key, field_key = classify_by_rules(rec)
            confidence = 0.6
            rationale = ""
            change = None
            source = "rules"

        results[rec_id] = _gate(
            recommendation=rec,
            revision_type_key=type_key,
            proposed_field=str(field_key) if field_key else None,
            confidence=max(0.0, min(1.0, confidence)),
            rationale=rationale,
            proposed_change=dict(change) if isinstance(change, dict) else {},
            campaign_dir=campaign_dir,
            target=targets.get(rec_id),
            source=source,
        )
    return results


# --- Cache ------------------------------------------------------------------

def classifications_path(campaign_dir: Path) -> Path:
    return revisions_dir(campaign_dir) / CLASSIFICATIONS_FILE


def load_classifications(campaign_dir: Path) -> dict[str, Classification]:
    data = load_json(classifications_path(campaign_dir), default=None)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Classification] = {}
    for rec_id, raw in (data.get("classifications") or {}).items():
        if isinstance(raw, dict):
            out[str(rec_id)] = Classification.from_dict({**raw, "recommendation_id": rec_id})
    return out


def save_classifications(campaign_dir: Path, results: dict[str, Classification]) -> Path:
    path = classifications_path(campaign_dir)
    atomic_write_json(
        path,
        {
            "campaign_id": campaign_dir.name,
            "updated_at": _now(),
            "classifications": {
                rec_id: result.to_dict() for rec_id, result in sorted(results.items())
            },
        },
    )
    return path


def ensure_classifications(
    *,
    campaign_dir: Path,
    recommendations: list[dict[str, Any]],
    use_model: bool = True,
    force: bool = False,
) -> tuple[dict[str, Classification], int]:
    """Cached classifications, classifying only what is new or has been edited.

    Returns the results and how many were freshly classified, so the interface
    can say whether anything actually happened.
    """
    stored = {} if force else load_classifications(campaign_dir)
    pending = [
        rec
        for rec in recommendations
        if force
        or str(rec.get("recommendation_id") or "") not in stored
        or stored[str(rec.get("recommendation_id"))].fingerprint != fingerprint(rec)
    ]
    if not pending:
        return stored, 0

    fresh = classify(
        campaign_dir=campaign_dir, recommendations=pending, use_model=use_model
    )
    merged = {**stored, **fresh}
    save_classifications(campaign_dir, merged)
    return merged, len(fresh)


def reclassify_one(
    *,
    campaign_dir: Path,
    recommendation: dict[str, Any],
    use_model: bool = True,
) -> Classification:
    fresh = classify(
        campaign_dir=campaign_dir, recommendations=[recommendation], use_model=use_model
    )
    rec_id = str(recommendation.get("recommendation_id") or "")
    stored = load_classifications(campaign_dir)
    stored.update(fresh)
    save_classifications(campaign_dir, stored)
    return fresh[rec_id]
