"""Brand Brain loader — shared by plan, repurpose, and review."""

from __future__ import annotations

from src.common import BRANDS_DIR, DEFAULT_BRAND_ID, BettyOSError

BRAND_BRAIN_FILES = (
    "identity.md",
    "audience.md",
    "products.md",
    "voice.md",
    "visual_language.md",
    "business_strategy.md",
    "creative_principles.md",
)


def load_brand_brain(brand_id: str = DEFAULT_BRAND_ID) -> str:
    """Load brands/<brand_id>/*.md in fixed order into one prompt-ready string."""
    brand_dir = BRANDS_DIR / brand_id
    if not brand_dir.is_dir():
        raise BettyOSError(
            f"Brand Brain not found: brands/{brand_id}/",
            hint="Expected markdown files under brands/<brand_id>/.",
        )

    sections: list[str] = [
        f"Brand Brain (loaded from brands/{brand_id}/)",
        "Use this as operating guidance. Do not invent positioning, products, "
        "pricing, claims, or brand history beyond what is stated here.",
    ]
    missing: list[str] = []
    for name in BRAND_BRAIN_FILES:
        path = brand_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)

    if missing:
        raise BettyOSError(
            f"Brand Brain incomplete for {brand_id}: " + ", ".join(missing),
            hint=f"Add the missing files under brands/{brand_id}/.",
        )
    if len(sections) <= 2:
        raise BettyOSError(
            f"Brand Brain is empty: brands/{brand_id}/",
            hint="Each Brand Brain markdown file should contain operating guidance.",
        )

    return "\n\n".join(sections)
