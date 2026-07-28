"""Turning an approved revision into a new render version.

Three rules govern everything here:

1. The original is never written to. A revision adds a version beside the one it
   came from and leaves that version's file, caption and settings snapshot alone.
2. Only the field that was revised changes. The new configuration starts from the
   configuration that produced the current version, so clips, timing and the copy
   nobody asked about all carry over untouched.
3. The new version arrives as `awaiting_review`, so Approvals is still the place
   a person signs it off.

The configuration used for each version is written to
`outputs/<campaign>/revisions/render_configs/<asset>_v<n>.json` and is not
rewritten afterwards, so the next revision has an accurate account of what the
current version actually is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from services import revision_store as store
from services import revision_types as rt
from services.copy_documents import CopyDocument
from services.revision_context import (
    AssetTarget,
    RenderConfig,
    current_value,
    load_render_config,
    platform_for,
    render_configs_dir,
    resolve_asset,
    template_constraints,
)
from services.revision_validation import REJECTED, Verdict, validate_option
from src.common import OUTPUTS_DIR, ROOT, BettyOSError
from src.persistence import atomic_write_json, atomic_write_text

OVERLAY_FIELDS = {
    "overlay_hook": "hook",
    "overlay_supporting": "supporting",
    "overlay_cta": "cta",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _display_path(path: Path) -> str:
    """A path worth showing: project-relative when it can be, absolute when not."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


class RevisionApplyError(BettyOSError):
    """The revision could not be applied, with a reason worth showing."""


# --- Resolving the request --------------------------------------------------

@dataclass
class Plan:
    """Everything needed to apply one revision, resolved and checked."""

    request: dict[str, Any]
    target: AssetTarget
    config: RenderConfig
    field_key: str
    field_label: str
    before: str
    after: str
    from_version: int
    to_version: int
    requires_rerender: bool
    change_rows: list[tuple[str, str, str]]
    validation: Verdict | None = None

    @property
    def is_copy(self) -> bool:
        revision_field = rt.field_for(self.field_key)
        return bool(revision_field and revision_field.is_copy)


def _version_stem(render_dir: Path, target: AssetTarget) -> str:
    """The naming already in use in this folder, so versions stay consistent."""
    from review.versioning import load_versions

    for entry in reversed(load_versions(render_dir).get("versions") or []):
        name = str(entry.get("filename") or "")
        if "_v" in name:
            return name.rsplit("_v", 1)[0]
    for path in sorted(render_dir.glob("*_v*.mp4")):
        return path.name.rsplit("_v", 1)[0]
    return target.template_id if target.renderer_module != "video" else render_dir.name


def _next_version(target: AssetTarget) -> int:
    if target.renderer_module == "video":
        from review.versioning import next_version_number

        return int(next_version_number(target.render_folder))
    from renderers.primitives import next_output_version

    suffix = "md" if target.renderer_module == "copy" else "png"
    return int(next_output_version(target.render_folder, target.template_id, suffix))


def _describe_seconds(value: Any) -> str:
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return "not set"


def _apply_change_to_config(
    config: RenderConfig, revision_type_key: str, change: dict[str, Any]
) -> tuple[RenderConfig, list[tuple[str, str, str]]]:
    """The new configuration, and the exact settings that differ."""
    rows: list[tuple[str, str, str]] = []
    clips = [dict(clip) for clip in config.clips]
    duration = config.target_duration_seconds
    cta_at = config.cta_appear_at_seconds

    if revision_type_key in {"cta_timing_change", "overlay_timing_change"}:
        wanted = change.get("cta_appear_at_seconds")
        if wanted is None:
            raise RevisionApplyError("This revision does not say when the CTA should appear.")
        rows.append(
            ("Call to action appears", _describe_seconds(cta_at), _describe_seconds(wanted))
        )
        cta_at = float(wanted)

    if revision_type_key == "duration_change":
        wanted = change.get("target_duration_seconds")
        if wanted is None:
            raise RevisionApplyError("This revision does not say what the duration should be.")
        rows.append(("Total duration", _describe_seconds(duration), _describe_seconds(wanted)))
        duration = float(wanted)
        if clips:
            per_clip = duration / len(clips)
            for clip in clips:
                clip["target_duration_seconds"] = round(per_clip, 3)

    if revision_type_key == "clip_remove":
        remove = [str(name).upper() for name in change.get("remove_clips") or []]
        kept = [
            clip
            for clip in clips
            if not any(name in str(clip.get("relative_path", "")).upper() for name in remove)
        ]
        if not kept:
            raise RevisionApplyError("Removing those clips would leave the reel with nothing in it.")
        rows.append(
            (
                "Source clips",
                ", ".join(Path(str(c.get("relative_path"))).name for c in clips),
                ", ".join(Path(str(c.get("relative_path"))).name for c in kept),
            )
        )
        clips = kept
        if duration:
            per_clip = float(duration) / len(clips)
            for clip in clips:
                clip["target_duration_seconds"] = round(per_clip, 3)

    if revision_type_key in {"clip_reorder", "slide_reorder"}:
        wanted = [str(name).upper() for name in change.get("clip_order") or []]
        if not wanted:
            raise RevisionApplyError("This revision does not say what the new order should be.")
        ordered: list[dict[str, Any]] = []
        for name in wanted:
            for clip in clips:
                if name in str(clip.get("relative_path", "")).upper() and clip not in ordered:
                    ordered.append(clip)
        ordered.extend(clip for clip in clips if clip not in ordered)
        rows.append(
            (
                "Clip order",
                ", ".join(Path(str(c.get("relative_path"))).name for c in clips),
                ", ".join(Path(str(c.get("relative_path"))).name for c in ordered),
            )
        )
        clips = ordered

    if revision_type_key == "source_asset_replace":
        replace = [str(name).upper() for name in change.get("replace_clips") or []]
        replacement = str(change.get("replacement_asset") or "")
        if not replacement:
            raise RevisionApplyError("This revision does not name a replacement asset.")
        if not (ROOT / replacement).exists():
            raise RevisionApplyError(f"The replacement asset is not on disk: {replacement}")
        swapped: list[dict[str, Any]] = []
        for clip in clips:
            path = str(clip.get("relative_path", ""))
            if any(name in path.upper() for name in replace):
                swapped.append({**clip, "relative_path": replacement})
            else:
                swapped.append(clip)
        rows.append(
            (
                "Source clips",
                ", ".join(Path(str(c.get("relative_path"))).name for c in clips),
                ", ".join(Path(str(c.get("relative_path"))).name for c in swapped),
            )
        )
        clips = swapped

    new_config = RenderConfig(
        template_id=config.template_id,
        render_folder=config.render_folder,
        based_on_version=config.based_on_version,
        overlay_copy=dict(config.overlay_copy),
        clips=clips,
        target_duration_seconds=duration,
        cta_appear_at_seconds=cta_at,
        source=config.source,
    )
    return new_config, rows


def build_plan(campaign_dir: Path, request: dict[str, Any]) -> Plan:
    """Resolve a request into a checked, applyable plan. Raises if it cannot be."""
    field_key = str(request.get("target_field") or "")
    revision_field = rt.field_for(field_key)
    if revision_field is None:
        raise RevisionApplyError("This revision has no field to write into.")

    target = resolve_asset(
        campaign_dir,
        affected_asset=str(request.get("affected_asset_name") or ""),
        affected_files=[str(request.get("affected_asset_id") or "")],
    )
    if target is None:
        raise RevisionApplyError(
            f"BettyOS could not find {request.get('affected_asset_name') or 'that asset'} "
            "in this campaign any more."
        )

    support = rt.renderer_support(
        template_id=target.template_id,
        renderer_module=target.renderer_module,
        field_key=field_key,
        revision_type_key=str(request.get("revision_type") or ""),
    )
    if not support.supported:
        raise RevisionApplyError(support.reason)

    config = load_render_config(campaign_dir, target)
    before = current_value(campaign_dir, target, field_key, config=config)
    to_version = _next_version(target)
    revision_type_key = str(request.get("revision_type") or "")

    if revision_field.is_copy:
        after = store.selected_value(request)
        if not after.strip():
            raise RevisionApplyError("No option has been selected for this revision yet.")
        constraints = template_constraints(target, field_key)
        validation = validate_option(
            after,
            option_id=str(request.get("selected_option_id") or "edited"),
            original_value=before,
            max_words=constraints.get("max_words"),
            max_chars=constraints.get("max_chars"),
            platform=platform_for(target, field_key),
        )
        if validation.verdict == REJECTED:
            reasons = "; ".join(issue.message for issue in validation.issues)
            raise RevisionApplyError(
                f"This wording did not pass the brand checks, so it cannot be applied: {reasons}"
            )
        return Plan(
            request=request,
            target=target,
            config=config,
            field_key=field_key,
            field_label=revision_field.label,
            before=before,
            after=after,
            from_version=target.current_version,
            to_version=to_version,
            requires_rerender=support.requires_rerender,
            change_rows=[(revision_field.label, before, after)],
            validation=validation,
        )

    change = dict(request.get("proposed_change") or {})
    new_config, rows = _apply_change_to_config(config, revision_type_key, change)
    if not rows:
        raise RevisionApplyError("This revision does not describe a setting change to make.")
    return Plan(
        request=request,
        target=target,
        config=new_config,
        field_key=field_key,
        field_label=revision_field.label,
        before=" · ".join(row[1] for row in rows),
        after=" · ".join(row[2] for row in rows),
        from_version=target.current_version,
        to_version=to_version,
        requires_rerender=True,
        change_rows=rows,
    )


def preview(campaign_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
    """Before and after, for the comparison shown before approval. Never raises."""
    try:
        plan = build_plan(campaign_dir, request)
    except BettyOSError as exc:
        return {"ok": False, "reason": exc.message}
    return {
        "ok": True,
        "asset_name": plan.target.asset_name,
        "template_id": plan.target.template_id,
        "field_label": plan.field_label,
        "before": plan.before,
        "after": plan.after,
        "change_rows": plan.change_rows,
        "from_version": plan.from_version,
        "to_version": plan.to_version,
        "requires_rerender": plan.requires_rerender,
        "is_copy": plan.is_copy,
        "validation": plan.validation.to_dict() if plan.validation else None,
    }


# --- The configuration snapshot ---------------------------------------------

def write_config_snapshot(
    campaign_dir: Path,
    plan: Plan,
    *,
    overlay_copy: dict[str, Any],
    outputs: list[str],
) -> Path:
    """An immutable record of the configuration this version was built from."""
    folder = render_configs_dir(campaign_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{plan.target.asset_id}_v{plan.to_version}.json"
    if path.exists():
        raise RevisionApplyError(
            f"A configuration snapshot for version {plan.to_version} already exists. "
            "Nothing was overwritten."
        )
    atomic_write_json(
        path,
        {
            "campaign_id": campaign_dir.name,
            "asset_id": plan.target.asset_id,
            "asset_name": plan.target.asset_name,
            "template_id": plan.target.template_id,
            "version": plan.to_version,
            "parent_version": plan.from_version,
            "based_on_version": plan.config.based_on_version,
            "created_at": _now(),
            "review_status": "awaiting_review",
            "revision_request_ids": [str(plan.request.get("revision_request_id"))],
            "recommendation_ids": [str(plan.request.get("recommendation_id"))],
            "revision_type": plan.request.get("revision_type"),
            "revised_field": plan.field_key,
            "overlay_copy": overlay_copy,
            "clips": [dict(clip) for clip in plan.config.clips],
            "target_duration_seconds": plan.config.target_duration_seconds,
            "cta_appear_at_seconds": plan.config.cta_appear_at_seconds,
            "outputs": outputs,
        },
    )
    return path


# --- Execution --------------------------------------------------------------

def _render_video_version(campaign_dir: Path, plan: Plan) -> tuple[list[str], dict[str, Any]]:
    """Build a new reel version. The existing versions are left in place."""
    from main import run_create_ritual_reel
    from review.versioning import ensure_baseline_version

    if plan.target.template_id != "cinematic_multi_clip_reel":
        raise RevisionApplyError(
            f"No renderer can build a revised version of {plan.target.asset_name}."
        )

    render_dir = plan.target.render_folder
    ensure_baseline_version(render_dir)
    stem = _version_stem(render_dir, plan.target)
    video_name = f"{stem}_v{plan.to_version}.mp4"

    overlay_copy = dict(plan.config.overlay_copy)
    caption_override: str | None = None
    caption_filename: str | None = None

    overlay_key = OVERLAY_FIELDS.get(plan.field_key)
    if overlay_key == "cta":
        overlay_copy["cta"] = plan.after.strip()
    elif overlay_key:
        lines = [line.strip() for line in plan.after.splitlines() if line.strip()]
        overlay_copy[overlay_key] = lines or [plan.after.strip()]
    elif plan.is_copy:
        caption_override, caption_filename = _revised_copy_document(plan)

    sources = [
        {
            "relative_path": str(clip.get("relative_path")),
            "target_duration_seconds": clip.get("target_duration_seconds"),
        }
        for clip in plan.config.clips
        if clip.get("relative_path")
    ]
    source_overrides = [
        {k: v for k, v in clip.items() if v is not None} for clip in sources
    ] or None

    run_create_ritual_reel(
        out_dir=render_dir,
        source_overrides=source_overrides,
        target_duration_seconds=plan.config.target_duration_seconds,
        cta_appear_at_seconds=plan.config.cta_appear_at_seconds,
        caption_override=caption_override,
        overlay_copy_overrides=overlay_copy,
        output_filename=video_name,
        caption_filename=caption_filename,
        preserve_existing=True,
        versioning={
            "version": plan.to_version,
            "parent_version": plan.from_version,
            "revision_request_ids": [str(plan.request.get("revision_request_id"))],
            "addressed_recommendation_ids": [str(plan.request.get("recommendation_id"))],
        },
    )

    produced = [video_name]
    if caption_filename:
        produced.append(caption_filename)
    return produced, overlay_copy


def _revised_copy_document(plan: Plan) -> tuple[str, str]:
    """The whole copy document with one field replaced, and the name to save it as."""
    source = plan.target.copy_path
    if source is None or not source.is_file():
        raise RevisionApplyError(
            f"BettyOS could not find the copy document for {plan.target.asset_name}."
        )
    document = CopyDocument.load(source)
    revised = document.replaced(plan.field_key, plan.after)
    if revised == document.text:
        raise RevisionApplyError(
            f"The {plan.field_label.lower()} in {source.name} did not change. Nothing was written."
        )
    stem = source.name.rsplit("_v", 1)[0] if "_v" in source.name else source.stem
    return revised, f"{stem}_v{plan.to_version}.md"


def _write_copy_version(campaign_dir: Path, plan: Plan) -> list[str]:
    """A new versioned copy document for a copy-family template."""
    from renderers.primitives import write_render_manifest

    revised, filename = _revised_copy_document(plan)
    output = plan.target.render_folder / filename
    if output.exists():
        raise RevisionApplyError(f"{filename} already exists. Nothing was overwritten.")
    atomic_write_text(output, revised if revised.endswith("\n") else revised + "\n")
    write_render_manifest(
        plan.target.render_folder,
        template_id=plan.target.template_id,
        content_piece_id=plan.target.piece_id or plan.target.asset_id,
        version=plan.to_version,
        outputs=[filename],
        source_assets=[],
        config={
            "revision_request_id": str(plan.request.get("revision_request_id")),
            "revision_type": plan.request.get("revision_type"),
            "revised_field": plan.field_key,
        },
        parent_version=plan.from_version or None,
    )
    return [filename]


def apply_revision(campaign_dir: Path, request_id: str) -> dict[str, Any]:
    """Apply one selected revision as a new version. Records its own failures."""
    request = store.get_request(campaign_dir, request_id)
    if request is None:
        raise RevisionApplyError(f"Revision request {request_id} is not in this campaign.")
    if str(request.get("status")) == store.APPLIED:
        return {
            "ok": True,
            "already_applied": True,
            "version": request.get("resulting_render_version_id"),
        }

    try:
        plan = build_plan(campaign_dir, request)
    except BettyOSError as exc:
        store.update_request(
            campaign_dir, request_id, status=store.FAILED, failure_reason=exc.message
        )
        return {"ok": False, "failure_reason": exc.message}

    store.update_request(campaign_dir, request_id, status=store.APPROVED_TO_APPLY)
    store.update_request(campaign_dir, request_id, status=store.APPLYING)

    try:
        if plan.target.renderer_module == "video":
            outputs, overlay_copy = _render_video_version(campaign_dir, plan)
        elif plan.target.renderer_module == "copy":
            outputs = _write_copy_version(campaign_dir, plan)
            overlay_copy = dict(plan.config.overlay_copy)
        else:
            raise RevisionApplyError(
                f"BettyOS has no renderer that can produce a revised "
                f"{plan.target.asset_name}."
            )

        from review.versioning import register_version

        register_version(
            plan.target.render_folder,
            version=plan.to_version,
            filename=outputs[0],
            parent_version=plan.from_version,
            revision_request_ids=[str(request_id)],
            addressed_recommendation_ids=[str(request.get("recommendation_id"))],
            review_status="awaiting_review",
        )
        snapshot = write_config_snapshot(
            campaign_dir, plan, overlay_copy=overlay_copy, outputs=outputs
        )
    except Exception as exc:  # noqa: BLE001 — every failure is recorded, then reported
        reason = getattr(exc, "message", None) or str(exc)
        store.update_request(
            campaign_dir, request_id, status=store.FAILED, failure_reason=reason
        )
        return {"ok": False, "failure_reason": reason}

    version_id = f"v{plan.to_version:03d}"
    store.update_request(
        campaign_dir,
        request_id,
        status=store.APPLIED,
        resulting_render_version_id=version_id,
        applied_at=_now(),
        failure_reason=None,
    )
    _mark_recommendation_completed(str(request.get("recommendation_id")))

    return {
        "ok": True,
        "version": version_id,
        "version_number": plan.to_version,
        "parent_version": plan.from_version,
        "asset_name": plan.target.asset_name,
        "outputs": [_display_path(plan.target.render_folder / name) for name in outputs],
        "config_snapshot": _display_path(snapshot),
        "review_status": "awaiting_review",
    }


def _mark_recommendation_completed(recommendation_id: str) -> None:
    """Keep the review in step, so an applied recommendation stops asking to be done."""
    path = OUTPUTS_DIR / "latest_scores.json"
    if not recommendation_id or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict) or not isinstance(data.get("recommendations"), list):
        return
    changed = False
    for item in data["recommendations"]:
        if isinstance(item, dict) and str(item.get("recommendation_id")) == recommendation_id:
            item["status"] = "completed"
            changed = True
    if changed:
        atomic_write_json(path, data)
