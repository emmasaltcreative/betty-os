"""Review Brain — Creative Director critique of BettyOS outputs.

Critique only. Does not rewrite captions, scripts, or regenerate content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from review.recommendations import (
    ensure_three_improvements,
    format_improvements_markdown,
    format_recommendations_markdown,
    structure_improvements,
)
from review.scoring import SCORE_LABELS, ReviewResult, parse_review_payload

MODEL = "claude-sonnet-4-6"

REVIEW_INSTRUCTIONS = """
You are an experienced Creative Director reviewing work before approval.

This is a CRITIQUE step — not a rewrite. Do not rewrite captions, scripts, hooks, or CTAs.
Do not regenerate content. Do not invent new pieces. Only evaluate what was provided.

Review philosophy — ask yourself:
- Does this feel unmistakably like the brand?
- Does this create desire instead of explaining?
- Is the emotion specific?
- Is anything generic?
- Is the CTA earned?
- Would a founder actually publish this?

Score each dimension from 0–10 (decimals allowed, e.g. 8.5):
1. brand_alignment
2. business_alignment
3. emotional_specificity
4. editorial_quality
5. visual_consistency
6. conversion_potential
7. overall_readiness

For EVERY score, write a short critique reason (2–4 sentences). Do not merely justify the number — actually critique the work. Name what is working and what is weak.

If rendered video / render settings are present, also inspect:
- opening hook
- pacing
- text timing
- visual hierarchy
- CTA timing
- editorial polish

After scoring, return ONLY the three improvements that would create the biggest overall lift.
Prioritize impact. Do not list tiny polish notes.

Also return the same three as structured recommendation objects. Preserve the full written
recommendation text in full_instruction. Use recommendation_type from:
replace_asset, remove_asset, revise_copy, change_timing, change_duration, change_cta,
rerender, manual_review.

Return ONLY valid JSON (no markdown fences, no preamble) matching:

{
  "scores": {
    "brand_alignment": {"score": 0.0, "reason": "..."},
    "business_alignment": {"score": 0.0, "reason": "..."},
    "emotional_specificity": {"score": 0.0, "reason": "..."},
    "editorial_quality": {"score": 0.0, "reason": "..."},
    "visual_consistency": {"score": 0.0, "reason": "..."},
    "conversion_potential": {"score": 0.0, "reason": "..."},
    "overall_readiness": {"score": 0.0, "reason": "..."}
  },
  "highest_impact_improvements": [
    "First highest-impact improvement",
    "Second highest-impact improvement",
    "Third highest-impact improvement"
  ],
  "recommendations": [
    {
      "title": "Short action title",
      "full_instruction": "Full original written recommendation",
      "rationale": "Why this matters",
      "affected_asset": "Ritual Reel",
      "affected_files": ["ritual_reel/ritual_reel_draft.mp4"],
      "recommendation_type": "remove_asset",
      "priority": "high",
      "expected_changes": "What should change in the next version"
    }
  ]
}
""".strip()


def format_review_markdown(
    result: ReviewResult,
    *,
    campaign_goal: str,
    package_name: str,
    render_names: list[str],
) -> str:
    """Render a professional creative review document."""
    lines: list[str] = [
        "# Creative Review",
        "",
        f"**Campaign goal:** {campaign_goal.strip()}",
        f"**Content package:** `{package_name}`",
    ]
    if render_names:
        lines.append("**Renders reviewed:** " + ", ".join(f"`{n}`" for n in render_names))
    else:
        lines.append("**Renders reviewed:** none present")
    lines.extend(["", "---", ""])

    overall = result.overall_readiness
    lines.extend(
        [
            "## Overall Readiness",
            "",
            f"**{overall.score:.1f} / 10**",
            "",
            overall.reason,
            "",
        ]
    )

    for key in (
        "brand_alignment",
        "business_alignment",
        "emotional_specificity",
        "editorial_quality",
        "visual_consistency",
        "conversion_potential",
    ):
        item = getattr(result, key)
        lines.extend(
            [
                f"## {SCORE_LABELS[key]}",
                "",
                f"**{item.score:.1f}**",
                "",
                "### Reason",
                "",
                item.reason,
                "",
            ]
        )

    if result.recommendations:
        lines.append(format_recommendations_markdown(result.recommendations))
    else:
        lines.append(format_improvements_markdown(result.highest_impact_improvements))
    return "\n".join(lines).rstrip() + "\n"


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Review response did not contain a JSON object.")
    return json.loads(cleaned[start : end + 1])


def build_review_prompt(
    *,
    brand_brain: str,
    production_brain: str,
    content_package: str,
    campaign_goal: str,
    render_context: str,
) -> str:
    parts = [
        REVIEW_INSTRUCTIONS,
        "",
        "## Campaign Goal",
        campaign_goal.strip(),
        "",
        "## Brand Brain",
        brand_brain.strip(),
        "",
        "## Production Brain",
        production_brain.strip(),
        "",
        "## Latest Content Package",
        content_package.strip(),
        "",
        "## Latest Render Outputs",
        render_context.strip() or "No render outputs present.",
    ]
    return "\n".join(parts)


def call_review_model(prompt: str, api_key: str, image_blocks: list[dict[str, Any]] | None = None) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    content: list[dict[str, Any]] = []
    if image_blocks:
        content.extend(image_blocks)
    content.append({"type": "text", "text": prompt})
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )
    chunks: list[str] = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def run_creative_review(
    *,
    brand_brain: str,
    production_brain: str,
    content_package: str,
    campaign_goal: str,
    render_context: str,
    api_key: str,
    outputs_dir: Path,
    package_name: str,
    render_names: list[str],
    image_blocks: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, ReviewResult]:
    """Run critique, write latest_review.md and latest_scores.json, return paths + result."""
    prompt = build_review_prompt(
        brand_brain=brand_brain,
        production_brain=production_brain,
        content_package=content_package,
        campaign_goal=campaign_goal,
        render_context=render_context,
    )
    raw = call_review_model(prompt, api_key, image_blocks=image_blocks)
    if not raw:
        raise RuntimeError("Review Brain returned an empty response.")

    try:
        payload = extract_json_object(raw)
        result = parse_review_payload(payload)
        result.highest_impact_improvements = ensure_three_improvements(
            result.highest_impact_improvements
        )
        if not result.recommendations:
            result.recommendations = structure_improvements(
                result.highest_impact_improvements
            )
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise RuntimeError(f"Could not parse Review Brain response: {exc}") from exc

    outputs_dir.mkdir(parents=True, exist_ok=True)
    review_path = outputs_dir / "latest_review.md"
    scores_path = outputs_dir / "latest_scores.json"

    review_path.write_text(
        format_review_markdown(
            result,
            campaign_goal=campaign_goal,
            package_name=package_name,
            render_names=render_names,
        ),
        encoding="utf-8",
    )
    scores_payload = {
        "campaign_goal": campaign_goal,
        "content_package": package_name,
        "renders": render_names,
        **result.scores_dict(),
    }
    scores_path.write_text(json.dumps(scores_payload, indent=2) + "\n", encoding="utf-8")
    return review_path, scores_path, result
