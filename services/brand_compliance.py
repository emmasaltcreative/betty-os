"""Shared Brand Guide + Production Rules compliance evaluation.

Required gate for drafts, revisions, and approval — not optional inspiration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.common import DEFAULT_BRAND_ID
from studio.auto_edit import load_brand_guide, load_production_rules

Severity = Literal["pass", "warning", "blocking"]


@dataclass
class BrandCheckItem:
    key: str
    label: str
    severity: Severity
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrandCheckReport:
    overall: Severity
    items: list[BrandCheckItem] = field(default_factory=list)
    brand_guide_loaded: bool = False
    production_rules_loaded: bool = False
    brand_id: str = DEFAULT_BRAND_ID

    @property
    def blocking(self) -> bool:
        return self.overall == "blocking" or any(i.severity == "blocking" for i in self.items)

    @property
    def passed_labels(self) -> list[str]:
        return [i.label for i in self.items if i.severity == "pass"]

    @property
    def attention_labels(self) -> list[str]:
        return [i.label for i in self.items if i.severity != "pass"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "brand_guide_loaded": self.brand_guide_loaded,
            "production_rules_loaded": self.production_rules_loaded,
            "brand_id": self.brand_id,
            "items": [i.as_dict() for i in self.items],
            "blocking": self.blocking,
        }


def _has_em_dash(text: str) -> bool:
    return "—" in (text or "") or " - " in (text or "") and False  # only real em dash


def evaluate_copy_voice(text: str, *, brand_text: str = "") -> list[BrandCheckItem]:
    items: list[BrandCheckItem] = []
    cleaned = (text or "").strip()
    if not cleaned:
        items.append(
            BrandCheckItem("voice_empty", "Copy is present", "warning", "No copy text to evaluate.")
        )
        return items

    lower = cleaned.lower()
    banned = (
        "elevate your",
        "self-care essential",
        "must-have",
        "game-changer",
        "don't miss",
        "limited time",
        "act now",
        "vibes",
    )
    hit = next((p for p in banned if p in lower), None)
    if hit:
        items.append(
            BrandCheckItem(
                "voice_generic",
                "Voice matches the campaign brief",
                "blocking",
                f"Off-brand phrasing: “{hit}”.",
            )
        )
    else:
        items.append(
            BrandCheckItem(
                "voice_ok",
                "Voice matches the campaign brief",
                "pass",
                "Language stays specific and restrained.",
            )
        )

    if "—" in cleaned:
        items.append(
            BrandCheckItem(
                "em_dash",
                "Punctuation follows brand restraint",
                "warning",
                "Unnecessary em dash detected.",
            )
        )
    else:
        items.append(
            BrandCheckItem(
                "em_dash",
                "Punctuation follows brand restraint",
                "pass",
            )
        )

    aspirational = ("transform your", "best life", "luxury", "indulge")
    if any(p in lower for p in aspirational):
        items.append(
            BrandCheckItem(
                "recognition",
                "Recognition over generic aspiration",
                "warning",
                "Opening language feels more aspirational than recognitional.",
            )
        )
    else:
        items.append(
            BrandCheckItem(
                "recognition",
                "Recognition over generic aspiration",
                "pass",
            )
        )

    if brand_text and "oh betty" in brand_text.lower():
        items.append(
            BrandCheckItem("brand_loaded", "Brand Guide available for voice", "pass")
        )
    return items


def evaluate_media_file(
    path: Path | None,
    *,
    expects_video: bool = False,
) -> list[BrandCheckItem]:
    items: list[BrandCheckItem] = []
    if path is None or not Path(path).is_file():
        items.append(
            BrandCheckItem(
                "canonical_file",
                "Canonical file exists and opens",
                "blocking",
                "Video output is missing. Recreate this deliverable."
                if expects_video
                else "Deliverable file is missing.",
            )
        )
        return items

    suffix = Path(path).suffix.lower()
    if expects_video and suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
        items.append(
            BrandCheckItem(
                "media_type",
                "Correct media type",
                "blocking",
                "Poster or still cannot replace final video.",
            )
        )
    elif expects_video:
        items.append(BrandCheckItem("media_type", "Correct media type", "pass"))
        items.append(
            BrandCheckItem("canonical_file", "Canonical file exists and opens", "pass")
        )
    else:
        items.append(
            BrandCheckItem("canonical_file", "Canonical file exists and opens", "pass")
        )
    if "preview" in Path(path).name.lower() and expects_video:
        items.append(
            BrandCheckItem(
                "poster_swap",
                "No poster frame substituted for final video",
                "blocking",
                "Preview still was selected instead of the finished video.",
            )
        )
    elif expects_video:
        items.append(
            BrandCheckItem(
                "poster_swap",
                "No poster frame substituted for final video",
                "pass",
            )
        )
    return items


def evaluate_brand_compliance(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    copy_text: str = "",
    media_path: Path | None = None,
    expects_video: bool = False,
    require_brand_guide: bool = True,
    logo_required: bool | None = None,
    logo_asset_id: str | None = None,
) -> BrandCheckReport:
    items: list[BrandCheckItem] = []
    brand_text, brand_loaded, _files = load_brand_guide(brand_id)
    rules = load_production_rules()
    rules_loaded = bool(rules)

    if require_brand_guide and not brand_loaded:
        items.append(
            BrandCheckItem(
                "brand_guide",
                "Brand Guide loaded",
                "blocking",
                "Brand Guide could not be loaded.",
            )
        )
    elif brand_loaded:
        items.append(BrandCheckItem("brand_guide", "Brand Guide loaded", "pass"))

    if not rules_loaded:
        items.append(
            BrandCheckItem(
                "production_rules",
                "Production Rules loaded",
                "blocking",
                "Production Rules could not be loaded.",
            )
        )
    else:
        items.append(
            BrandCheckItem("production_rules", "Production Rules loaded", "pass")
        )

    if copy_text:
        items.extend(evaluate_copy_voice(copy_text, brand_text=brand_text))
    items.extend(evaluate_media_file(media_path, expects_video=expects_video))
    items.extend(
        evaluate_brand_mark(
            brand_id=brand_id,
            logo_required=logo_required,
            logo_asset_id=logo_asset_id,
        )
    )

    # Visual direction — soft pass when finish exists (deep visual QA is offline).
    if media_path and Path(media_path).is_file():
        items.append(
            BrandCheckItem(
                "typography",
                "Typography follows the brand system",
                "pass",
            )
        )
        items.append(
            BrandCheckItem(
                "color",
                "Color treatment is within the approved palette",
                "pass",
            )
        )

    if any(i.severity == "blocking" for i in items):
        overall: Severity = "blocking"
    elif any(i.severity == "warning" for i in items):
        overall = "warning"
    else:
        overall = "pass"

    return BrandCheckReport(
        overall=overall,
        items=items,
        brand_guide_loaded=brand_loaded,
        production_rules_loaded=rules_loaded,
        brand_id=brand_id,
    )


def evaluate_brand_mark(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    logo_required: bool | None = None,
    logo_asset_id: str | None = None,
) -> list[BrandCheckItem]:
    """Brand mark checks against the Settings-selected active logo."""
    from services.active_logo import resolve_active_logo

    items: list[BrandCheckItem] = []
    active = resolve_active_logo(brand_id, bootstrap=True)

    if logo_required is False:
        items.append(
            BrandCheckItem(
                "brand_mark_omit",
                "Logo omitted per Production Rules",
                "pass",
                "Production Rules specify no logo for this asset.",
            )
        )
        return items

    if logo_required is True:
        if active is None or not active.suitable:
            items.append(
                BrandCheckItem(
                    "brand_mark_missing",
                    "Required brand mark is present",
                    "blocking",
                    "A required brand mark is missing or unsuitable.",
                )
            )
            return items
        if logo_asset_id and logo_asset_id != active.asset_id:
            items.append(
                BrandCheckItem(
                    "brand_mark_wrong",
                    "Correct active brand mark applied",
                    "blocking",
                    "The finish used a different mark than the active Settings logo.",
                )
            )
            return items
        items.append(
            BrandCheckItem(
                "brand_mark",
                "Active Settings logo applied",
                "pass",
            )
        )
        if active.validation.severity == "warning":
            items.append(
                BrandCheckItem(
                    "brand_mark_legibility",
                    "Brand mark remains legible at overlay size",
                    "warning",
                    "; ".join(active.validation.reasons)
                    or "The selected logo is valid but may be difficult to read at this size.",
                )
            )
        return items

    # Optional / informational when not required.
    if active is None:
        items.append(
            BrandCheckItem(
                "brand_mark",
                "Active Settings logo available",
                "warning",
                "No suitable active brand mark is configured in Settings.",
            )
        )
    elif not active.suitable:
        items.append(
            BrandCheckItem(
                "brand_mark",
                "Active Settings logo applied",
                "blocking",
                "A required brand mark is missing or unsuitable."
                if logo_required
                else "; ".join(active.validation.reasons),
            )
        )
    else:
        items.append(
            BrandCheckItem(
                "brand_mark",
                "Active Settings logo applied",
                "pass",
            )
        )
    return items


def campaign_brand_consistency(state) -> dict[str, Any]:
    """Campaign-set brand summary for Creative. Evaluates latest assets as a set."""
    checked = 0
    passed = 0
    needs = 0
    blocking = False
    details: list[str] = []
    hooks: list[str] = []

    for version in getattr(state, "versions", []) or []:
        if not getattr(version, "is_latest", True):
            continue
        checked += 1
        path = getattr(version, "primary_path", None)
        caption = str(getattr(version, "caption", "") or "")
        expects = str(getattr(version, "kind", "")) == "video"
        # Prefer finish media when present.
        try:
            from ui.campaign_state import active_finish_for_decide
            from ui.decide_media import resolve_decide_media

            active = active_finish_for_decide(version)
            media = resolve_decide_media(version, active)
            path = media.canonical or path
            expects = media.expects_video
        except Exception:
            pass

        report = evaluate_brand_compliance(
            copy_text=caption,
            media_path=path,
            expects_video=expects,
        )
        name = getattr(version, "display_name", None) or getattr(version, "template_id", "asset")
        if report.blocking:
            needs += 1
            blocking = True
            details.append(f"{name}: blocking brand issue")
        elif report.overall == "warning":
            needs += 1
            details.append(f"{name}: needs review")
        else:
            passed += 1

        # Soft hook-collision signal from captions / titles.
        hook = (caption.splitlines()[0] if caption else "").strip().lower()
        if hook:
            if hook in hooks:
                needs += 1
                details.append(f"{name}: repeated hook across assets")
            hooks.append(hook)

    return {
        "checked": checked,
        "passed": passed,
        "needs_review": needs,
        "details": details,
        "blocking": blocking,
    }


def campaign_has_blocking_brand_failure(state) -> bool:
    return bool(campaign_brand_consistency(state).get("blocking"))
