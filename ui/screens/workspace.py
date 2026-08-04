"""Guided campaign workspace — Brief → Plan → Capture → Create → Decide → Deliver.

Pipeline tools (Create, Studio, Review, Approvals, Export) remain available under
Advanced. The ordinary path is one progression with one primary action.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.common import DEFAULT_BRAND_ID
from ui import nav
from ui.campaign_state import CampaignState, finish_records_for_version
from ui.components import (
    blocked_state,
    empty_state,
    key_values,
    media_preview,
    note,
    page_header,
    progress_rail,
    quiet,
    report,
    saved_note,
    section,
    show_badges,
)
from ui.continue_campaign import (
    WORKSPACE_STAGES,
    resolve_continuation,
)
from ui.journal import journal_for_campaign
from ui.status import Status, campaign_status
from ui.workflow_service import copy_fields_for_piece, render_piece, save_version_decision
from ui.export_service import (
    PUBLISHING_MODE,
    build_plan,
    create_export_package,
    human_size,
    list_existing_packages,
)


STAGE_OPTIONS = [label for _, label in WORKSPACE_STAGES]
STAGE_KEYS = {label: key for key, label in WORKSPACE_STAGES}
KEY_TO_LABEL = {key: label for key, label in WORKSPACE_STAGES}

# Widget-backed key must stay distinct from internal workflow / pending navigation keys.
STAGE_WIDGET_KEY = "workspace_stage_selector"
STAGE_STATE_KEY = "workspace_stage"


def _sync_stage_before_widget(default_label: str) -> str:
    """Apply pending navigation and defaults before the stage widget exists.

    Streamlit forbids writing a widget's session_state key after that widget is
    instantiated. Pending deep-links (Today → Decide, etc.) must land on the
    selector key here, ahead of `step_selector`.
    """
    pending = nav.take_pending_stage(STAGE_OPTIONS)
    if pending:
        st.session_state[STAGE_STATE_KEY] = pending
        st.session_state[STAGE_WIDGET_KEY] = pending
        return pending

    current = st.session_state.get(STAGE_STATE_KEY)
    if current not in STAGE_OPTIONS:
        current = default_label
        st.session_state[STAGE_STATE_KEY] = current

    if st.session_state.get(STAGE_WIDGET_KEY) not in STAGE_OPTIONS:
        st.session_state[STAGE_WIDGET_KEY] = current
    return current


def render(state: CampaignState) -> None:
    continuation = resolve_continuation(state)

    if not state.exists:
        page_header("Campaign", "Start or open a campaign to continue.")
        empty_state("No active campaign", "Start a campaign and BettyOS will recommend the next move.")
        if st.button("Start a Campaign", type="primary"):
            nav.clear_contextual_page()
            nav.goto("Campaigns")
        return

    _header(state, continuation)

    flash = st.session_state.pop("betty_flash", None)
    if flash:
        saved_note(str(flash))

    # Resume interrupted flows (e.g. logo upload) before choosing the stage.
    interrupted = nav.take_interrupted_flow()
    if interrupted and interrupted.get("stage"):
        st.session_state[nav.PENDING_STAGE] = interrupted["stage"]
        if interrupted.get("piece_id"):
            nav.select_piece(interrupted["piece_id"])
        if interrupted.get("version_key"):
            st.session_state[nav.FOCUS_VERSION] = interrupted["version_key"]

    default_label = KEY_TO_LABEL.get(continuation.current_stage, "Plan")
    _sync_stage_before_widget(default_label)
    selected = nav.step_selector("Stage", STAGE_OPTIONS, key=STAGE_WIDGET_KEY)
    # Reflect the widget choice into the internal workflow key only — never write
    # back to STAGE_WIDGET_KEY after the selector exists.
    if selected in STAGE_OPTIONS:
        st.session_state[STAGE_STATE_KEY] = selected
    else:
        selected = st.session_state.get(STAGE_STATE_KEY, default_label)

    stage_key = STAGE_KEYS.get(selected, continuation.current_stage)
    nav.persist_workspace_context(state.path, stage=stage_key)

    if stage_key == "brief":
        _stage_brief(state, continuation)
    elif stage_key == "plan":
        _stage_plan(state, continuation)
    elif stage_key == "capture":
        _stage_capture(state, continuation)
    elif stage_key == "create":
        _stage_create(state, continuation)
    elif stage_key == "decide":
        _stage_decide(state, continuation)
    else:
        _stage_deliver(state, continuation)

    _journal_panel(state)
    _advanced_panel(state, stage_key)


def _header(state: CampaignState, continuation) -> None:
    stage = Status(
        continuation.current_state,
        continuation.founder_stage_label,
        campaign_status(state.stage).tone,
    )
    page_header(state.name, state.goal, badges=[stage])
    progress_rail(state.steps)

    cols = st.columns([3, 1, 1], gap="medium", vertical_alignment="center")
    with cols[0]:
        quiet(f"Next: {continuation.primary_action.label}")
    with cols[1]:
        if st.button("Return to Today", use_container_width=True, key="ws_today"):
            nav.clear_contextual_page()
            nav.goto("Today")
    with cols[2]:
        if st.button("Campaign details", use_container_width=True, key="ws_campaigns"):
            nav.clear_contextual_page()
            nav.goto("Campaigns")


def _resolve_stage_label(stage_key: str) -> str:
    return KEY_TO_LABEL.get(stage_key, "Plan")


# --- Brief ------------------------------------------------------------------

def _stage_brief(state: CampaignState, continuation) -> None:
    section("What are we trying to accomplish?")
    quiet(continuation.message)
    with st.container(border=True):
        goal = st.text_area("Campaign goal", value=state.goal if state.goal != "No goal recorded" else "", height=100)
        platforms = st.multiselect(
            "Platforms",
            ["Instagram", "Pinterest", "TikTok", "Email", "Waitlist", "YouTube Shorts"],
            default=state.platforms or st.session_state.get("campaign_platforms", ["Instagram", "Pinterest"]),
        )
        if st.button("Save Goal", type="primary", key="ws_save_goal"):
            st.session_state["campaign_goal"] = goal.strip()
            st.session_state["campaign_platforms"] = platforms
            st.session_state["betty_flash"] = (
                "Goal saved for this session. Existing campaign content keeps its recorded goal; "
                "new planning uses this goal."
            )
            if goal.strip():
                nav.goto_workspace("plan")
            else:
                st.rerun()
        quiet("To rebuild the content plan from a new goal, create or replan from Campaigns.")
        if st.button("Open Campaigns to replan", key="ws_replan"):
            nav.clear_contextual_page()
            nav.goto("Campaigns")


# --- Plan -------------------------------------------------------------------

def _stage_plan(state: CampaignState, continuation) -> None:
    section("Recommended direction")
    if not state.pieces:
        empty_state(
            "No campaign content yet",
            "Create or replan this campaign so I can recommend what to make.",
        )
        if st.button("Start Planning", type="primary"):
            nav.clear_contextual_page()
            nav.goto("Campaigns")
        return

    piece = _focus_piece(state, continuation)
    record = piece.record
    with st.container(border=True):
        st.markdown(f'<div class="betty-section">{record.title}</div>', unsafe_allow_html=True)
        key_values(
            [
                ("Primary platform", record.platform or "—"),
                ("Audience intent", record.objective or "—"),
                ("Expected role", record.format or "—"),
                ("What will be created", piece.template_name),
                ("Source material needed", _source_summary(piece)),
                ("Estimated human effort", continuation.estimated_effort or "—"),
            ]
        )
        why = continuation.why
        if why:
            st.write("")
            section("Why it is the best fit")
            st.write(why)

        st.write("")
        if st.button("Accept Plan", type="primary", key="ws_accept_plan"):
            if piece.status_key == "missing_inputs":
                nav.goto_workspace("capture", piece_id=record.piece_id)
            elif piece.status_key == "ready_to_render" or piece.versions:
                nav.goto_workspace("create", piece_id=record.piece_id)
            else:
                nav.goto_workspace("capture", piece_id=record.piece_id)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Request a Different Direction", key="ws_diff_dir"):
                nav.clear_contextual_page()
                nav.goto("Campaigns")
        with c2:
            if st.button("Edit Campaign Goal", key="ws_edit_goal"):
                nav.goto_workspace("brief")

    with st.expander("View Planning Details", expanded=False):
        for other in state.pieces:
            status = other.status_key.replace("_", " ")
            quiet(f"{other.record.title} · {other.record.platform} · {status}")


# --- Capture ----------------------------------------------------------------

def _stage_capture(state: CampaignState, continuation) -> None:
    section("What I need from you")
    piece = _focus_piece(state, continuation)
    if piece is None:
        quiet("Nothing is waiting on footage right now.")
        if st.button("Continue", type="primary"):
            nav.goto_workspace(continuation.current_stage)
        return

    required = list(continuation.required_from_user) or _default_shots(piece)
    with st.container(border=True):
        st.markdown(
            f'<div class="betty-section">I need {len(required)} '
            f'{"clip" if len(required) == 1 else "clips"}.</div>',
            unsafe_allow_html=True,
        )
        for index, item in enumerate(required, start=1):
            st.markdown(f"{index}. {item}")

        st.write("")
        section("Estimated filming time")
        quiet(continuation.estimated_effort or "About 8 minutes")

        st.write("")
        section("Capture guidance")
        for tip in (
            "Vertical framing",
            "Natural window light",
            "Leave room for typography",
            "Keep the background quiet",
        ):
            st.markdown(f"- {tip}")

        st.write("")
        uploaded = st.file_uploader(
            "Add footage",
            type=["mp4", "mov", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"ws_capture_{piece.record.piece_id}",
        )
        if st.button("Add Footage", type="primary", key="ws_add_footage"):
            if not uploaded:
                note("Choose one or more files, then select Add Footage.")
            else:
                saved = _save_uploads(uploaded)
                st.session_state["betty_flash"] = (
                    f"Saved {len(saved)} file{'s' if len(saved) != 1 else ''} to the library. "
                    "I will use available footage on the next create pass. "
                    "If a piece still needs specific clips, mark them or adapt the plan."
                )
                nav.goto_workspace("create", piece_id=piece.record.piece_id)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Choose from Library", key="ws_lib"):
                nav.set_interrupted_flow(
                    {
                        "return_to": "workspace",
                        "stage": "capture",
                        "piece_id": piece.record.piece_id,
                    }
                )
                nav.clear_contextual_page()
                nav.goto("Library")
        with c2:
            if st.button("Adapt plan to available footage", key="ws_adapt"):
                nav.goto_workspace("plan", piece_id=piece.record.piece_id)


def _save_uploads(uploaded) -> list[Path]:
    from src.common import ASSETS_MEDIA_DIR

    ASSETS_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for file in uploaded:
        path = ASSETS_MEDIA_DIR / file.name
        path.write_bytes(file.getbuffer())
        saved.append(path)
    return saved


def _default_shots(piece) -> list[str]:
    from pathlib import Path

    assets = list(piece.record.source_assets or [])
    if assets:
        return [Path(a).name for a in assets[:5]]
    return piece.missing_inputs[:5] or ["Source footage for this piece"]


# --- Create -----------------------------------------------------------------

def _stage_create(state: CampaignState, continuation) -> None:
    section("Create")
    piece = _focus_piece(state, continuation)
    version = _focus_version(state, continuation)

    if continuation.current_state == "processing":
        quiet("I’m selecting, editing, and finishing the strongest version.")
        return

    with st.container(border=True):
        if version is not None and finish_records_for_version(version):
            quiet("A finished draft already exists for this work.")
            if st.button("Review Draft", type="primary", key="ws_to_decide"):
                nav.goto_workspace("decide", version_key=version.key)
            return

        ready = bool(
            version
            or (piece is not None and piece.status_key == "ready_to_render")
        )
        quiet("I have everything I need." if ready else continuation.message)
        st.write("")
        if st.button("Create Best Draft", type="primary", key="ws_create_best"):
            _run_create_best(state, piece, version)

        # Logo missing resume hook
        if st.session_state.get("logo_needed_missing"):
            blocked_state(
                "A logo is recommended but unavailable",
                "I recommend a subtle wordmark on this asset, but no suitable transparent logo is available.",
            )
            if st.button("Add Logo", type="primary", key="ws_add_logo"):
                nav.set_interrupted_flow(
                    {
                        "return_to": "workspace",
                        "stage": "create",
                        "piece_id": piece.record.piece_id if piece else None,
                        "version_key": version.key if version else None,
                    }
                )
                nav.clear_contextual_page()
                nav.goto("Library")


def _run_create_best(state: CampaignState, piece, version) -> None:
    from studio.service import generate_best_edit
    from studio.versions import render_version_id

    target_piece = piece
    if target_piece is None and version is not None:
        for p in state.pieces:
            if version.piece_id and p.record.piece_id == version.piece_id:
                target_piece = p
                break
            if not version.piece_id and p.versions and version in p.versions:
                target_piece = p
                break

    with st.status("Creating your draft…", expanded=True) as status:
        quiet(
            "I’m selecting the strongest footage, applying the brand treatment, "
            "and reviewing the final sequence."
        )

        render_version = version
        if render_version is None and target_piece is not None and target_piece.can_render:
            status.write("Creating the base draft…")
            result = render_piece(
                template_id=target_piece.template_id,
                content_piece_id=target_piece.record.piece_id,
                source_assets=list(target_piece.record.source_assets or []),
                campaign_dir=state.path,
                copy_fields=copy_fields_for_piece(target_piece.record),
                title=target_piece.record.title,
                duration_seconds=15,
                cta_appear_at_seconds=10,
            )
            report(result)
            if not result.ok:
                status.update(label="Could not create the base draft.", state="error")
                return
            st.session_state["betty_flash"] = "Base draft created. Continuing finishing…"
            nav.goto_workspace("create", piece_id=target_piece.record.piece_id)
            return

        if render_version is None:
            if target_piece and target_piece.latest_version:
                render_version = target_piece.latest_version
            elif state.versions:
                render_version = state.versions[-1]
            else:
                status.update(label="Nothing is ready to finish yet.", state="error")
                blocked_state(
                    "I need source media or a draft first",
                    "Add footage in Capture, or confirm the plan includes a supported format.",
                )
                return

        source = render_version.primary_path
        if source is None or not source.is_file():
            status.update(label="The draft file is missing.", state="error")
            return

        status.write("Finishing with Brand Guide and Production Rules…")
        campaign_id = state.path.name if state.path else "campaign"
        parent_render_id = render_version_id(render_version.version)
        ctx_title = state.piece_title(render_version) or render_version.display_name

        def progress(msg: str) -> None:
            status.write(msg)

        try:
            outcome = generate_best_edit(
                render_folder=render_version.folder,
                campaign_id=campaign_id,
                content_piece_id=render_version.piece_id,
                template_id=render_version.template_id,
                parent_render_version_id=parent_render_id,
                source_file=source,
                brand_id=DEFAULT_BRAND_ID,
                platform=_platform_for(state, render_version),
                campaign_goal=state.goal,
                progress=progress,
            )
        except Exception as exc:  # noqa: BLE001 — surface plainly
            status.update(label="I could not finish this draft.", state="error")
            blocked_state("Creation stopped", str(exc).splitlines()[-1])
            with st.expander("View Technical Details", expanded=False):
                st.code(str(exc))
            return

        if not outcome.get("ok"):
            status.update(label="I could not finish this draft.", state="error")
            blocked_state("Creation stopped", str(outcome.get("error") or "Unknown error"))
            return

        status.update(label=f"Draft ready for {ctx_title}.", state="complete")
        st.session_state["betty_flash"] = "I finished the strongest version."
        st.session_state["studio_pending_version_key"] = render_version.key
        nav.goto_workspace("decide", version_key=render_version.key)


def _platform_for(state: CampaignState, version) -> str:
    title_piece = None
    for piece in state.pieces:
        if version.piece_id and piece.record.piece_id == version.piece_id:
            title_piece = piece
            break
    if title_piece and title_piece.record.platform:
        return title_piece.record.platform
    return (state.platforms[0] if state.platforms else "Instagram")


# --- Decide -----------------------------------------------------------------

def _stage_decide(state: CampaignState, continuation) -> None:
    section("Decide")
    version = _focus_version(state, continuation)
    if version is None:
        # Fall back to first awaiting / needs revision / latest
        awaiting = [v for v in state.versions if v.is_latest and v.approval_status == "awaiting_review"]
        needs = [v for v in state.versions if v.is_latest and v.approval_status == "needs_revision"]
        version = (awaiting or needs or state.versions or [None])[-1] if state.versions else None
        if awaiting:
            version = awaiting[0]
        elif needs:
            version = needs[0]
        elif state.versions:
            version = max(state.versions, key=lambda v: (v.is_latest, v.version))

    if version is None:
        empty_state("No draft to review yet", "Create a best draft first.")
        if st.button("Create Best Draft", type="primary"):
            nav.goto_workspace("create")
        return

    finishes = finish_records_for_version(version)
    active = next((f for f in finishes if f.status == "ready_for_review"), None)
    if active is None and finishes:
        active = finishes[-1]

    title = state.piece_title(version) or version.display_name
    platform = _platform_for(state, version)

    with st.container(border=True):
        st.markdown(f'<div class="betty-section">Draft ready</div>', unsafe_allow_html=True)
        quiet(f"{title} · {platform}")

        preview = None
        if active is not None:
            from studio.paths import finish_version_dir

            folder = finish_version_dir(version.folder, active.finish_version_id)
            out_dir = folder / "outputs"
            if out_dir.is_dir():
                candidates = sorted(out_dir.iterdir())
                media = [
                    p
                    for p in candidates
                    if p.suffix.lower() in {".mp4", ".mov", ".png", ".jpg", ".jpeg"}
                ]
                preview = media[0] if media else None
        if preview is None and version.primary_path:
            preview = version.primary_path
        if preview and preview.is_file():
            _show_preview_path(preview)
        else:
            media_preview(version)

        decision_lines = _decision_lines(active)
        if decision_lines:
            st.write("")
            section("Creative Director note")
            for line in decision_lines[:3]:
                st.markdown(f"- {line}")

        st.write("")
        if st.button("Approve", type="primary", key="ws_approve"):
            result = save_version_decision(
                state.path, version=version, status="approved", note=""
            )
            report(result)
            if result.ok:
                st.session_state["betty_flash"] = "Approved. Your publishing package is ready."
                nav.goto_workspace("deliver")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Needs Revision", key="ws_needs_rev"):
                st.session_state["ws_show_revision"] = True
                st.rerun()
        with c2:
            if st.button("Reject", key="ws_reject"):
                result = save_version_decision(
                    state.path, version=version, status="rejected", note=""
                )
                report(result)
                if result.ok:
                    st.session_state["betty_flash"] = "Rejected. This version will not be delivered."
                    st.rerun()

    if st.session_state.get("ws_show_revision"):
        with st.container(border=True):
            section("What should change?")
            quiet("Describe the problem in plain language.")
            feedback = st.text_area(
                "Feedback",
                placeholder="The pacing feels rushed. The CTA feels disconnected.",
                key="ws_revision_text",
                height=100,
            )
            if st.button("Apply Revision", type="primary", key="ws_apply_rev"):
                if not feedback.strip():
                    note("Add a short note so I know what to change.")
                else:
                    _apply_natural_revision(state, version, active, feedback.strip())

    with st.expander("Version History", expanded=False):
        for v in sorted(state.versions, key=lambda x: (x.template_id, x.version), reverse=True):
            quiet(
                f"{state.describe(v)} · {v.approval_status.replace('_', ' ')}"
            )

    with st.expander("View Creative Review Details", expanded=False):
        from ui.screens import review as review_screen

        quiet("Full Creative Director Review tools.")
        if st.button("Open full review tools", key="ws_full_review"):
            st.session_state["ws_embed_review"] = True
            st.rerun()
        if st.session_state.get("ws_embed_review"):
            review_screen.render(state)


def _decision_lines(active) -> list[str]:
    if active is None:
        return []
    decision = active.edit_decision or {}
    if not isinstance(decision, dict):
        return []
    lines = []
    for key in ("major_decision_summaries", "key_decisions"):
        for item in decision.get(key) or []:
            text = str(item).strip()
            if text:
                lines.append(text)
    if not lines:
        rationale = decision.get("rationale") or decision.get("overall_judgment")
        if rationale:
            lines.append(str(rationale).strip())
    return lines[:3]


def _apply_natural_revision(state, version, active, feedback: str) -> None:
    from studio.service import revise_best_edit

    save_version_decision(state.path, version=version, status="needs_revision", note=feedback)
    if active is None:
        st.session_state["betty_flash"] = (
            "I recorded your feedback. Create a finished draft first so I can apply supported revisions."
        )
        nav.goto_workspace("create", version_key=version.key)
        return

    with st.status("I’m addressing your feedback…", expanded=True) as status:
        try:
            outcome = revise_best_edit(
                brand_id=DEFAULT_BRAND_ID,
                render_folder=version.folder,
                finish_version_id=active.finish_version_id,
                revision_note=feedback,
            )
            if isinstance(outcome, dict) and not outcome.get("ok", True):
                status.update(label="I could not apply that revision automatically.", state="error")
                blocked_state(
                    "Revision needs another path",
                    str(outcome.get("error") or "Use Advanced review tools for a supported change."),
                )
                return
            status.update(label="I revised the draft.", state="complete")
            st.session_state["ws_show_revision"] = False
            st.session_state["betty_flash"] = "I revised the draft. Review the new version."
            nav.goto_workspace("decide", version_key=version.key)
        except Exception as exc:  # noqa: BLE001
            status.update(label="I could not apply that revision automatically.", state="error")
            blocked_state(
                "Revision needs another path",
                f"{str(exc).splitlines()[-1]} You can use Advanced review tools to apply a supported change.",
            )


def _show_preview_path(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov"}:
        st.video(str(path))
    elif suffix in {".png", ".jpg", ".jpeg"}:
        st.image(str(path), use_container_width=True)
    else:
        quiet(path.name)


# --- Deliver ----------------------------------------------------------------

def _stage_deliver(state: CampaignState, continuation) -> None:
    section("Ready to deliver")
    approved = state.approved_versions
    if not approved and state.export_count == 0:
        empty_state(
            "Nothing approved yet",
            "Approve a draft in Decide before downloading a publishing package.",
        )
        if st.button("Review Draft", type="primary"):
            nav.goto_workspace("decide")
        return

    plan = build_plan(state, mode=PUBLISHING_MODE, selected_keys=set())
    summary = plan.summary
    with st.container(border=True):
        if plan.is_blocked or plan.is_empty:
            st.markdown("**Publishing package blocked**")
            for blocker in plan.blockers or ["No publishable final assets."]:
                quiet(blocker)
        else:
            st.markdown("**Publishing package ready**")

        st.write("")
        quiet("Included:")
        if summary.included_lines:
            for line in summary.included_lines:
                st.markdown(f"- {line}")
        elif plan.included:
            for item in plan.included:
                st.markdown(f"- {item.label}")
        else:
            quiet("Nothing publishable yet.")

        if summary.excluded_lines or plan.excluded:
            st.write("")
            quiet("Excluded:")
            for line in summary.excluded_lines[:12]:
                st.markdown(f"- {line}")
            if len(summary.excluded_lines) > 12:
                quiet(f"…and {len(summary.excluded_lines) - 12} more.")

        if plan.warnings:
            st.write("")
            note("Warnings")
            for warning in plan.warnings:
                quiet(warning)
            acknowledge = st.checkbox(
                "I understand these warnings",
                key="ws_ack_warnings",
            )
        else:
            acknowledge = True

        st.write("")
        cols = st.columns([1, 1])
        with cols[0]:
            create_disabled = plan.is_empty or plan.is_blocked or (
                plan.validation_status == "ready_with_warnings" and not acknowledge
            )
            if st.button(
                "Create Publishing Package",
                type="primary",
                key="ws_download",
                disabled=create_disabled,
            ):
                result = create_export_package(
                    state,
                    mode=PUBLISHING_MODE,
                    selected_keys=set(),
                    acknowledge_warnings=acknowledge,
                )
                if result.ok and result.path:
                    st.session_state["betty_flash"] = "Publishing package ready."
                    st.session_state["ws_last_export"] = str(result.path)
                    st.rerun()
                else:
                    report(result)
        with cols[1]:
            if st.button("Review Exclusions", key="ws_pkg_contents"):
                st.session_state["ws_show_plan"] = True
                st.rerun()

        last = st.session_state.get("ws_last_export")
        if last and Path(last).is_file():
            st.write("")
            st.download_button(
                "Save ZIP",
                data=Path(last).read_bytes(),
                file_name=Path(last).name,
                mime="application/zip",
                type="primary",
                key="ws_zip_dl",
            )
            quiet(f"{Path(last).name} · {human_size(Path(last).stat().st_size)}")

    if st.session_state.get("ws_show_plan"):
        with st.expander("Exclusions and lineage", expanded=True):
            key_values(
                [
                    ("Publishable items", len(plan.included)),
                    ("Excluded", len(plan.excluded)),
                    ("Duplicates removed", len(plan.duplicates_removed)),
                    ("Earlier packages", len(list_existing_packages(state))),
                ]
            )
            for item in plan.included:
                lineage = item.finish_version_id or item.render_version_id or ""
                quiet(f"{item.label} · {item.platform} · {lineage}")
            for exclusion in plan.excluded:
                quiet(f"{exclusion.label} — {exclusion.reason}")

    packages = list_existing_packages(state)
    if packages:
        with st.expander("Earlier packages", expanded=False):
            for path, created, size in packages[:5]:
                quiet(f"{path.name} · {created} · {size}")
                if path.is_file():
                    st.download_button(
                        f"Download {path.name}",
                        data=path.read_bytes(),
                        file_name=path.name,
                        key=f"ws_pkg_{path.name}",
                    )


# --- Journal + Advanced -----------------------------------------------------

def _journal_panel(state: CampaignState) -> None:
    entries = journal_for_campaign(state)
    if not entries:
        return
    with st.expander("Creative Journal", expanded=False):
        current_date = None
        for entry in entries:
            if entry.date_label != current_date:
                current_date = entry.date_label
                st.markdown(f"**{current_date}**")
            quiet(entry.text)


def _advanced_panel(state: CampaignState, stage_key: str) -> None:
    with st.expander("Advanced / Diagnostics", expanded=False):
        quiet("Pipeline tools remain available for debugging and exceptional adjustments.")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Content & Render tools", key="adv_create"):
                st.session_state["ws_embed"] = "create"
                st.rerun()
            if st.button("Automatic Studio controls", key="adv_studio"):
                st.session_state["ws_embed"] = "studio"
                st.rerun()
        with c2:
            if st.button("Creative Review tools", key="adv_review"):
                st.session_state["ws_embed"] = "review"
                st.rerun()
            if st.button("All campaign decisions", key="adv_approvals"):
                st.session_state["ws_embed"] = "approvals"
                st.rerun()
        with c3:
            if st.button("Advanced Delivery Options", key="adv_export"):
                st.session_state["ws_embed"] = "export"
                st.rerun()
            quiet(f"Internal stage: {stage_key}")
            if state.path:
                quiet(f"Campaign id: {state.path.name}")

        embed = st.session_state.get("ws_embed")
        if embed:
            if st.button("Hide advanced tools", key="adv_hide"):
                st.session_state["ws_embed"] = None
                st.rerun()
            from ui.screens import approvals, create, export, review, studio

            if embed == "create":
                create.render(state)
            elif embed == "studio":
                studio.render(state)
            elif embed == "review":
                review.render(state)
            elif embed == "approvals":
                approvals.render(state)
            elif embed == "export":
                export.render(state)


# --- Focus helpers ----------------------------------------------------------

def _focus_piece(state: CampaignState, continuation):
    piece_id = continuation.focus_piece_id or nav.selected_piece_id()
    if piece_id:
        for piece in state.pieces:
            if piece.record.piece_id == piece_id:
                return piece
    missing = [p for p in state.pieces if p.status_key == "missing_inputs"]
    if missing:
        return missing[0]
    ready = [p for p in state.pieces if p.status_key == "ready_to_render"]
    if ready:
        return ready[0]
    return state.pieces[0] if state.pieces else None


def _focus_version(state: CampaignState, continuation):
    key = continuation.focus_version_key or nav.focus_version_key()
    if key:
        for version in state.versions:
            if version.key == key:
                return version
    return None


def _source_summary(piece) -> str:
    from pathlib import Path

    if piece.missing_inputs:
        return f"{len(piece.missing_inputs)} item(s) still needed"
    assets = list(piece.record.source_assets or [])
    if not assets:
        return "No source media listed"
    names = ", ".join(Path(a).name for a in assets[:3])
    if len(assets) > 3:
        names += f" +{len(assets) - 3} more"
    return names
