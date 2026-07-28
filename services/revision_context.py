"""What is true about a campaign right now.

The classifier and the revision service both need the same picture: which asset
a recommendation points at, what its copy currently says, what its render
configuration currently is, which source assets exist, and what the renderer
could do about it. Gathering that in one read-only place keeps the two services
honest about the same facts.

Nothing here writes to disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services import revision_types as rt
from services.copy_documents import CopyDocument
from src.common import ASSETS_PATH, OUTPUTS_DIR, PRODUCTION_DIR, ROOT
from src.templates.registry import (
    LEGACY_FOLDER_TO_TEMPLATE,
    TEMPLATE_TO_LEGACY_FOLDER,
    templates_by_id,
)

REVISIONS_DIRNAME = "revisions"
RENDER_CONFIGS_DIRNAME = "render_configs"
UPLOADS_DIRNAME = "uploads"

# Names the review model uses for the two video pieces, mapped to their
# canonical template. Reviews say "Ritual Reel"; the registry says
# "Cinematic Multi-Clip Reel"; the folder on disk may be either.
DISPLAY_ALIASES: dict[str, str] = {
    "ritual reel": "cinematic_multi_clip_reel",
    "the ritual reel": "cinematic_multi_clip_reel",
    "cinematic multi-clip reel": "cinematic_multi_clip_reel",
    "page turn loop": "single_clip_atmospheric_loop",
    "the page turn loop": "single_clip_atmospheric_loop",
    "single-clip atmospheric loop": "single_clip_atmospheric_loop",
}

_TEMPLATE_CONFIG_FILE: dict[str, Path] = {
    "cinematic_multi_clip_reel": PRODUCTION_DIR / "templates" / "ritual_reel.json",
    "single_clip_atmospheric_loop": PRODUCTION_DIR / "templates" / "page_turn_loop.json",
}

MEDIA_SUFFIXES = {".mp4", ".mov", ".png", ".jpg", ".jpeg"}


def revisions_dir(campaign_dir: Path) -> Path:
    return campaign_dir / REVISIONS_DIRNAME


def render_configs_dir(campaign_dir: Path) -> Path:
    return revisions_dir(campaign_dir) / RENDER_CONFIGS_DIRNAME


def uploads_dir(campaign_dir: Path) -> Path:
    return revisions_dir(campaign_dir) / UPLOADS_DIRNAME


# --- The asset a recommendation points at -----------------------------------

@dataclass
class AssetTarget:
    """One revisable output in a campaign."""

    asset_id: str  # folder name, e.g. "ritual_reel"
    asset_name: str  # what a person calls it, e.g. "Ritual Reel"
    template_id: str
    renderer_module: str
    render_folder: Path
    piece_id: str | None = None
    current_version: int = 1
    copy_path: Path | None = None

    @property
    def render_version_id(self) -> str:
        return f"v{self.current_version:03d}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _highest_version(folder: Path, pattern: str) -> int:
    highest = 0
    for path in folder.glob(pattern):
        digits = "".join(ch for ch in path.stem.rsplit("_v", 1)[-1] if ch.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return highest


def _current_version(render_folder: Path) -> int:
    from review.versioning import load_versions

    data = load_versions(render_folder)
    current = int(data.get("current_version") or 0)
    if current:
        return current
    for pattern in ("*_v*.mp4", "*_v*.png", "*_v*.md"):
        found = _highest_version(render_folder, pattern)
        if found:
            return found
    return 1


def _copy_path_for(render_folder: Path) -> Path | None:
    caption = render_folder / "caption.md"
    if caption.is_file():
        return caption
    drafts = sorted(render_folder.glob("*_v*.md"))
    return drafts[-1] if drafts else None


def _folder_display_name(folder_name: str, template_id: str) -> str:
    template = templates_by_id().get(template_id)
    if template:
        return template.display_name
    return folder_name.replace("_", " ").title()


def _has_media(folder: Path) -> bool:
    return any(
        p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES for p in folder.rglob("*")
    )


def render_folder_pairs(campaign_dir: Path) -> list[tuple[str, Path]]:
    """Canonical (template_id, folder) pairs, hiding migration duplicates.

    This deliberately reproduces the rule in `ui.campaign_state._render_folders`.
    A revision has to land in the folder the interface shows, or a new version
    would be written somewhere nobody looks.
    """
    present = {
        p.name
        for p in campaign_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != REVISIONS_DIRNAME
    }
    pairs: list[tuple[str, Path]] = []
    for name in sorted(present):
        template_id = LEGACY_FOLDER_TO_TEMPLATE.get(name, name)
        legacy_twin = TEMPLATE_TO_LEGACY_FOLDER.get(template_id)
        is_legacy = name != template_id
        if is_legacy and template_id in present:
            continue
        if not is_legacy and legacy_twin and legacy_twin in present:
            canonical_dir = campaign_dir / name
            if not _has_media(canonical_dir) and _has_media(campaign_dir / legacy_twin):
                pairs.append((template_id, campaign_dir / legacy_twin))
                continue
        pairs.append((template_id, campaign_dir / name))
    return pairs


def list_asset_targets(campaign_dir: Path) -> list[AssetTarget]:
    """Every render folder in the campaign that a revision could touch."""
    if not campaign_dir.is_dir():
        return []
    registry = templates_by_id()
    targets: list[AssetTarget] = []

    for template_id, folder in render_folder_pairs(campaign_dir):
        template = registry.get(template_id)
        if template is None:
            continue
        piece_dirs = [
            p for p in sorted(folder.iterdir()) if p.is_dir() and p.name.startswith("piece_")
        ]
        for output_dir in piece_dirs or [folder]:
            # One template can render several content pieces into their own
            # folders, so the asset id has to name the piece as well.
            asset_id = (
                folder.name if output_dir == folder else f"{folder.name}__{output_dir.name}"
            )
            targets.append(
                AssetTarget(
                    asset_id=asset_id,
                    asset_name=_folder_display_name(folder.name, template_id),
                    template_id=template_id,
                    renderer_module=template.renderer_module,
                    render_folder=output_dir,
                    piece_id=output_dir.name if output_dir != folder else None,
                    current_version=_current_version(output_dir),
                    copy_path=_copy_path_for(output_dir),
                )
            )
    return targets


def resolve_asset(
    campaign_dir: Path,
    *,
    affected_asset: str,
    affected_files: list[str] | None = None,
) -> AssetTarget | None:
    """Find the render folder a recommendation is talking about."""
    targets = list_asset_targets(campaign_dir)
    if not targets:
        return None

    def identities(target: AssetTarget) -> set[str]:
        folder_name = target.render_folder.name
        top_folder = target.asset_id.split("__", 1)[0]
        return {
            target.asset_id,
            top_folder,
            folder_name,
            target.template_id,
            LEGACY_FOLDER_TO_TEMPLATE.get(top_folder, top_folder),
            TEMPLATE_TO_LEGACY_FOLDER.get(target.template_id, target.template_id),
            target.asset_name.lower(),
        }

    # A named file is the strongest signal — it says which folder outright.
    for relative in affected_files or []:
        head = str(relative).replace("\\", "/").split("/")[0]
        canonical = LEGACY_FOLDER_TO_TEMPLATE.get(head, head)
        for target in targets:
            if head in identities(target) or canonical in identities(target):
                return target

    wanted = str(affected_asset or "").strip().lower()
    if not wanted:
        return None
    alias = DISPLAY_ALIASES.get(wanted)
    for target in targets:
        if alias and alias in identities(target):
            return target
        if wanted in identities(target):
            return target
    for target in targets:
        if wanted in target.asset_name.lower():
            return target
    return None


# --- The render configuration currently in force ----------------------------

@dataclass
class RenderConfig:
    """The configuration that produced the current version of an asset."""

    template_id: str
    render_folder: Path
    based_on_version: int
    overlay_copy: dict[str, Any] = field(default_factory=dict)
    clips: list[dict[str, Any]] = field(default_factory=list)
    target_duration_seconds: float | None = None
    cta_appear_at_seconds: float | None = None
    source: str = ""

    def clip_names(self) -> list[str]:
        return [Path(str(c.get("relative_path") or "")).name for c in self.clips]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "based_on_version": self.based_on_version,
            "overlay_copy": dict(self.overlay_copy),
            "clips": [dict(c) for c in self.clips],
            "target_duration_seconds": self.target_duration_seconds,
            "cta_appear_at_seconds": self.cta_appear_at_seconds,
            "source": self.source,
        }


def _overlay_from_template(template: dict[str, Any]) -> dict[str, Any]:
    hook = (template.get("hook") or {}).get("lines") or []
    supporting = (template.get("supporting") or {}).get("lines") or []
    cta = (template.get("cta") or {}).get("text") or ""
    return {
        "hook": [str(line) for line in hook],
        "supporting": [str(line) for line in supporting],
        "cta": str(cta),
    }


def latest_config_snapshot(campaign_dir: Path, asset_id: str) -> tuple[Path | None, dict[str, Any]]:
    """The newest immutable revision config snapshot written for an asset."""
    folder = render_configs_dir(campaign_dir)
    if not folder.is_dir():
        return None, {}
    best: tuple[int, Path] | None = None
    for path in folder.glob(f"{asset_id}_v*.json"):
        digits = "".join(ch for ch in path.stem.rsplit("_v", 1)[-1] if ch.isdigit())
        if not digits:
            continue
        number = int(digits)
        if best is None or number > best[0]:
            best = (number, path)
    if best is None:
        return None, {}
    return best[1], _load_json(best[1])


def load_render_config(campaign_dir: Path, target: AssetTarget) -> RenderConfig:
    """The live configuration for an asset, newest source of truth first.

    A previously applied revision is the most current description of the asset,
    so its snapshot wins over the render settings written at first render, which
    in turn win over the shared template file under `production/`.
    """
    snapshot_path, snapshot = latest_config_snapshot(campaign_dir, target.asset_id)
    if snapshot:
        return RenderConfig(
            template_id=target.template_id,
            render_folder=target.render_folder,
            based_on_version=int(snapshot.get("version") or target.current_version),
            overlay_copy=dict(snapshot.get("overlay_copy") or {}),
            clips=[dict(c) for c in snapshot.get("clips") or []],
            target_duration_seconds=snapshot.get("target_duration_seconds"),
            cta_appear_at_seconds=snapshot.get("cta_appear_at_seconds"),
            source=snapshot_path.name if snapshot_path else "revision snapshot",
        )

    def version_of(path: Path) -> int:
        digits = "".join(ch for ch in path.stem.rsplit("_v", 1)[-1] if ch.isdigit())
        return int(digits) if digits else 0

    versioned = sorted(target.render_folder.glob("render_settings_v*.json"), key=version_of)
    settings_path = versioned[-1] if versioned else target.render_folder / "render_settings.json"
    settings = _load_json(settings_path)
    if settings:
        template = (settings.get("production") or {}).get("template") or {}
        resolved = settings.get("resolved") or {}
        clips = [
            {
                "relative_path": str(entry.get("relative_path")),
                "target_duration_seconds": entry.get("target_duration_seconds"),
            }
            for entry in template.get("sources") or []
            if entry.get("relative_path")
        ]
        if not clips:
            clips = [
                {"relative_path": str(c.get("path")), "target_duration_seconds": None}
                for c in settings.get("clips") or []
                if c.get("path")
            ]
        return RenderConfig(
            template_id=target.template_id,
            render_folder=target.render_folder,
            based_on_version=target.current_version,
            overlay_copy=_overlay_from_template(template),
            clips=clips,
            target_duration_seconds=(
                float(template["target_duration_seconds"])
                if template.get("target_duration_seconds") is not None
                else None
            ),
            cta_appear_at_seconds=(
                float(resolved["cta_appear_at_seconds"])
                if resolved.get("cta_appear_at_seconds") is not None
                else None
            ),
            source=settings_path.name,
        )

    template_path = _TEMPLATE_CONFIG_FILE.get(target.template_id)
    template = _load_json(template_path) if template_path else {}
    return RenderConfig(
        template_id=target.template_id,
        render_folder=target.render_folder,
        based_on_version=target.current_version,
        overlay_copy=_overlay_from_template(template),
        clips=[dict(entry) for entry in template.get("sources") or []],
        target_duration_seconds=template.get("target_duration_seconds"),
        cta_appear_at_seconds=None,
        source=template_path.name if template_path else "template defaults",
    )


# --- Current value of a field -----------------------------------------------

_OVERLAY_FIELDS = {
    "overlay_hook": "hook",
    "overlay_supporting": "supporting",
    "overlay_cta": "cta",
}


def current_value(
    campaign_dir: Path,
    target: AssetTarget,
    field_key: str,
    *,
    config: RenderConfig | None = None,
) -> str:
    """What this field says today, as text a person would recognise."""
    config = config or load_render_config(campaign_dir, target)

    overlay_key = _OVERLAY_FIELDS.get(field_key)
    if overlay_key:
        value = config.overlay_copy.get(overlay_key)
        if isinstance(value, list):
            return " ".join(str(line).strip() for line in value if str(line).strip())
        return str(value or "")

    if field_key == "cta_timing":
        return (
            f"{config.cta_appear_at_seconds:.1f}s"
            if config.cta_appear_at_seconds is not None
            else "not set"
        )
    if field_key == "duration":
        return (
            f"{config.target_duration_seconds:.0f}s"
            if config.target_duration_seconds is not None
            else "not set"
        )
    if field_key in {"clip_list", "slide_order"}:
        return ", ".join(config.clip_names()) or "no clips recorded"

    if target.copy_path and target.copy_path.is_file():
        value = CopyDocument.load(target.copy_path).read(field_key)
        if value:
            return value
    return ""


def copy_fields_available(target: AssetTarget) -> list[str]:
    if not target.copy_path or not target.copy_path.is_file():
        return []
    return CopyDocument.load(target.copy_path).fields_present()


# --- Source assets ----------------------------------------------------------

def available_source_assets(campaign_dir: Path | None = None) -> list[str]:
    """Media BettyOS can already use, as root-relative paths."""
    found: list[str] = []
    indexed = _load_json(ASSETS_PATH)
    for key in sorted(indexed):
        if (ROOT / key).exists():
            found.append(str(key))
    media_dir = ROOT / "assets"
    if media_dir.is_dir():
        for path in sorted(media_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
                relative = path.relative_to(ROOT).as_posix()
                if relative not in found:
                    found.append(relative)
    if campaign_dir is not None:
        folder = uploads_dir(campaign_dir)
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
                    found.append(path.relative_to(ROOT).as_posix())
    return found


# --- Campaign framing -------------------------------------------------------

def campaign_objective() -> str:
    scores = _load_json(OUTPUTS_DIR / "latest_scores.json")
    goal = str(scores.get("campaign_goal") or "").strip()
    if goal:
        return goal
    from src.common import find_latest_content_package
    from src.package_parse import extract_campaign_goal

    try:
        package = find_latest_content_package()
    except Exception:  # noqa: BLE001 — an absent package is not an error here
        return "Not specified"
    return extract_campaign_goal(package.read_text(encoding="utf-8")) or "Not specified"


def platform_for(target: AssetTarget, field_key: str) -> str:
    """The platform whose limits this field has to respect."""
    if field_key.startswith("pinterest"):
        return "pinterest"
    if field_key.startswith("email"):
        return "email"
    if field_key.startswith("overlay") and target.template_id == "cinematic_multi_clip_reel":
        return "instagram_reel"
    registry = templates_by_id()
    template = registry.get(target.template_id)
    platforms = list(template.supported_platforms) if template else []
    return str(platforms[0]) if platforms else "instagram"


def protected_fields(target: AssetTarget, field_key: str) -> list[str]:
    """Values a rewrite must not touch, named so the prompt can protect them."""
    protected = [
        "Brand name: Oh Betty Jaletti",
        "Product name: First Edition: The Reading Hour",
        "Footer branding lines",
    ]
    if field_key != "overlay_cta":
        protected.append("On-screen call to action")
    if field_key != "overlay_hook":
        protected.append("On-screen hook")
    if field_key != "overlay_supporting":
        protected.append("On-screen supporting copy")
    if not field_key.startswith("email"):
        protected.append("Email subject and preview text")
    return protected


def template_constraints(target: AssetTarget, field_key: str) -> dict[str, Any]:
    """Length and format limits, taken from production config and the field table."""
    defaults = _load_json(PRODUCTION_DIR / "global_defaults.json")
    revision_field = rt.field_for(field_key)
    max_words = revision_field.max_words if revision_field else None
    if field_key.startswith("overlay"):
        screen_max = defaults.get("maximum_words_per_screen")
        if screen_max is not None:
            max_words = min(int(screen_max), max_words or int(screen_max))
    return {
        "field": revision_field.label if revision_field else field_key,
        "max_words": max_words,
        "max_chars": revision_field.max_chars if revision_field else None,
        "platform": platform_for(target, field_key),
        "voice": "Betty",
        "template": target.template_id,
    }


def renderer_capabilities(target: AssetTarget) -> dict[str, str]:
    return rt.capability_summary(
        template_id=target.template_id, renderer_module=target.renderer_module
    )
