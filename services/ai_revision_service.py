"""The AI Revision Service.

Given one field's current wording and the recommendation about it, propose two
to five replacements with a short reason for each. Structured data only — the
interface never has to read prose out of a model reply.

What this service will not do: invent a product claim, touch a field it was not
asked about, exceed the platform or on-screen limits, or return a single option
and call it a decision. Those are enforced here on the way out, and again in
`services.revision_validation` before anything is shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services import revision_types as rt
from services.llm import GenerationError, complete_json

MIN_OPTIONS = 2
MAX_OPTIONS = 5


@dataclass
class RevisionOption:
    option_id: str
    text: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {"option_id": self.option_id, "text": self.text, "rationale": self.rationale}


@dataclass
class RevisionProposal:
    """The result of one generation request."""

    revision_request_id: str
    revision_type: str
    original_value: str
    options: list[RevisionOption] = field(default_factory=list)
    constraints_used: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "revision_request_id": self.revision_request_id,
            "revision_type": self.revision_type,
            "original_value": self.original_value,
            "options": [option.to_dict() for option in self.options],
            "constraints_used": dict(self.constraints_used),
        }
        if not self.ok:
            payload["failure_reason"] = self.failure_reason
        return payload


_INSTRUCTIONS = """
You are writing replacement copy for a small independent brand, working from its
Brand Guide. You are not writing marketing copy. You are finding the one true
sentence the brand would have written itself.

Rules, in order of importance:

1. Write only the field you were asked to write. Do not rewrite anything else,
   do not add a call to action that was not there, do not add hashtags or emoji
   that were not there.
2. Never state a product claim, material, price, dimension, date, quantity or
   availability that is not already in the Brand Guide or the original copy.
3. Never claim the founder makes, sews, pours, packs or ships anything.
4. Stay inside the length limits exactly. They are hard limits, not targets.
5. Invite, never pressure. No scarcity, no countdowns, no "don't miss out".
6. No generic lifestyle-brand language: no "elevate your routine", "self-care
   essentials", "vibes", "must-have", "cozy season", "game-changer".
7. Each option must be a genuinely different approach, not a reworded twin.
   Name a specific observed detail rather than a general feeling.
8. Do not repeat the original wording back as an option.
9. Do not use em dashes by default. Prefer periods, commas, colons,
   parentheses, or separate sentences. Avoid decorative or habitual em dashes.
   Never use multiple em dashes in one short piece of copy. An em dash may be
   used only when it materially improves hook visibility, reading rhythm,
   emotional emphasis, scanability, or conversion clarity. If you use one,
   say that benefit in the rationale.

Give each option a rationale of one short sentence saying what it does
differently. Write the rationale for the person choosing between them.

Return ONLY valid JSON (no markdown fences, no preamble):

{"options": [{"text": "...", "rationale": "..."}]}
""".strip()


def _limits_block(constraints: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    max_words = constraints.get("max_words")
    max_chars = constraints.get("max_chars")
    if max_words:
        lines.append(f"- Hard maximum: {int(max_words)} words.")
    if max_chars:
        lines.append(f"- Hard maximum: {int(max_chars)} characters.")
    platform = constraints.get("platform")
    if platform:
        lines.append(f"- Platform: {platform}. Respect how copy is read there.")
    voice = constraints.get("voice")
    if voice:
        lines.append(f"- Voice: {voice}, exactly as the Brand Guide describes it.")
    return lines or ["- No explicit limit; keep it short and specific."]


def build_prompt(
    *,
    original_content: str,
    recommendation: str,
    instruction: str,
    revision_type: str,
    field_label: str,
    brand_guide: str,
    campaign_brief: str,
    campaign_objective: str,
    platform: str,
    template_constraints: dict[str, Any],
    protected_fields: list[str],
    option_count: int,
    avoid: list[str],
    similar_to: str | None,
) -> str:
    parts = [
        _INSTRUCTIONS,
        "",
        f"## What to write: {field_label}",
        f"Revision type: {rt.type_label(revision_type)} (`{revision_type}`)",
        f"Number of options to return: exactly {option_count}.",
        "",
        "## Constraints",
        *_limits_block({**template_constraints, "platform": platform}),
        "",
        "## Fields you must not change",
        *([f"- {name}" for name in protected_fields] or ["- none"]),
        "",
        "## Current wording of this field",
        original_content.strip() or "(empty)",
        "",
        # The instruction is what the person actually asked for. It comes first,
        # and it wins where it and the review disagree.
        "## The instruction to follow — this takes precedence",
        instruction.strip() or recommendation.strip() or "Improve this copy.",
        "",
        "## The creative review this came from, for background",
        recommendation.strip() or "No written critique recorded.",
        "",
        "## Campaign objective",
        campaign_objective.strip() or "Not specified",
    ]
    if campaign_brief.strip():
        parts.extend(["", "## Campaign brief", campaign_brief.strip()[:4000]])
    if avoid:
        parts.extend(
            [
                "",
                "## Wording already proposed — do not repeat or lightly reword these",
                *[f"- {text}" for text in avoid[:12]],
            ]
        )
    if similar_to:
        parts.extend(
            [
                "",
                "## Take this direction further",
                similar_to.strip(),
                "Keep what makes this work and vary the image, rhythm or entry point. "
                "Do not drift to a different idea.",
            ]
        )
    parts.extend(["", "## Brand Guide", brand_guide.strip()])
    return "\n".join(parts)


def generate_options(
    *,
    revision_request_id: str,
    original_content: str,
    recommendation: str,
    revision_type: str,
    brand_guide: str,
    campaign_brief: str = "",
    campaign_objective: str = "",
    platform: str = "instagram",
    template_constraints: dict[str, Any] | None = None,
    protected_fields: list[str] | None = None,
    instruction: str = "",
    option_count: int = 3,
    avoid: list[str] | None = None,
    similar_to: str | None = None,
    api_key: str | None = None,
) -> RevisionProposal:
    """Propose replacements for one field. Never raises — failures come back in the result."""
    constraints = dict(template_constraints or {})
    field_key = str(constraints.get("field_key") or "")
    revision_field = rt.field_for(field_key)
    field_label = str(constraints.get("field") or (revision_field.label if revision_field else "copy"))
    wanted = max(MIN_OPTIONS, min(MAX_OPTIONS, int(option_count)))
    constraints_used = {
        "max_words": constraints.get("max_words"),
        "max_chars": constraints.get("max_chars"),
        "platform": platform,
        "voice": constraints.get("voice") or "Betty",
        "field": field_label,
        "protected_fields": list(protected_fields or []),
        "options_requested": wanted,
    }

    proposal = RevisionProposal(
        revision_request_id=revision_request_id,
        revision_type=revision_type,
        original_value=original_content,
        constraints_used=constraints_used,
    )

    if not original_content.strip():
        proposal.ok = False
        proposal.failure_reason = (
            f"There is no {field_label.lower()} on this asset yet, so there is nothing to revise."
        )
        return proposal

    prompt = build_prompt(
        original_content=original_content,
        recommendation=recommendation,
        instruction=instruction,
        revision_type=revision_type,
        field_label=field_label,
        brand_guide=brand_guide,
        campaign_brief=campaign_brief,
        campaign_objective=campaign_objective,
        platform=platform,
        template_constraints=constraints,
        protected_fields=list(protected_fields or []),
        option_count=wanted,
        avoid=list(avoid or []),
        similar_to=similar_to,
    )

    try:
        payload = complete_json(prompt, key=api_key, max_tokens=2000, temperature=1.0)
    except GenerationError as exc:
        proposal.ok = False
        proposal.failure_reason = exc.message
        return proposal

    raw = payload.get("options") if isinstance(payload, dict) else payload
    if not isinstance(raw, list) or not raw:
        proposal.ok = False
        proposal.failure_reason = "The model did not return any options."
        return proposal

    start = int(constraints.get("option_start_index") or 1)
    seen: set[str] = {original_content.strip().lower()}
    seen.update(text.strip().lower() for text in avoid or [])
    options: list[RevisionOption] = []
    for entry in raw:
        text = ""
        rationale = ""
        if isinstance(entry, str):
            text = entry.strip()
        elif isinstance(entry, dict):
            text = str(entry.get("text") or entry.get("option") or "").strip()
            rationale = str(entry.get("rationale") or entry.get("reason") or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        options.append(
            RevisionOption(
                option_id=f"option_{start + len(options):03d}",
                text=text,
                rationale=rationale or "No reason given.",
            )
        )
        if len(options) >= MAX_OPTIONS:
            break

    if len(options) < MIN_OPTIONS:
        proposal.ok = False
        proposal.failure_reason = (
            "The model returned fewer than two usable options. Try generating again."
        )
        proposal.options = options
        return proposal

    proposal.options = options
    return proposal
