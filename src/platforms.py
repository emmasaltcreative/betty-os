"""Canonical campaign-planning platform vocabulary and safe normalization.

Piece records often store geometry-qualified labels such as
``Instagram Reels (9:16)``. Streamlit multiselect widgets only accept values
that appear in their options list. Normalize at the UI/domain boundary —
do not rewrite historical campaign records merely to render a screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

# Display labels shown in campaign-planning multiselects.
PLATFORM_OPTIONS: tuple[str, ...] = (
    "Instagram",
    "Pinterest",
    "TikTok",
    "Email",
    "Waitlist",
    "YouTube Shorts",
)

# Map lowercase aliases / legacy forms → canonical display label.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "instagram": "Instagram",
    "ig": "Instagram",
    "insta": "Instagram",
    "instagram_reels": "Instagram",
    "instagram reels": "Instagram",
    "instagram_feed": "Instagram",
    "instagram feed": "Instagram",
    "instagram stories": "Instagram",
    "instagram_stories": "Instagram",
    "reels": "Instagram",
    "reel": "Instagram",
    "feed": "Instagram",
    "pinterest": "Pinterest",
    "pin": "Pinterest",
    "pins": "Pinterest",
    "tiktok": "TikTok",
    "tik tok": "TikTok",
    "tt": "TikTok",
    "email": "Email",
    "e-mail": "Email",
    "newsletter": "Email",
    "waitlist": "Waitlist",
    "youtube shorts": "YouTube Shorts",
    "youtube_shorts": "YouTube Shorts",
    "youtubeshorts": "YouTube Shorts",
    "yt shorts": "YouTube Shorts",
    "shorts": "YouTube Shorts",
    "youtube": "YouTube Shorts",
}

# In-process diagnostics for unknown legacy values (not a second persistence store).
_UNKNOWN_PLATFORM_DIAGNOSTICS: list[dict[str, str]] = []


@dataclass(frozen=True)
class PlatformNormalizationResult:
    """Normalized multiselect-safe defaults plus unknowns left in history."""

    selected: list[str]
    unknown: list[str] = field(default_factory=list)
    mapped_from: dict[str, str] = field(default_factory=dict)


def canonical_platform(raw: str | None) -> str | None:
    """Map one stored platform string to a canonical option, or None if unknown."""
    text = (raw or "").strip()
    if not text:
        return None

    # Exact canonical match first.
    if text in PLATFORM_OPTIONS:
        return text

    lowered = text.lower().strip()
    if lowered in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[lowered]

    # Strip geometry / parenthetical suffixes: "Instagram Reels (9:16)" → "instagram reels"
    base = lowered
    if "(" in base:
        base = base.split("(", 1)[0].strip()
    if base in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[base]

    # Containment against known option names (longest first to prefer specificity).
    for option in sorted(PLATFORM_OPTIONS, key=len, reverse=True):
        if option.lower() in base or option.lower() in lowered:
            return option

    # Alias token containment (e.g. "instagram_reels_vertical").
    for alias, canonical in sorted(
        _ALIAS_TO_CANONICAL.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if alias in base.replace("-", " ").replace("_", " ") or alias in base:
            return canonical

    return None


def normalize_platforms(
    values: Iterable[str] | None,
    *,
    options: Sequence[str] = PLATFORM_OPTIONS,
    fallback: Sequence[str] | None = None,
    record_unknown: bool = True,
    source: str = "",
) -> PlatformNormalizationResult:
    """Normalize persisted platforms to values present in ``options``.

    Unknown legacy values are excluded from the widget default, recorded in
    diagnostics when ``record_unknown`` is True, and returned in ``unknown``
    so callers can keep historical data intact.
    """
    option_set = list(options)
    option_lookup = {opt: opt for opt in option_set}
    selected: list[str] = []
    unknown: list[str] = []
    mapped_from: dict[str, str] = {}
    seen: set[str] = set()

    for raw in values or []:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if text in option_lookup and text not in seen:
            selected.append(text)
            seen.add(text)
            continue
        canonical = canonical_platform(text)
        if canonical and canonical in option_lookup:
            if canonical not in seen:
                selected.append(canonical)
                seen.add(canonical)
            if text != canonical:
                mapped_from[text] = canonical
            continue
        unknown.append(text)
        if record_unknown:
            _record_unknown(text, source=source)

    if not selected and fallback is not None:
        for item in fallback:
            canonical = canonical_platform(item) or (item if item in option_lookup else None)
            if canonical and canonical in option_lookup and canonical not in seen:
                selected.append(canonical)
                seen.add(canonical)

    # Final guard: never return a value outside options.
    selected = [item for item in selected if item in option_lookup]
    return PlatformNormalizationResult(
        selected=selected,
        unknown=unknown,
        mapped_from=mapped_from,
    )


def multiselect_platform_defaults(
    *candidates: Iterable[str] | None,
    options: Sequence[str] = PLATFORM_OPTIONS,
    fallback: Sequence[str] | None = ("Instagram", "Pinterest"),
    source: str = "multiselect",
) -> list[str]:
    """Pick the first non-empty candidate list, normalize, and guarantee safe defaults.

    Pass candidates in priority order (e.g. campaign state, session, intelligence).
    """
    for candidate in candidates:
        if candidate is None:
            continue
        values = list(candidate)
        if not values:
            continue
        result = normalize_platforms(
            values,
            options=options,
            fallback=None,
            record_unknown=True,
            source=source,
        )
        if result.selected:
            return result.selected

    result = normalize_platforms(
        list(fallback or ()),
        options=options,
        fallback=None,
        record_unknown=False,
        source=source,
    )
    return result.selected


def unknown_platform_diagnostics() -> list[dict[str, str]]:
    """Return a copy of recorded unknown platform diagnostics for this process."""
    return list(_UNKNOWN_PLATFORM_DIAGNOSTICS)


def clear_unknown_platform_diagnostics() -> None:
    _UNKNOWN_PLATFORM_DIAGNOSTICS.clear()


def _record_unknown(value: str, *, source: str) -> None:
    entry = {"value": value, "source": source or "unknown"}
    # Deduplicate identical entries to avoid alarm noise on reruns.
    if entry not in _UNKNOWN_PLATFORM_DIAGNOSTICS:
        _UNKNOWN_PLATFORM_DIAGNOSTICS.append(entry)
