"""Studio — automatic brand-informed finishing engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from src.common import DEFAULT_BRAND_ID
from studio.apply_recipe import apply_recipe_to_config
from studio.brand_assets import (
    ROLE_LABELS,
    default_asset_for_role,
    list_assets,
    resolve_asset_path,
)
from studio.capabilities import load_capabilities
from studio.edit_decision import EditDecision, ExecutionReport
from studio.guardrails import ensure_guardrails, list_guardrails
from studio.luts import list_luts
from studio.models import (
    ASPECT_PRESETS,
    LOGO_PLACEMENTS,
    LOGO_ROLES,
    PLATFORM_EXPORT_PRESETS,
    FinishConfiguration,
    FinishRecord,
)
from studio.package import finished_download_name, mime_for, output_is_downloadable
from studio.paths import preview_cache_dir
from studio.recipes import ensure_default_recipes, get_recipe, list_recipes
from studio.service import (
    create_finish,
    generate_best_edit,
    make_studio_package,
    revise_best_edit,
    run_preview,
    set_finish_approval,
    source_entry_validation,
)
from studio.validation import summarize, validate_config
from studio.versions import (
    config_hash,
    discard_draft,
    draft_id_for,
    list_finish_records,
    load_draft,
    load_finish_config,
    render_version_id,
    resolve_finish_output,
    resolve_finish_preview,
    save_draft,
)
from ui import nav
from ui.campaign_state import CampaignState, PieceState, RenderVersion, count_phrase
from ui.components import (
    blocked_state,
    download_file,
    empty_state,
    key_values,
    note,
    page_header,
    progress_rail,
    quiet,
    saved_note,
    section,
    show_badges,
)
from ui.status import action_status

CONFIG_KEY = "studio_finish_config"
DIRTY_KEY = "studio_dirty"
SOURCE_KEY = "studio_source_key"
PREVIEW_KEY = "studio_preview_path"
SAVE_STATUS_KEY = "studio_save_status"
PENDING_VERSION_KEY = "studio_pending_version_key"

VERSION_SELECT_KEY = "studio_version_key"
ASSET_SELECT_KEY = "studio_asset_path"
PREVIEW_MODE_KEY = "studio_preview_mode"
ZOOM_MODE_KEY = "studio_zoom_mode"
FINISH_SELECT_KEY = "studio_finish_select"
PENDING_SWITCH_KEY = "studio_pending_source_switch"
SAVED_NOTE_KEY = "studio_saved_note"
NEEDS_ACK_KEY = "studio_needs_ack"
ACTIVE_FINISH_KEY = "studio_active_finish_id"
LOADED_FOR_KEY = "studio_loaded_for"
DRAFT_ID_KEY = "studio_draft_id"
REVISION_NOTE_KEY = "studio_revision_note"
LAST_RESULT_KEY = "studio_last_best_edit"

PREVIEW_MODES = ("Original", "Finished Preview", "Side by Side", "Split Comparison")
ZOOM_MODES = ("Fit", "100%")

MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"}


def _get_config() -> FinishConfiguration:
    raw = st.session_state.get(CONFIG_KEY)
    if isinstance(raw, FinishConfiguration):
        return raw
    if isinstance(raw, dict):
        return FinishConfiguration.from_dict(raw)
    return FinishConfiguration()


def _set_config(config: FinishConfiguration, *, dirty: bool | None = None) -> None:
    updated = config.to_dict()
    if dirty is True:
        changed = updated != st.session_state.get(CONFIG_KEY)
        st.session_state[CONFIG_KEY] = updated
        if changed:
            st.session_state[DIRTY_KEY] = True
            st.session_state[SAVE_STATUS_KEY] = "unsaved"
        return
    st.session_state[CONFIG_KEY] = updated
    if dirty is False:
        st.session_state[DIRTY_KEY] = False
        st.session_state[SAVE_STATUS_KEY] = "saved"


def _source_key(version: RenderVersion, source_path: Path) -> str:
    return f"{version.key}|{source_path.resolve()}"


def _eligible_versions(state: CampaignState) -> list[RenderVersion]:
    return [v for v in state.versions if v.kind in {"image", "video"}]


def _media_files(version: RenderVersion) -> list[Path]:
    files = [p for p in version.media_files if p.suffix.lower() in MEDIA_SUFFIXES]
    if not files and version.primary_path and version.primary_path.suffix.lower() in MEDIA_SUFFIXES:
        files = [version.primary_path]
    return sorted(set(files))


def _media_type_for(path: Path) -> str:
    if path.suffix.lower() in {".mp4", ".mov"}:
        return "video"
    return "static"


def _recipe_label(recipe_id: str | None) -> str:
    if not recipe_id:
        return "Custom"
    recipe = get_recipe(recipe_id, DEFAULT_BRAND_ID)
    return recipe.display_name if recipe else recipe_id


def _draft_id_for_source(
    campaign_id: str,
    piece_id: str | None,
    parent_render_id: str,
    source_path: Path,
) -> str:
    return draft_id_for(campaign_id, piece_id, parent_render_id, source_path.name)


def _normalise_for_media(config: FinishConfiguration, media_type: str) -> FinishConfiguration:
    if media_type == "video":
        config.export.format = "mp4"
        config.export.fps = float(config.export.fps or 0.0)
    return config


def _load_config_for_source(
    render_folder: Path,
    *,
    campaign_id: str,
    piece_id: str | None,
    parent_render_id: str,
    source_path: Path,
    source_key: str,
    media_type: str,
) -> tuple[FinishConfiguration, str]:
    draft_id = _draft_id_for_source(campaign_id, piece_id, parent_render_id, source_path)
    saved = load_draft(render_folder, draft_id)
    if saved:
        config = FinishConfiguration.from_dict(saved)
    else:
        config = FinishConfiguration()
    config = _normalise_for_media(config, media_type)
    st.session_state[CONFIG_KEY] = config.to_dict()
    st.session_state[DIRTY_KEY] = False
    st.session_state[SAVE_STATUS_KEY] = "saved" if saved else "unsaved"
    st.session_state.pop(PREVIEW_KEY, None)
    st.session_state.pop(NEEDS_ACK_KEY, None)
    st.session_state[DRAFT_ID_KEY] = draft_id
    st.session_state[LOADED_FOR_KEY] = source_key
    return config, draft_id


def _ensure_editor_loaded(
    render_folder: Path,
    *,
    campaign_id: str,
    piece_id: str | None,
    parent_render_id: str,
    source_path: Path,
    source_key: str,
    media_type: str,
) -> tuple[FinishConfiguration, str]:
    if st.session_state.get(LOADED_FOR_KEY) != source_key:
        return _load_config_for_source(
            render_folder,
            campaign_id=campaign_id,
            piece_id=piece_id,
            parent_render_id=parent_render_id,
            source_path=source_path,
            source_key=source_key,
            media_type=media_type,
        )
    draft_id = st.session_state.get(DRAFT_ID_KEY)
    if not draft_id:
        draft_id = _draft_id_for_source(campaign_id, piece_id, parent_render_id, source_path)
        st.session_state[DRAFT_ID_KEY] = draft_id
    return _get_config(), draft_id


def _piece_context(state: CampaignState, version: RenderVersion) -> dict[str, str]:
    piece: PieceState | None = None
    if version.piece_id:
        for candidate in state.pieces:
            if candidate.record.piece_id == version.piece_id:
                piece = candidate
                break
    if piece is None:
        return {
            "title": state.piece_title(version) or version.display_name,
            "platform": (state.platforms[0] if state.platforms else ""),
            "objective": "",
            "format": "",
        }
    return {
        "title": piece.record.title,
        "platform": piece.record.platform or "",
        "objective": piece.record.objective or "",
        "format": piece.record.format or "",
    }


def render(state: CampaignState) -> None:
    ensure_default_recipes(DEFAULT_BRAND_ID)
    ensure_guardrails(DEFAULT_BRAND_ID)
    load_capabilities(DEFAULT_BRAND_ID)

    page_header(
        "Studio",
        "BettyOS chooses and applies the best finish from the Brand Guide and Production Rules.",
    )
    progress_rail(state.steps)

    saved = st.session_state.pop(SAVED_NOTE_KEY, None)
    if saved:
        saved_note(saved)

    if not state.exists:
        empty_state("No campaign selected", "Open a campaign before finishing renders in Studio.")
        if st.button("Go to Campaigns", type="primary", key="studio_to_campaigns"):
            nav.goto("Campaigns")
        return

    eligible = _eligible_versions(state)
    if not eligible:
        empty_state(
            "No eligible renders yet",
            "Studio works on image and video renders. Create at least one render first.",
        )
        if st.button("Go to Create", type="primary", key="studio_to_create"):
            nav.goto("Create", "3. Render")
        return

    pending_version = st.session_state.pop(PENDING_VERSION_KEY, None)
    if pending_version:
        st.session_state[VERSION_SELECT_KEY] = pending_version

    version, source_path, blocked = _select_source(state, eligible)
    if blocked:
        return
    if version is None or source_path is None:
        return

    entry = source_entry_validation(source_path)
    validation = entry.get("validation") or {}
    media_type = entry.get("media_type") or _media_type_for(source_path)
    meta = entry.get("meta") or {}

    if validation.get("outcome") == "fail":
        section("Source validation")
        blocked_state("This source cannot be opened in Studio", _validation_summary(validation))
        _validation_items(validation)
        return

    campaign_id = state.path.name if state.path else "campaign"
    parent_render_id = render_version_id(version.version)
    render_folder = version.folder
    source_key = st.session_state.get(SOURCE_KEY) or _source_key(version, source_path)
    config, draft_id = _ensure_editor_loaded(
        render_folder,
        campaign_id=campaign_id,
        piece_id=version.piece_id,
        parent_render_id=parent_render_id,
        source_path=source_path,
        source_key=source_key,
        media_type=media_type,
    )
    ctx = _piece_context(state, version)
    finish_records = _finish_records_for_render(render_folder, parent_render_id)
    active_finish_id = _active_finish_id(finish_records)
    active_record = next((r for r in finish_records if r.finish_version_id == active_finish_id), None)

    _context_panel(state, version, source_path, media_type, ctx, active_record)

    if validation.get("outcome") == "warning":
        note(_validation_summary(validation))

    section("Generate Best Edit")
    quiet(
        "BettyOS loads the Brand Guide and Production Rules, then applies one recommended finish. "
        "No preset shopping — one best decision."
    )
    if st.button("Generate Best Edit", type="primary", use_container_width=True, key=f"{draft_id}_best_edit"):
        _run_best_edit(
            state,
            version,
            source_path,
            render_folder,
            campaign_id,
            parent_render_id,
            active_finish_id,
            ctx,
            draft_id,
        )

    if active_record and active_record.edit_decision:
        _approval_experience(
            state,
            version,
            source_path,
            render_folder,
            media_type,
            meta,
            active_record,
            draft_id,
            ctx,
        )
    else:
        section("Preview")
        quiet("Generate Best Edit to create a finished draft for approval.")
        _show_media(source_path, media_type, use_container_width=True)

    _finished_versions_panel(render_folder, finish_records, draft_id, version, campaign_id)

    with st.expander("Advanced — normally managed automatically by BettyOS", expanded=False):
        quiet(
            "Manual recipe, lighting, color, grain, LUT, logo, and export controls for debugging "
            "and exceptional use. Ordinary finishing should use Generate Best Edit."
        )
        _advanced_controls(
            state,
            version,
            source_path,
            render_folder,
            draft_id,
            media_type,
            meta,
            finish_records,
            active_finish_id,
            campaign_id,
            parent_render_id,
        )


def _context_panel(
    state: CampaignState,
    version: RenderVersion,
    source_path: Path,
    media_type: str,
    ctx: dict[str, str],
    active_record: FinishRecord | None,
) -> None:
    section("Source and context")
    status = "—"
    if active_record:
        status = f"{active_record.finish_version_id} · {active_record.approval_status.replace('_', ' ')}"
    with st.container(border=True):
        key_values(
            [
                ("Content piece", ctx["title"]),
                ("Campaign goal", state.goal or "—"),
                ("Platform", ctx["platform"] or "—"),
                ("Objective", ctx["objective"] or "—"),
                ("Source asset", source_path.name),
                ("Assigned template", version.display_name),
                ("Render version", f"v{version.version}"),
                ("Current finish", status),
                ("Media", media_type.title()),
            ]
        )
        guardrails = list_guardrails(DEFAULT_BRAND_ID)
        if guardrails:
            quiet(f"{len(guardrails)} production guardrails apply to this brand.")


def _run_best_edit(
    state: CampaignState,
    version: RenderVersion,
    source_path: Path,
    render_folder: Path,
    campaign_id: str,
    parent_render_id: str,
    parent_finish_id: str | None,
    ctx: dict[str, str],
    draft_id: str,
) -> None:
    messages: list[str] = []
    progress_box = st.empty()

    def progress(msg: str) -> None:
        messages.append(msg)
        progress_box.caption(" · ".join(messages[-4:]))

    with st.status("Generating Best Edit…", expanded=True) as status:
        result = generate_best_edit(
            render_folder=render_folder,
            campaign_id=campaign_id,
            content_piece_id=version.piece_id,
            template_id=version.template_id,
            parent_render_version_id=parent_render_id,
            parent_finish_version_id=parent_finish_id,
            source_file=source_path,
            brand_id=DEFAULT_BRAND_ID,
            platform=ctx["platform"],
            campaign_goal=state.goal or "",
            piece_objective=ctx["objective"],
            piece_format=ctx["format"],
            progress=progress,
        )
        if not result.get("ok"):
            status.update(label=str(result.get("error") or "Best Edit failed."), state="error")
            blocked_state("Best Edit failed", str(result.get("error") or ""))
            return

        record = result["record"]
        decision = result.get("decision")
        report = result.get("execution_report")
        config = result.get("config")
        if isinstance(config, FinishConfiguration):
            _set_config(config, dirty=False)
        preview = resolve_finish_preview(render_folder, record)
        if preview and preview.is_file():
            st.session_state[PREVIEW_KEY] = str(preview)
        st.session_state[ACTIVE_FINISH_KEY] = record.finish_version_id
        st.session_state[LAST_RESULT_KEY] = {
            "finish_version_id": record.finish_version_id,
            "decision_id": getattr(decision, "decision_id", None),
        }
        discard_draft(render_folder, draft_id)

        if isinstance(report, ExecutionReport) and report.state != "edit_fully_applied":
            status.update(label=report.summary or "Best Edit partially applied.", state="complete")
        else:
            summary = report.summary if isinstance(report, ExecutionReport) else "Best Edit ready."
            status.update(label=summary, state="complete")
        st.session_state[SAVED_NOTE_KEY] = f"Finished version {record.finish_version_id} created."
        st.rerun()


def _approval_experience(
    state: CampaignState,
    version: RenderVersion,
    source_path: Path,
    render_folder: Path,
    media_type: str,
    meta: dict[str, Any],
    record: FinishRecord,
    draft_id: str,
    ctx: dict[str, str],
) -> None:
    section("Finished draft")
    decision = EditDecision.from_dict(record.edit_decision) if record.edit_decision else None
    report = ExecutionReport.from_dict(record.execution_report) if record.execution_report else None
    preview = resolve_finish_preview(render_folder, record)
    finished = resolve_finish_output(render_folder, record)

    # Before / after
    col_a, col_b = st.columns(2)
    with col_a:
        quiet("Original")
        _show_media(source_path, media_type, use_container_width=True)
    with col_b:
        quiet("Finished")
        if preview and preview.is_file():
            _show_media(preview, "static", use_container_width=True)
        elif finished and finished.is_file():
            show_type = "video" if finished.suffix.lower() in {".mp4", ".mov"} else "static"
            _show_media(finished, show_type, use_container_width=True)
        else:
            quiet("Finished preview unavailable.")

    score = record.creative_review_score
    if score is None and decision:
        score = decision.creative_review_score
    with st.container(border=True):
        key_values(
            [
                ("Finish version", record.finish_version_id),
                ("Status", record.approval_status.replace("_", " ")),
                ("Creative-review score", f"{score:.0f}" if score is not None else "—"),
                (
                    "Execution",
                    (report.state.replace("_", " ") if report else "—"),
                ),
            ]
        )
        if report and report.summary:
            quiet(report.summary)

    # ≤3 major decisions
    section("Key decisions")
    majors = decision.major_decision_summaries() if decision else []
    if not majors and decision and decision.color_recipe:
        recipe = decision.color_recipe.value or {}
        if isinstance(recipe, dict):
            majors = [f"Color recipe: {recipe.get('display_name') or recipe.get('recipe_id')}"]
    if majors:
        for item in majors[:3]:
            st.markdown(f"- {item}")
    else:
        quiet("No major decisions recorded.")

    if report:
        if report.applied:
            quiet("Applied: " + "; ".join(a.label for a in report.applied[:8]))
        if report.not_applied:
            note(
                "Not applied: "
                + "; ".join(f"{a.label} — {a.reason}" for a in report.not_applied[:4])
            )

    with st.expander("View Edit Details", expanded=False):
        if decision:
            key_values(
                [
                    ("Decision id", decision.decision_id),
                    ("Confidence", f"{decision.confidence:.0%}"),
                    ("Brand Guide", "Loaded" if decision.brand_guide_loaded else "Missing"),
                    (
                        "Production Rules",
                        "Loaded" if decision.production_rules_loaded else "Missing",
                    ),
                    ("Rationale", decision.rationale),
                    (
                        "Logo",
                        f"{decision.logo_decision.value} — {decision.logo_decision.reason}",
                    ),
                    (
                        "Recipe",
                        str(
                            (decision.color_recipe.value or {}).get("display_name")
                            if isinstance(decision.color_recipe.value, dict)
                            else decision.color_recipe.value
                        ),
                    ),
                ]
            )
            if decision.unsupported_actions:
                quiet("Limitations: " + " | ".join(decision.unsupported_actions))
            if decision.guidance_conflict_resolutions:
                quiet(
                    "Conflict resolutions: "
                    + " | ".join(decision.guidance_conflict_resolutions)
                )
        else:
            quiet("No structured edit decision on this finish.")
        if finished and finished.is_file():
            download_file(
                finished,
                label="Download finished file",
                key=f"{draft_id}_dl_active_{record.finish_version_id}",
                mime=mime_for(finished),
            )

    section("Approval")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Approve", type="primary", use_container_width=True, key=f"{draft_id}_approve"):
            result = set_finish_approval(
                render_folder=render_folder,
                finish_version_id=record.finish_version_id,
                status="approved",
                brand_id=DEFAULT_BRAND_ID,
                content_type=ctx.get("format") or "",
                platform=ctx.get("platform") or "",
            )
            if result.get("ok"):
                st.session_state[SAVED_NOTE_KEY] = f"{record.finish_version_id} approved."
                st.rerun()
            else:
                blocked_state("Approve failed", str(result.get("error") or ""))
    with col2:
        if st.button("Needs Revision", use_container_width=True, key=f"{draft_id}_needs_rev"):
            st.session_state[f"{draft_id}_show_revision"] = True
    with col3:
        if st.button("Reject", use_container_width=True, key=f"{draft_id}_reject"):
            result = set_finish_approval(
                render_folder=render_folder,
                finish_version_id=record.finish_version_id,
                status="rejected",
                brand_id=DEFAULT_BRAND_ID,
                content_type=ctx.get("format") or "",
                platform=ctx.get("platform") or "",
            )
            if result.get("ok"):
                st.session_state[SAVED_NOTE_KEY] = f"{record.finish_version_id} rejected."
                st.rerun()
            else:
                blocked_state("Reject failed", str(result.get("error") or ""))

    if st.session_state.get(f"{draft_id}_show_revision") or record.approval_status == "needs_revision":
        note(
            "Describe what should change. BettyOS will translate this into a structured revision "
            "and create a new finished version where supported."
        )
        feedback = st.text_area(
            "Revision feedback",
            value=st.session_state.get(REVISION_NOTE_KEY, ""),
            placeholder="The color feels too warm and the logo is distracting.",
            key=f"{draft_id}_revision_text",
        )
        if st.button("Apply Revision", type="primary", key=f"{draft_id}_apply_revision"):
            if not feedback.strip():
                blocked_state("Feedback required", "Enter natural-language revision notes.")
            else:
                st.session_state[REVISION_NOTE_KEY] = feedback.strip()
                _run_revision(
                    state,
                    version,
                    render_folder,
                    record.finish_version_id,
                    feedback.strip(),
                    ctx,
                )


def _run_revision(
    state: CampaignState,
    version: RenderVersion,
    render_folder: Path,
    finish_version_id: str,
    note_text: str,
    ctx: dict[str, str],
) -> None:
    messages: list[str] = []
    progress_box = st.empty()

    def progress(msg: str) -> None:
        messages.append(msg)
        progress_box.caption(" · ".join(messages[-4:]))

    with st.status("Applying revision…", expanded=True) as status:
        result = revise_best_edit(
            render_folder=render_folder,
            finish_version_id=finish_version_id,
            revision_note=note_text,
            brand_id=DEFAULT_BRAND_ID,
            platform=ctx.get("platform") or "",
            campaign_goal=state.goal or "",
            piece_objective=ctx.get("objective") or "",
            piece_format=ctx.get("format") or "",
            progress=progress,
        )
        if not result.get("ok"):
            status.update(label=str(result.get("error") or "Revision failed."), state="error")
            blocked_state("Revision not fully applied", str(result.get("error") or ""))
            return
        record = result["record"]
        preview = resolve_finish_preview(render_folder, record)
        if preview and preview.is_file():
            st.session_state[PREVIEW_KEY] = str(preview)
        st.session_state[ACTIVE_FINISH_KEY] = record.finish_version_id
        st.session_state.pop(REVISION_NOTE_KEY, None)
        status.update(label=f"Revised finish {record.finish_version_id} created.", state="complete")
        st.session_state[SAVED_NOTE_KEY] = f"Revision applied as {record.finish_version_id}."
        st.rerun()


def _select_source(
    state: CampaignState,
    eligible: list[RenderVersion],
) -> tuple[RenderVersion | None, Path | None, bool]:
    section("Choose a render to finish")
    labels = {v.key: state.describe(v) for v in eligible}
    keys = [v.key for v in eligible]
    if st.session_state.get(VERSION_SELECT_KEY) not in keys:
        st.session_state[VERSION_SELECT_KEY] = keys[0]

    chosen_key = st.selectbox(
        "Render version",
        options=keys,
        format_func=lambda key: labels[key],
        key=VERSION_SELECT_KEY,
    )
    version = next(v for v in eligible if v.key == chosen_key)
    media = _media_files(version)
    if not media:
        blocked_state("No media file", "This render version has no image or video output to finish.")
        return version, None, False

    asset_labels = {str(p): p.name for p in media}
    asset_paths = list(asset_labels.keys())
    if st.session_state.get(ASSET_SELECT_KEY) not in asset_paths:
        default = str(version.primary_path) if version.primary_path else asset_paths[0]
        if default not in asset_paths:
            default = asset_paths[0]
        st.session_state[ASSET_SELECT_KEY] = default

    chosen_asset = st.selectbox(
        "Output asset",
        options=asset_paths,
        format_func=lambda path: asset_labels[path],
        key=ASSET_SELECT_KEY,
    )
    source_path = Path(chosen_asset)
    requested_key = _source_key(version, source_path)
    current_key = st.session_state.get(SOURCE_KEY)

    if current_key and current_key != requested_key and st.session_state.get(DIRTY_KEY):
        st.session_state[PENDING_SWITCH_KEY] = requested_key
        blocked_state(
            "Unsaved advanced changes",
            "Save or discard your Advanced Controls draft before switching source.",
        )
        col_save, col_discard = st.columns(2)
        if col_save.button("Save Draft", type="primary", key="studio_switch_save"):
            _save_current_draft_from_key(state, current_key)
            st.session_state[SOURCE_KEY] = requested_key
            st.session_state.pop(LOADED_FOR_KEY, None)
            st.session_state.pop(PENDING_SWITCH_KEY, None)
            st.rerun()
        if col_discard.button("Discard", key="studio_switch_discard"):
            st.session_state[SOURCE_KEY] = requested_key
            st.session_state.pop(LOADED_FOR_KEY, None)
            st.session_state.pop(PENDING_SWITCH_KEY, None)
            st.rerun()
        return version, source_path, True

    if current_key != requested_key:
        st.session_state[SOURCE_KEY] = requested_key
        st.rerun()

    return version, source_path, False


def _save_current_draft_from_key(state: CampaignState, source_key: str) -> None:
    version_key, source_str = source_key.split("|", 1)
    source_path = Path(source_str)
    version = next((v for v in _eligible_versions(state) if v.key == version_key), None)
    if version is None:
        return
    campaign_id = state.path.name if state.path else "campaign"
    parent_render_id = render_version_id(version.version)
    draft_id = _draft_id_for_source(campaign_id, version.piece_id, parent_render_id, source_path)
    config = _get_config()
    save_draft(
        version.folder,
        draft_id,
        config,
        meta={"source_file": str(source_path.resolve()), "config_hash": config_hash(config)},
    )
    _set_config(config, dirty=False)


def _show_media(
    path: Path,
    media_type: str,
    *,
    use_container_width: bool,
    width: int | None = None,
) -> None:
    if not path.is_file():
        blocked_state("File missing", str(path))
        return
    if media_type == "video" and path.suffix.lower() in {".mp4", ".mov"}:
        st.video(str(path))
        return
    kwargs: dict[str, Any] = {"use_container_width": use_container_width}
    if width and not use_container_width:
        kwargs["width"] = min(width, 1600)
    st.image(str(path), **kwargs)


def _advanced_controls(
    state: CampaignState,
    version: RenderVersion,
    source_path: Path,
    render_folder: Path,
    draft_id: str,
    media_type: str,
    meta: dict[str, Any],
    finish_records: list[FinishRecord],
    active_finish_id: str | None,
    campaign_id: str,
    parent_render_id: str,
) -> None:
    config = _get_config()
    with st.expander("Recipe", expanded=False):
        config = _section_recipe(config, draft_id)
    with st.expander("Logo", expanded=False):
        config = _section_logo(config, draft_id, media_type, meta)
    with st.expander("Light", expanded=False):
        config = _section_lighting(config, draft_id)
    with st.expander("Color", expanded=False):
        config = _section_color(config, draft_id)
    with st.expander("Texture", expanded=False):
        config = _section_texture(config, draft_id, media_type)
    with st.expander("Crop / Geometry", expanded=False):
        config = _section_geometry(config, draft_id)
    with st.expander("LUT", expanded=False):
        config = _section_lut(config, draft_id)
    if media_type == "video":
        with st.expander("Video", expanded=False):
            config = _section_video(config, draft_id)
    with st.expander("Export", expanded=False):
        config = _section_export(config, draft_id, media_type)
    _set_config(config, dirty=st.session_state.get(DIRTY_KEY, False))

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Preview Changes", use_container_width=True, key=f"{draft_id}_adv_preview"):
            cache = preview_cache_dir(DEFAULT_BRAND_ID) / draft_id
            cache.mkdir(parents=True, exist_ok=True)
            preview_out = cache / (
                "preview.jpg" if media_type == "video" else f"preview{source_path.suffix.lower()}"
            )
            result = run_preview(
                source_path, config, brand_id=DEFAULT_BRAND_ID, preview_out=preview_out
            )
            if result.get("ok") and result.get("preview"):
                st.session_state[PREVIEW_KEY] = str(result["preview"])
                st.success("Advanced preview ready.")
            else:
                blocked_state("Preview failed", str(result.get("error") or ""))
        if st.button("Save Draft", use_container_width=True, key=f"{draft_id}_adv_save"):
            save_draft(
                render_folder,
                draft_id,
                config,
                meta={"source_file": str(source_path.resolve()), "config_hash": config_hash(config)},
            )
            _set_config(config, dirty=False)
            st.session_state[SAVED_NOTE_KEY] = "Advanced draft saved."
            st.rerun()
    with col_b:
        if st.button("Create Finished Version", use_container_width=True, key=f"{draft_id}_adv_finish"):
            result = create_finish(
                render_folder=render_folder,
                campaign_id=campaign_id,
                content_piece_id=version.piece_id,
                template_id=version.template_id,
                parent_render_version_id=parent_render_id,
                parent_finish_version_id=active_finish_id,
                source_file=source_path,
                config=config,
                brand_id=DEFAULT_BRAND_ID,
                auto_ack_warnings=True,
            )
            if result.get("ok"):
                st.session_state[ACTIVE_FINISH_KEY] = result["record"].finish_version_id
                st.session_state[SAVED_NOTE_KEY] = (
                    f"Manual finish {result['record'].finish_version_id} created."
                )
                st.rerun()
            else:
                blocked_state("Finish failed", str(result.get("error") or ""))
        if st.button("Discard Draft", use_container_width=True, key=f"{draft_id}_adv_discard"):
            discard_draft(render_folder, draft_id)
            _load_config_for_source(
                render_folder,
                campaign_id=campaign_id,
                piece_id=version.piece_id,
                parent_render_id=parent_render_id,
                source_path=source_path,
                source_key=_source_key(version, source_path),
                media_type=media_type,
            )
            st.rerun()


def _finish_records_for_render(render_folder: Path, parent_render_id: str) -> list[FinishRecord]:
    return [
        r
        for r in list_finish_records(render_folder)
        if r.parent_render_version_id == parent_render_id and r.status != "failed"
    ]


def _active_finish_id(records: list[FinishRecord]) -> str | None:
    stored = st.session_state.get(ACTIVE_FINISH_KEY)
    if stored and any(r.finish_version_id == stored for r in records):
        return stored
    if records:
        return records[-1].finish_version_id
    return None


def _finished_versions_panel(
    render_folder: Path,
    records: list[FinishRecord],
    draft_id: str,
    version: RenderVersion,
    campaign_id: str,
) -> None:
    section("Finished versions")
    if not records:
        quiet("No finished versions yet for this render.")
        return

    quiet(count_phrase(len(records), "finished version") + f" for {version.display_name} v{version.version}.")
    for record in reversed(records):
        with st.container(border=True):
            output = output_is_downloadable(render_folder, record)
            key_values(
                [
                    ("Version", record.finish_version_id),
                    ("Recipe", _recipe_label(record.recipe_id)),
                    ("Status", record.status.replace("_", " ")),
                    ("Approval", record.approval_status.replace("_", " ")),
                    ("Created", record.created_at),
                    (
                        "Decision",
                        (record.edit_decision or {}).get("decision_id") or "—",
                    ),
                ]
            )
            if record.revision_note:
                quiet(f"Revision note: {record.revision_note}")
            col_dl, col_pkg = st.columns(2)
            with col_dl:
                if output:
                    download_file(
                        output,
                        label="Download finished file",
                        key=f"{draft_id}_dl_{record.finish_version_id}",
                        mime=mime_for(output),
                    )
                    quiet(finished_download_name(record, output))
                else:
                    quiet("Output file not available.")
            with col_pkg:
                if st.button(
                    "Build Studio package",
                    key=f"{draft_id}_pkg_{record.finish_version_id}",
                    use_container_width=True,
                ):
                    try:
                        dest = make_studio_package(render_folder, record, DEFAULT_BRAND_ID)
                        st.session_state[f"studio_pkg_{record.finish_version_id}"] = str(dest)
                    except Exception as exc:  # noqa: BLE001
                        blocked_state("Package failed", str(exc))
                built = st.session_state.get(f"studio_pkg_{record.finish_version_id}")
                if built and Path(built).is_file():
                    download_file(
                        Path(built),
                        label="Download package",
                        key=f"{draft_id}_pkg_dl_{record.finish_version_id}",
                        mime="application/zip",
                    )
            if st.button(
                "View this version",
                key=f"{draft_id}_view_{record.finish_version_id}",
            ):
                st.session_state[ACTIVE_FINISH_KEY] = record.finish_version_id
                preview = resolve_finish_preview(render_folder, record)
                if preview:
                    st.session_state[PREVIEW_KEY] = str(preview)
                st.rerun()


def _validation_summary(validation: dict[str, Any]) -> str:
    items = validation.get("items") or []
    fails = [i for i in items if i.get("outcome") == "fail"]
    warns = [i for i in items if i.get("outcome") == "warning"]
    if fails:
        return fails[0].get("message") or "Validation failed."
    if warns:
        return warns[0].get("message") or "Validation produced warnings."
    return "Validation passed."


def _validation_items(validation: dict[str, Any]) -> None:
    items = validation.get("items") or []
    if not items:
        return
    with st.expander("Validation details", expanded=False):
        for item in items:
            outcome = item.get("outcome", "pass")
            tone = {"fail": "blocked", "warning": "attention", "pass": "positive"}.get(outcome, "neutral")
            show_badges([action_status(tone if tone != "attention" else "blocked")])
            quiet(item.get("message") or "")
            if item.get("details"):
                quiet(str(item["details"]))


# --- Advanced control sections (exceptional / debugging use) ---------------


def _section_recipe(config: FinishConfiguration, draft_id: str) -> FinishConfiguration:
    recipes = list_recipes(DEFAULT_BRAND_ID)
    options = ["— None —", *[r.recipe_id for r in recipes]]
    labels = {"— None —": "No recipe"}
    labels.update({r.recipe_id: r.display_name for r in recipes})
    current = config.recipe_id or "— None —"
    if current not in options:
        options.append(current)
    selected = st.selectbox(
        "Color recipe",
        options=options,
        index=options.index(current),
        format_func=lambda key: labels.get(key, key),
        key=f"{draft_id}_recipe",
    )
    if selected != current:
        if selected == "— None —":
            config.recipe_id = None
            config.recipe_version = 1
            config.recipe_snapshot = {}
        else:
            recipe = get_recipe(selected, DEFAULT_BRAND_ID)
            if recipe:
                config = apply_recipe_to_config(recipe, config)
        _set_config(config, dirty=True)

    if config.recipe_id:
        recipe = get_recipe(config.recipe_id, DEFAULT_BRAND_ID)
        if recipe and recipe.description:
            note(recipe.description)

    if st.button("Apply recipe defaults", key=f"{draft_id}_apply_recipe"):
        recipe = get_recipe(config.recipe_id, DEFAULT_BRAND_ID) if config.recipe_id else None
        if recipe:
            config = apply_recipe_to_config(recipe, FinishConfiguration())
            _set_config(config, dirty=True)
            st.rerun()
    return _get_config()


def _section_logo(
    config: FinishConfiguration,
    draft_id: str,
    media_type: str,
    meta: dict[str, Any],
) -> FinishConfiguration:
    logo = config.logo
    roles = ["none", *LOGO_ROLES]
    role = st.selectbox(
        "Logo role",
        options=roles,
        index=roles.index(logo.role if logo.role in roles else "none"),
        format_func=lambda r: "None" if r == "none" else ROLE_LABELS.get(r, r.replace("_", " ").title()),
        key=f"{draft_id}_logo_role",
    )
    logo.role = role

    assets = list_assets(DEFAULT_BRAND_ID)
    role_assets = [a for a in assets if a.role == role] if role != "none" else []
    asset_options = ["— Default for role —", *[a.asset_id for a in role_assets]]
    asset_labels = {"— Default for role —": "Default for role"}
    asset_labels.update({a.asset_id: a.display_name for a in role_assets})
    current_asset = logo.asset_id or "— Default for role —"
    if current_asset not in asset_options and logo.asset_id:
        asset_options.append(current_asset)

    picked = st.selectbox(
        "Logo asset",
        options=asset_options,
        index=asset_options.index(current_asset),
        format_func=lambda key: asset_labels.get(key, key),
        key=f"{draft_id}_logo_asset",
        disabled=role == "none",
    )
    if picked == "— Default for role —":
        default = default_asset_for_role(role, DEFAULT_BRAND_ID) if role != "none" else None
        logo.asset_id = default.asset_id if default else None
    else:
        logo.asset_id = picked

    placements = list(LOGO_PLACEMENTS)
    placement = st.selectbox(
        "Placement",
        options=placements,
        index=placements.index(logo.placement if logo.placement in placements else "bottom_right"),
        format_func=lambda p: p.replace("_", " ").title(),
        key=f"{draft_id}_logo_placement",
    )
    logo.placement = placement

    if placement == "custom":
        logo.custom_x_percent = st.slider(
            "Horizontal position (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(logo.custom_x_percent),
            key=f"{draft_id}_logo_custom_x",
        )
        logo.custom_y_percent = st.slider(
            "Vertical position (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(logo.custom_y_percent),
            key=f"{draft_id}_logo_custom_y",
        )

    size_modes = ["subtle", "standard", "prominent", "custom"]
    logo.size_mode = st.selectbox(
        "Size",
        options=size_modes,
        index=size_modes.index(logo.size_mode if logo.size_mode in size_modes else "standard"),
        key=f"{draft_id}_logo_size_mode",
    )
    if logo.size_mode == "custom":
        logo.size_percent = st.slider(
            "Size (%)",
            min_value=4.0,
            max_value=40.0,
            value=float(logo.size_percent),
            key=f"{draft_id}_logo_size_pct",
        )

    logo.opacity = st.slider(
        "Opacity",
        min_value=0.1,
        max_value=1.0,
        value=float(logo.opacity),
        key=f"{draft_id}_logo_opacity",
    )

    if media_type == "video":
        timing_modes = ["full", "opening", "closing", "custom"]
        logo.timing_mode = st.selectbox(
            "Timing",
            options=timing_modes,
            index=timing_modes.index(logo.timing_mode if logo.timing_mode in timing_modes else "full"),
            key=f"{draft_id}_logo_timing",
        )
        duration = float(meta.get("duration") or 30.0)
        if logo.timing_mode == "custom":
            logo.start_seconds = st.number_input(
                "Start (seconds)",
                min_value=0.0,
                max_value=duration,
                value=float(logo.start_seconds),
                key=f"{draft_id}_logo_start",
            )
            end_default = logo.end_seconds if logo.end_seconds is not None else duration
            logo.end_seconds = st.number_input(
                "End (seconds)",
                min_value=logo.start_seconds,
                max_value=duration,
                value=float(end_default),
                key=f"{draft_id}_logo_end",
            )

    if logo.asset_id:
        asset = next((a for a in assets if a.asset_id == logo.asset_id), None)
        if asset:
            path = resolve_asset_path(asset)
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                st.image(str(path), width=120)

    config.logo = logo
    _set_config(config, dirty=True)
    return config


def _section_lighting(config: FinishConfiguration, draft_id: str) -> FinishConfiguration:
    light = config.lighting
    light.exposure = st.slider("Exposure (stops)", -2.0, 2.0, float(light.exposure), 0.05, key=f"{draft_id}_exp")
    light.brightness = st.slider("Brightness", -100.0, 100.0, float(light.brightness), key=f"{draft_id}_bright")
    light.contrast = st.slider("Contrast", -100.0, 100.0, float(light.contrast), key=f"{draft_id}_contrast")
    light.highlights = st.slider("Highlights", -100.0, 100.0, float(light.highlights), key=f"{draft_id}_hi")
    light.shadows = st.slider("Shadows", -100.0, 100.0, float(light.shadows), key=f"{draft_id}_sh")
    light.whites = st.slider("Whites", -100.0, 100.0, float(light.whites), key=f"{draft_id}_wh")
    light.blacks = st.slider("Blacks", -100.0, 100.0, float(light.blacks), key=f"{draft_id}_bl")
    light.gamma = st.slider("Gamma", 0.5, 2.0, float(light.gamma), 0.01, key=f"{draft_id}_gamma")
    config.lighting = light
    _set_config(config, dirty=True)
    return config


def _section_color(config: FinishConfiguration, draft_id: str) -> FinishConfiguration:
    color = config.color
    color.temperature = st.slider("Temperature", -100.0, 100.0, float(color.temperature), key=f"{draft_id}_temp")
    color.tint = st.slider("Tint", -100.0, 100.0, float(color.tint), key=f"{draft_id}_tint")
    color.saturation = st.slider("Saturation", -100.0, 100.0, float(color.saturation), key=f"{draft_id}_sat")
    color.vibrance = st.slider("Vibrance", -100.0, 100.0, float(color.vibrance), key=f"{draft_id}_vib")
    color.fade = st.slider("Fade", 0.0, 100.0, float(color.fade), key=f"{draft_id}_fade")
    color.black_point_lift = st.slider(
        "Black point lift",
        0.0,
        100.0,
        float(color.black_point_lift),
        key=f"{draft_id}_lift",
    )
    color.red_balance = st.slider("Red balance", -100.0, 100.0, float(color.red_balance), key=f"{draft_id}_red")
    color.green_balance = st.slider("Green balance", -100.0, 100.0, float(color.green_balance), key=f"{draft_id}_green")
    color.blue_balance = st.slider("Blue balance", -100.0, 100.0, float(color.blue_balance), key=f"{draft_id}_blue")
    config.color = color
    _set_config(config, dirty=True)
    return config


def _section_texture(
    config: FinishConfiguration,
    draft_id: str,
    media_type: str,
) -> FinishConfiguration:
    if media_type == "video":
        quiet("Use the Video section for grain, vignette, and sharpening on video.")
        return config
    tex = config.texture
    tex.grain_amount = st.slider("Grain", 0.0, 100.0, float(tex.grain_amount), key=f"{draft_id}_grain")
    tex.grain_size = st.slider("Grain size", 0.5, 3.0, float(tex.grain_size), 0.1, key=f"{draft_id}_grain_size")
    tex.grain_roughness = st.slider(
        "Grain roughness",
        0.0,
        1.0,
        float(tex.grain_roughness),
        key=f"{draft_id}_grain_rough",
    )
    tex.sharpening = st.slider("Sharpening", 0.0, 100.0, float(tex.sharpening), key=f"{draft_id}_sharp")
    tex.softening = st.slider("Softening", 0.0, 100.0, float(tex.softening), key=f"{draft_id}_soft")
    tex.clarity = st.slider("Clarity", 0.0, 100.0, float(tex.clarity), key=f"{draft_id}_clarity")
    tex.bloom = st.slider("Bloom", 0.0, 100.0, float(tex.bloom), key=f"{draft_id}_bloom")
    tex.vignette_amount = st.slider("Vignette", 0.0, 100.0, float(tex.vignette_amount), key=f"{draft_id}_vig")
    tex.vignette_feather = st.slider(
        "Vignette feather",
        0.0,
        1.0,
        float(tex.vignette_feather),
        key=f"{draft_id}_vig_feather",
    )
    config.texture = tex
    _set_config(config, dirty=True)
    return config


def _section_geometry(config: FinishConfiguration, draft_id: str) -> FinishConfiguration:
    geo = config.geometry
    aspect_keys = list(ASPECT_PRESETS.keys())
    geo.aspect_preset = st.selectbox(
        "Aspect preset",
        options=aspect_keys,
        index=aspect_keys.index(geo.aspect_preset if geo.aspect_preset in aspect_keys else "original"),
        format_func=lambda k: k.replace("_", " ").title(),
        key=f"{draft_id}_aspect",
    )
    crop_modes = ["none", "free", "fill", "fit"]
    geo.crop_mode = st.selectbox(
        "Crop mode",
        options=crop_modes,
        index=crop_modes.index(geo.crop_mode if geo.crop_mode in crop_modes else "none"),
        key=f"{draft_id}_crop_mode",
    )
    if geo.crop_mode != "none":
        geo.crop_left = st.slider("Crop left", 0.0, 1.0, float(geo.crop_left), key=f"{draft_id}_crop_l")
        geo.crop_top = st.slider("Crop top", 0.0, 1.0, float(geo.crop_top), key=f"{draft_id}_crop_t")
        geo.crop_right = st.slider("Crop right", 0.0, 1.0, float(geo.crop_right), key=f"{draft_id}_crop_r")
        geo.crop_bottom = st.slider("Crop bottom", 0.0, 1.0, float(geo.crop_bottom), key=f"{draft_id}_crop_b")
    rotate_options = [0.0, 90.0, 180.0, 270.0]
    geo.rotate_degrees = st.selectbox(
        "Rotate",
        options=rotate_options,
        index=rotate_options.index(geo.rotate_degrees if geo.rotate_degrees in rotate_options else 0.0),
        key=f"{draft_id}_rotate",
    )
    geo.straighten_degrees = st.slider(
        "Straighten",
        -15.0,
        15.0,
        float(geo.straighten_degrees),
        key=f"{draft_id}_straighten",
    )
    platform_keys = list(PLATFORM_EXPORT_PRESETS.keys())
    geo.platform_preset = st.selectbox(
        "Platform preset",
        options=platform_keys,
        index=platform_keys.index(geo.platform_preset if geo.platform_preset in platform_keys else "original"),
        format_func=lambda k: PLATFORM_EXPORT_PRESETS[k]["label"],
        key=f"{draft_id}_platform",
    )
    preset = PLATFORM_EXPORT_PRESETS.get(geo.platform_preset, {})
    if preset.get("width"):
        geo.output_width = preset["width"]
        geo.output_height = preset["height"]
    config.geometry = geo
    _set_config(config, dirty=True)
    return config


def _section_lut(config: FinishConfiguration, draft_id: str) -> FinishConfiguration:
    luts = [r for r in list_luts(DEFAULT_BRAND_ID) if r.status == "Ready"]
    options = ["— None —", *[r.lut_id for r in luts]]
    labels = {"— None —": "No LUT"}
    labels.update({r.lut_id: r.display_name for r in luts})
    current = config.lut.lut_id or "— None —"
    if current not in options and config.lut.lut_id:
        options.append(current)
    picked = st.selectbox(
        "LUT",
        options=options,
        index=options.index(current),
        format_func=lambda key: labels.get(key, key),
        key=f"{draft_id}_lut",
    )
    config.lut.lut_id = None if picked == "— None —" else picked
    config.lut.intensity = st.slider(
        "LUT intensity",
        0.0,
        1.0,
        float(config.lut.intensity),
        key=f"{draft_id}_lut_intensity",
    )
    _set_config(config, dirty=True)
    return config


def _section_video(config: FinishConfiguration, draft_id: str) -> FinishConfiguration:
    vid = config.video
    vid.brightness = st.slider("Brightness", -1.0, 1.0, float(vid.brightness), 0.05, key=f"{draft_id}_vid_bright")
    vid.contrast = st.slider("Contrast", 0.5, 2.0, float(vid.contrast), 0.05, key=f"{draft_id}_vid_contrast")
    vid.saturation = st.slider("Saturation", 0.0, 2.0, float(vid.saturation), 0.05, key=f"{draft_id}_vid_sat")
    vid.gamma = st.slider("Gamma", 0.5, 2.0, float(vid.gamma), 0.01, key=f"{draft_id}_vid_gamma")
    vid.temperature = st.slider("Temperature", -100.0, 100.0, float(vid.temperature), key=f"{draft_id}_vid_temp")
    vid.fade = st.slider("Fade", 0.0, 100.0, float(vid.fade), key=f"{draft_id}_vid_fade")
    vid.grain = st.slider("Grain", 0.0, 100.0, float(vid.grain), key=f"{draft_id}_vid_grain")
    vid.sharpen = st.slider("Sharpen", 0.0, 100.0, float(vid.sharpen), key=f"{draft_id}_vid_sharpen")
    vid.vignette = st.slider("Vignette", 0.0, 100.0, float(vid.vignette), key=f"{draft_id}_vid_vig")
    config.video = vid
    _set_config(config, dirty=True)
    return config


def _section_export(
    config: FinishConfiguration,
    draft_id: str,
    media_type: str,
) -> FinishConfiguration:
    export = config.export
    if media_type == "static":
        formats = ["png", "jpg", "webp"]
        export.format = st.selectbox(
            "Format",
            options=formats,
            index=formats.index(export.format if export.format in formats else "png"),
            key=f"{draft_id}_export_fmt",
        )
        export.quality = st.slider("Quality", 60, 100, int(export.quality), key=f"{draft_id}_export_q")
        export.preserve_transparency = st.checkbox(
            "Preserve transparency",
            value=export.preserve_transparency,
            key=f"{draft_id}_export_alpha",
        )
    else:
        export.format = "mp4"
        export.fps = st.number_input(
            "FPS (optional)",
            min_value=0.0,
            value=float(export.fps or 0.0),
            key=f"{draft_id}_export_fps",
        )
        export.bitrate = st.text_input("Bitrate", value=export.bitrate, key=f"{draft_id}_export_bitrate")
        export.audio_normalize = st.checkbox(
            "Normalize audio",
            value=export.audio_normalize,
            key=f"{draft_id}_export_audio",
        )
        export.fade_in_seconds = st.number_input(
            "Fade in (seconds)",
            min_value=0.0,
            value=float(export.fade_in_seconds),
            key=f"{draft_id}_export_fade_in",
        )
        export.fade_out_seconds = st.number_input(
            "Fade out (seconds)",
            min_value=0.0,
            value=float(export.fade_out_seconds),
            key=f"{draft_id}_export_fade_out",
        )
    export.strip_metadata = st.checkbox(
        "Strip metadata",
        value=export.strip_metadata,
        key=f"{draft_id}_export_strip",
    )
    config.export = export
    _set_config(config, dirty=True)
    return config
