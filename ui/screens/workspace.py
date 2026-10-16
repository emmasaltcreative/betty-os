"""Guided campaign workspace — Brief → Plan → Capture → Create → Decide → Deliver.

Pipeline tools (Create, Studio, Review, Approvals, Export) remain available under
Advanced. The ordinary path is one progression with one primary action.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.common import DEFAULT_BRAND_ID
from ui import nav
from ui.campaign_state import CampaignState, active_finish_for_decide, finish_records_for_version
from ui.components import (
    blocked_state,
    compact_media_preview,
    empty_state,
    focus_bar,
    key_values,
    media_preview,
    note,
    page_header,
    quiet,
    report,
    saved_note,
    section,
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
    # Stage is driven by deep links / continuation — not a second permanent menu.
    selected = st.session_state.get(STAGE_WIDGET_KEY) or st.session_state.get(
        STAGE_STATE_KEY, default_label
    )
    if selected not in STAGE_OPTIONS:
        selected = default_label
        st.session_state[STAGE_STATE_KEY] = selected
        st.session_state[STAGE_WIDGET_KEY] = selected
    else:
        st.session_state[STAGE_STATE_KEY] = selected

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

    if not st.session_state.get("betty_focus_mode", True):
        _journal_panel(state)
    _advanced_panel(state, stage_key)


def _header(state: CampaignState, continuation) -> None:
    stage = Status(
        continuation.current_state,
        continuation.founder_stage_label,
        campaign_status(state.stage).tone,
    )
    # Compact campaign chrome — workflow stage is contextual, not a second app menu.
    focus_bar(
        campaign=state.name,
        step=KEY_TO_LABEL.get(continuation.current_stage, continuation.founder_stage_label),
        estimate=continuation.estimated_effort,
        action=continuation.primary_action.label,
    )
    cols = st.columns([1, 1, 1], gap="small")
    with cols[0]:
        if st.button("Campaign Overview", use_container_width=True, key="ws_overview"):
            nav.clear_contextual_page()
            st.session_state["campaign_shell_tab"] = "Overview"
            nav.goto("Campaigns")
    with cols[1]:
        if st.button("Today", use_container_width=True, key="ws_today"):
            nav.clear_contextual_page()
            nav.goto("Today")
    with cols[2]:
        if st.button("Timeline", use_container_width=True, key="ws_timeline"):
            st.session_state["ws_show_timeline"] = not st.session_state.get(
                "ws_show_timeline", False
            )
            st.rerun()
    if st.session_state.get("ws_show_timeline"):
        from ui.timeline import render_timeline

        with st.container(border=True):
            render_timeline(state)
    # Compact stage progress — not a competing navigation row.
    quiet(
        " · ".join(
            f"{'●' if key == continuation.current_stage else '○'} {label}"
            for key, label in WORKSPACE_STAGES
        )
    )
    _ = stage  # badge reserved for advanced/full view if re-enabled


def _resolve_stage_label(stage_key: str) -> str:
    return KEY_TO_LABEL.get(stage_key, "Plan")


# --- Brief ------------------------------------------------------------------

def _stage_brief(state: CampaignState, continuation) -> None:
    from src.platforms import PLATFORM_OPTIONS, multiselect_platform_defaults
    from ui.intelligence_ui import render_brief_intelligence_inputs

    section("What are we trying to accomplish?")
    quiet(continuation.message)
    with st.container(border=True):
        goal = st.text_area("Campaign goal", value=state.goal if state.goal != "No goal recorded" else "", height=100)
        platform_defaults = multiselect_platform_defaults(
            state.platforms,
            st.session_state.get("campaign_platforms"),
            fallback=("Instagram", "Pinterest"),
            source="workspace.brief",
        )
        platforms = st.multiselect(
            "Platforms",
            list(PLATFORM_OPTIONS),
            default=platform_defaults,
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

    if state.path is not None:
        default_goal = ""
        if state.goal and state.goal != "No goal recorded":
            default_goal = state.goal
        render_brief_intelligence_inputs(state.path, default_goal=default_goal)


# --- Plan -------------------------------------------------------------------

def _stage_plan(state: CampaignState, continuation) -> None:
    from ui.intelligence_ui import (
        accept_plan_with_brief,
        render_plan_intelligence,
        render_production_brief_success,
    )

    # Accepted plan success state: Production Brief (not a permanent top-level tab)
    if state.path is not None and (
        st.session_state.get("ws_brief_ready") or _has_production_brief(state.path)
    ):
        render_production_brief_success(state.path)
        with st.expander("View content plan", expanded=False):
            _render_content_plan_card(state, continuation)
        return

    section("Recommended direction")
    if state.path is not None:
        render_plan_intelligence(state.path, piece_count=max(1, len(state.pieces) or 5))
        st.write("")

    if not state.pieces:
        empty_state(
            "No campaign content yet",
            "Create or replan this campaign so I can recommend what to make.",
        )
        if st.button("Start Planning", type="primary"):
            nav.clear_contextual_page()
            nav.goto("Campaigns")
        return

    _render_content_plan_card(state, continuation, accept_with_brief=True)


def _has_production_brief(campaign_dir: Path) -> bool:
    from src.campaign_intelligence import newest_brief, resolve_brief_file

    record = newest_brief(campaign_dir)
    if record is None:
        return False
    return resolve_brief_file(campaign_dir, record) is not None


def _render_content_plan_card(state: CampaignState, continuation, *, accept_with_brief: bool = False) -> None:
    from ui.intelligence_ui import accept_plan_with_brief

    piece = _focus_piece(state, continuation)
    if piece is None:
        return
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
            if accept_with_brief and state.path is not None:
                from src.campaign_intelligence import load_intelligence, plan_campaign_intelligence
                from src.campaign_intelligence.models import CampaignInputs

                if load_intelligence(state.path) is None:
                    from src.platforms import multiselect_platform_defaults

                    plan_campaign_intelligence(
                        campaign_dir=state.path,
                        campaign_name=state.name,
                        inputs=CampaignInputs(
                            business_objective=st.session_state.get(
                                "campaign_goal",
                                state.goal
                                if state.goal != "No goal recorded"
                                else "grow the waitlist",
                            ),
                            preferred_platforms=multiselect_platform_defaults(
                                state.platforms,
                                st.session_state.get("campaign_platforms"),
                                fallback=("Instagram", "Pinterest"),
                                source="workspace.accept_plan",
                            ),
                            filming_minutes_available=60,
                        ),
                        piece_count=max(1, len(state.pieces)),
                        persist=True,
                    )
                accept_plan_with_brief(state.path)
                st.session_state["betty_flash"] = "Plan accepted. Production Brief generated."
                st.rerun()
                return
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

    if state.path is not None:
        from ui.intelligence_ui import render_capture_reestimate
        from src.campaign_intelligence import load_intelligence

        planned = len(required)
        intel = load_intelligence(state.path)
        if intel and intel.production_session:
            planned = len([s for s in intel.production_session.shots if s.must_have]) or planned
        render_capture_reestimate(state.path, planned)


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

    job = st.session_state.get("betty_create_job")
    if isinstance(job, dict) and job.get("status") == "running":
        quiet("Creating Asset…")
        st.button("Creating Asset…", type="primary", key="ws_create_best", disabled=True)
        return

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
        create_label = "Create Next Asset" if piece is not None else "Create Best Draft"
        if st.button(create_label, type="primary", key="ws_create_best"):
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
    from uuid import uuid4

    from studio.service import generate_best_edit
    from studio.versions import render_version_id
    from ui.campaign_state import build_campaign_state

    existing = st.session_state.get("betty_create_job")
    if isinstance(existing, dict) and existing.get("status") == "running":
        return
    job_id = uuid4().hex
    st.session_state["betty_create_job"] = {
        "id": job_id,
        "status": "running",
        "piece_id": piece.record.piece_id if piece else None,
    }

    target_piece = piece
    if target_piece is None and version is not None:
        for p in state.pieces:
            if version.piece_id and p.record.piece_id == version.piece_id:
                target_piece = p
                break
            if not version.piece_id and p.versions and version in p.versions:
                target_piece = p
                break

    with st.status("Creating Asset…", expanded=True) as status:
        quiet(
            "I’m selecting the strongest footage, applying the brand treatment, "
            "and reviewing the final sequence."
        )

        def _fail(message: str, *, detail: str | None = None) -> None:
            st.session_state["betty_create_job"] = {
                "id": job_id,
                "status": "failed",
                "error": message,
            }
            status.update(label=message, state="error")
            if detail:
                blocked_state("Creation stopped", detail)

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
                _fail("Could not create the base draft.")
                return
            # Same click continues into finishing — no second button press.
            status.write("Base draft ready. Continuing finishing…")
            refreshed = build_campaign_state(state.path)
            target_piece = next(
                (
                    p
                    for p in refreshed.pieces
                    if p.record.piece_id == target_piece.record.piece_id
                ),
                target_piece,
            )
            render_version = target_piece.latest_version if target_piece else None
            state = refreshed

        if render_version is None:
            if target_piece and target_piece.latest_version:
                render_version = target_piece.latest_version
            elif state.versions:
                render_version = state.versions[-1]
            else:
                _fail(
                    "Nothing is ready to finish yet.",
                    detail="Add footage in Capture, or confirm the plan includes a supported format.",
                )
                return

        source = render_version.primary_path
        if source is None or not source.is_file():
            _fail("The draft file is missing.")
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
            _fail("I could not finish this draft.", detail=str(exc).splitlines()[-1])
            with st.expander("View Technical Details", expanded=False):
                st.code(str(exc))
            return

        if not outcome.get("ok"):
            _fail(
                "I could not finish this draft.",
                detail=str(outcome.get("error") or "Unknown error"),
            )
            return

        record = outcome.get("record")
        if record is not None:
            from studio.service import send_to_review

            # Hand the new finish to Decide immediately so an older jade-badge
            # ready_for_review version is not what the user still sees.
            send_to_review(render_version.folder, record.finish_version_id)

        status.update(label=f"Draft ready for {ctx_title}.", state="complete")
        st.session_state["betty_create_job"] = {
            "id": job_id,
            "status": "complete",
            "version_key": render_version.key,
        }
        st.session_state["betty_flash"] = "I finished the strongest version."
        st.session_state["studio_pending_version_key"] = render_version.key
        nav.goto_workspace("decide", version_key=render_version.key)


def _after_approve(state: CampaignState, version, title: str) -> None:
    """Explain campaign progress and recommend the next asset — do not surprise-jump."""
    from src.campaign_meta import (
        coverage_summary,
        ensure_campaign_meta,
        next_recommended_deliverable,
        why_next_matters,
    )
    from ui.campaign_state import build_campaign_state

    refreshed = build_campaign_state(state.path)
    meta = ensure_campaign_meta(
        refreshed.path, objective=refreshed.goal, pieces=refreshed.pieces
    )
    coverage = coverage_summary(meta)
    nxt = next_recommended_deliverable(meta)
    flash = (
        f"{title} approved.\n\n"
        f"Campaign progress: {coverage['progress_label']}."
    )
    if nxt is not None:
        flash += f"\n\nRecommended next: {why_next_matters(nxt)}"
        st.session_state["betty_flash"] = flash
        if nxt.status == "in_review":
            nav.goto_workspace("decide", piece_id=nxt.piece_id)
        elif nxt.status == "missing_footage":
            nav.goto_workspace("capture", piece_id=nxt.piece_id)
        else:
            nav.goto_workspace("create", piece_id=nxt.piece_id)
        return
    flash += "\n\nAll required deliverables are ready. Open Publishing to deliver the campaign."
    st.session_state["betty_flash"] = flash
    nav.clear_contextual_page()
    st.session_state["campaign_shell_tab"] = "Publishing"
    nav.goto("Campaigns")


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

REVISION_SHORTCUTS = (
    "Make the copy more on brand",
    "Make it less generic",
    "Make it quieter and more editorial",
    "Improve the opening hook",
    "Adjust the pacing",
    "Change the footage",
    "Improve typography",
    "Other",
)


def _stage_decide(state: CampaignState, continuation) -> None:
    from services.decide_revision import (
        active_job_for_version,
        load_job,
        recover_stale_jobs,
    )

    if state.path:
        recover_stale_jobs(state.path)

    version = _focus_version(state, continuation)
    if version is not None and not _is_user_facing_version(version):
        version = None
    if version is None:
        awaiting = [
            v
            for v in state.versions
            if v.is_latest
            and v.approval_status == "awaiting_review"
            and _is_user_facing_version(v)
        ]
        needs = [
            v
            for v in state.versions
            if v.is_latest
            and v.approval_status == "needs_revision"
            and _is_user_facing_version(v)
        ]
        # Prefer revision-ready / pending review over already-approved.
        if awaiting:
            version = awaiting[0]
        elif needs:
            version = needs[0]
        else:
            pending = [
                v
                for v in state.versions
                if v.is_latest
                and v.approval_status not in {"approved", "rejected"}
                and _is_user_facing_version(v)
            ]
            if pending:
                version = max(pending, key=lambda v: v.version)
            else:
                user_versions = [v for v in state.versions if _is_user_facing_version(v)]
                version = (
                    max(user_versions, key=lambda v: (v.is_latest, v.version))
                    if user_versions
                    else None
                )

    if version is None:
        empty_state("No draft to review yet", "Create a best draft first.")
        if st.button("Create Best Draft", type="primary"):
            nav.goto_workspace("create")
        return

    preferred_finish = st.session_state.get("ws_decide_focus_finish_id")
    job = None
    if state.path:
        job_id = st.session_state.get("ws_revision_job_id")
        if job_id:
            job = load_job(state.path, str(job_id))
        if job is None:
            job = active_job_for_version(state.path, version.key)
        # After a copy revision, prefer the new render version when present.
        if job and job.new_version_key and job.status == "ready":
            for candidate in state.versions:
                if candidate.key == job.new_version_key:
                    version = candidate
                    break
        if job and job.new_finish_version_id and job.status == "ready":
            preferred_finish = job.new_finish_version_id
            st.session_state["ws_decide_focus_finish_id"] = preferred_finish

    active = active_finish_for_decide(version, preferred_finish_id=preferred_finish)
    title = state.piece_title(version) or version.display_name
    platform = _platform_for(state, version)
    decision_lines = _decision_lines(active)
    confidence = _confidence_for(active)

    from ui.decide_media import resolve_decide_media

    decide_media = resolve_decide_media(version, active)

    brand_report = _brand_check_for_decide(version, active, decide_media, job)
    revision_ready = bool(job and job.status == "ready" and job.new_finish_version_id)

    left, right = st.columns([1.05, 1.2], gap="medium")
    with left:
        with st.container(border=True):
            if revision_ready:
                st.markdown(
                    '<div class="betty-section">Revision ready</div>',
                    unsafe_allow_html=True,
                )
                quiet(f"{title} · {platform}")
                if job and job.feedback:
                    quiet(f"Requested change: “{job.feedback}”")
                if job and job.what_changed:
                    quiet("What changed:")
                    for line in job.what_changed:
                        st.markdown(f"- {line}")
            else:
                quiet(f"{title} · {platform}")
                if active and active.approval_status == "approved":
                    quiet("Approved")
            if decide_media.blocking_message:
                blocked_state(
                    "Video output is missing"
                    if decide_media.expects_video
                    else "Preview unavailable",
                    decide_media.blocking_message,
                )
            elif decide_media.canonical is not None:
                compact_media_preview(
                    decide_media.canonical,
                    key=f"decide_{version.key}_{getattr(active, 'finish_version_id', 'none')}",
                    poster=decide_media.poster,
                )
            else:
                media_preview(version, key_prefix="decide_")

            if revision_ready and job and job.plan:
                st.write("")
                quiet("Original")
                quiet(f"“{job.plan.original_copy}”")
                quiet("Revised")
                quiet(f"“{job.plan.proposed_copy}”")
                if job.plan.why_changed:
                    quiet(f"Why it changed · {job.plan.why_changed}")

            # Previous version access
            prior = _prior_approved_finish(version, active)
            if prior is not None and active and prior.finish_version_id != active.finish_version_id:
                if st.button("View previous approved version", key="ws_view_prior_finish"):
                    st.session_state["ws_decide_focus_finish_id"] = prior.finish_version_id
                    st.rerun()

    with right:
        with st.container(border=True):
            st.markdown(
                '<div class="betty-section">Creative Director</div>',
                unsafe_allow_html=True,
            )
            if decision_lines:
                quiet("Why this version won")
                for line in decision_lines[:3]:
                    st.markdown(f"- {line}")
            else:
                quiet("This is the strongest draft for the campaign direction.")
            if confidence:
                quiet(f"Confidence · {confidence}")

            _render_brand_check(brand_report)

            st.write("")
            is_approved = (
                version.approval_status == "approved"
                or (active is not None and active.approval_status == "approved")
            ) and not revision_ready

            if is_approved:
                quiet("Approved")
                note("This version is already approved. Request a revision if something should change.")
                if st.button("Request revision", use_container_width=True, key="ws_needs_rev_approved"):
                    st.session_state["ws_show_revision"] = True
                    st.rerun()
                prior = _prior_approved_finish(version, active)
                if prior is not None and active and prior.finish_version_id != active.finish_version_id:
                    if st.button("Compare with previous", key="ws_compare_prior"):
                        st.session_state["ws_decide_focus_finish_id"] = prior.finish_version_id
                        st.rerun()
            else:
                approve_disabled = (
                    not decide_media.can_approve
                    or brand_report.blocking
                    or (job is not None and job.is_active)
                )
                if approve_disabled and decide_media.blocking_message:
                    note(decide_media.blocking_message)
                elif brand_report.blocking:
                    note("Brand Check has a blocking issue. Fix it before approving.")
                if st.button(
                    "Approve",
                    type="primary",
                    use_container_width=True,
                    key="ws_approve",
                    disabled=approve_disabled,
                ):
                    result = save_version_decision(
                        state.path, version=version, status="approved", note=""
                    )
                    if active is not None:
                        from studio.service import set_finish_approval

                        set_finish_approval(
                            render_folder=version.folder,
                            finish_version_id=active.finish_version_id,
                            brand_id=DEFAULT_BRAND_ID,
                            approval_status="approved",
                        )
                    report(result)
                    if result.ok:
                        st.session_state.pop("ws_revision_job_id", None)
                        st.session_state.pop("ws_decide_focus_finish_id", None)
                        _after_approve(state, version, title)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Needs Revision", use_container_width=True, key="ws_needs_rev"):
                        st.session_state["ws_show_revision"] = True
                        st.rerun()
                with c2:
                    if st.button("Reject", use_container_width=True, key="ws_reject"):
                        result = save_version_decision(
                            state.path, version=version, status="rejected", note=""
                        )
                        report(result)
                        if result.ok:
                            st.session_state["betty_flash"] = (
                                "Rejected. This version will not be delivered."
                            )
                            st.rerun()

            _render_revision_panel(state, version, active, job)

            with st.expander("Creative Journal", expanded=False):
                from ui.journal import journal_for_campaign

                entries = journal_for_campaign(state)
                if not entries:
                    quiet("No journal entries yet.")
                else:
                    for entry in entries[:4]:
                        quiet(entry.text)

    with st.expander("Version details", expanded=False):
        quiet("Internal version history for troubleshooting.")
        for v in sorted(state.versions, key=lambda x: (x.template_id, x.version), reverse=True)[:12]:
            quiet(f"{state.describe(v)} · {v.approval_status.replace('_', ' ')}")


def _brand_check_for_decide(version, active, decide_media, job) -> "BrandCheckReport":
    from services.brand_compliance import BrandCheckReport, evaluate_brand_compliance

    if job and job.brand_check:
        data = job.brand_check
        items = []
        from services.brand_compliance import BrandCheckItem

        for raw in data.get("items") or []:
            items.append(
                BrandCheckItem(
                    key=str(raw.get("key") or ""),
                    label=str(raw.get("label") or ""),
                    severity=str(raw.get("severity") or "pass"),  # type: ignore[arg-type]
                    detail=str(raw.get("detail") or ""),
                )
            )
        return BrandCheckReport(
            overall=str(data.get("overall") or "pass"),  # type: ignore[arg-type]
            items=items,
            brand_guide_loaded=bool(data.get("brand_guide_loaded")),
            production_rules_loaded=bool(data.get("production_rules_loaded")),
            brand_id=str(data.get("brand_id") or DEFAULT_BRAND_ID),
        )

    copy_text = ""
    if job and job.plan:
        copy_text = job.plan.proposed_copy or job.plan.original_copy
    elif version.folder.is_dir():
        from services.decide_revision import _original_hook

        try:
            copy_text = _original_hook(version.folder)
        except Exception:
            copy_text = ""

    return evaluate_brand_compliance(
        brand_id=DEFAULT_BRAND_ID,
        copy_text=copy_text,
        media_path=decide_media.canonical,
        expects_video=decide_media.expects_video,
    )


def _render_brand_check(brand_report) -> None:
    st.write("")
    st.markdown(
        '<div class="betty-section">Brand Check</div>',
        unsafe_allow_html=True,
    )
    if brand_report.blocking:
        quiet("Needs attention")
    elif brand_report.overall == "warning":
        quiet("Needs attention")
    else:
        quiet("Passed")
    for label in brand_report.passed_labels[:4]:
        st.markdown(f"- {label}")
    for item in brand_report.items:
        if item.severity != "pass":
            detail = f" — {item.detail}" if item.detail else ""
            st.markdown(f"- {item.label}{detail}")
    with st.expander("Brand Check details", expanded=False):
        quiet(
            "BettyOS evaluated this draft against the active Brand Guide and Production Rules."
        )
        for item in brand_report.items:
            quiet(f"{item.severity.upper()} · {item.label}" + (f" · {item.detail}" if item.detail else ""))


def _prior_approved_finish(version, active):
    finishes = finish_records_for_version(version)
    approved = [f for f in finishes if f.approval_status == "approved"]
    if not approved:
        return None
    prior = max(approved, key=lambda f: f.finish_version_id or "")
    if active and prior.finish_version_id == active.finish_version_id:
        older = [f for f in approved if f.finish_version_id != active.finish_version_id]
        if not older:
            return None
        return max(older, key=lambda f: f.finish_version_id or "")
    return prior


def _render_revision_panel(state, version, active, job) -> None:
    from services.decide_revision import (
        execute_revision_job,
        load_job,
        start_revision_job,
        update_plan_copy,
    )

    show = bool(st.session_state.get("ws_show_revision")) or (
        job is not None and job.status not in {"ready", "cancelled"}
    )
    if not show and not (job and job.status == "failed"):
        return

    st.write("")
    quiet("What should change?")

    if job and job.is_active:
        quiet(job.phase_label or "Working on your revision…")
        note("Revision is in progress. This action is locked until it finishes.")
        return

    if job and job.awaiting_confirmation and job.plan:
        st.markdown(
            '<div class="betty-section">Revision plan</div>',
            unsafe_allow_html=True,
        )
        for line in job.plan.summary_lines:
            st.markdown(f"- {line}")
        st.write("")
        quiet("Original")
        quiet(f"“{job.plan.original_copy}”")
        edited = st.text_area(
            "Revised copy",
            value=job.plan.proposed_copy,
            key=f"ws_rev_proposed_{job.job_id}",
            height=80,
        )
        if job.plan.why_changed:
            quiet(f"Why it changed · {job.plan.why_changed}")
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            if st.button("Use this revision", type="primary", key="ws_use_rev"):
                if edited.strip() != job.plan.proposed_copy:
                    update_plan_copy(state.path, job, edited.strip())
                    job = load_job(state.path, job.job_id) or job
                _execute_revision_with_phases(state, version, active, job)
        with a2:
            if st.button("Edit revision", key="ws_edit_rev"):
                note("Edit the revised copy above, then choose Use this revision.")
        with a3:
            if st.button("Try another direction", key="ws_try_rev"):
                from services.decide_revision import propose_copy_revision

                proposed, why = propose_copy_revision(
                    feedback=job.feedback + " Try another quieter direction.",
                    original=job.plan.original_copy,
                    campaign_goal=state.goal or "",
                )
                update_plan_copy(state.path, job, proposed)
                if job.plan:
                    job.plan.why_changed = why
                    from services.decide_revision import save_job

                    save_job(state.path, job)
                st.rerun()
        with a4:
            if st.button("Cancel", key="ws_cancel_rev"):
                job.status = "cancelled"
                from services.decide_revision import PHASE_LABELS, save_job

                job.phase_label = PHASE_LABELS["cancelled"]
                save_job(state.path, job)
                st.session_state["ws_show_revision"] = False
                st.session_state.pop("ws_revision_job_id", None)
                st.rerun()
        return

    if job and job.status == "failed":
        blocked_state(
            "Revision could not finish",
            job.error or "Something stopped this revision. Your feedback is preserved.",
        )
        if st.button("Retry Revision", type="primary", key="ws_retry_rev"):
            st.session_state["ws_revision_text"] = job.feedback
            st.session_state["ws_show_revision"] = True
            st.session_state.pop("ws_revision_job_id", None)
            # Force a fresh job on next apply by clearing failed id focus
            _start_revision_from_feedback(state, version, active, job.feedback)
        return

    shortcut = st.selectbox(
        "Shortcut",
        options=[""] + list(REVISION_SHORTCUTS),
        format_func=lambda x: "Optional shortcut…" if not x else x,
        key="ws_revision_shortcut",
    )
    if shortcut and shortcut != "Other" and not (st.session_state.get("ws_revision_text") or "").strip():
        st.session_state["ws_revision_text"] = shortcut
    feedback = st.text_area(
        "Feedback",
        placeholder="The pacing feels rushed. The CTA feels disconnected.",
        key="ws_revision_text",
        height=80,
        label_visibility="collapsed",
    )
    applying = st.session_state.get("ws_revision_applying")
    if st.button(
        "Apply Revision",
        type="primary",
        key="ws_apply_rev",
        disabled=bool(applying),
    ):
        note_text = (st.session_state.get("ws_revision_text") or feedback or "").strip()
        if not note_text:
            note("Add a short note so I know what to change.")
        else:
            _start_revision_from_feedback(state, version, active, note_text)


def _start_revision_from_feedback(state, version, active, feedback: str) -> None:
    from services.decide_revision import start_revision_job

    if active is None:
        st.session_state["betty_flash"] = (
            "I recorded your feedback. Create a finished draft first so I can apply supported revisions."
        )
        nav.goto_workspace("create", version_key=version.key)
        return

    st.session_state["ws_revision_applying"] = True
    try:
        with st.status("Interpreting your feedback", expanded=True) as status:
            status.write("Reviewing the Brand Guide")
            job = start_revision_job(
                campaign_dir=state.path,
                version_key=version.key,
                finish_version_id=active.finish_version_id,
                feedback=feedback,
                render_folder=version.folder,
                campaign_goal=state.goal or "",
                brand_id=DEFAULT_BRAND_ID,
            )
            st.session_state["ws_revision_job_id"] = job.job_id
            st.session_state["ws_show_revision"] = True
            if job.status == "failed":
                status.update(label="Revision stopped", state="error")
            else:
                status.update(label="Revision plan ready", state="complete")
    finally:
        st.session_state["ws_revision_applying"] = False
    st.rerun()


def _execute_revision_with_phases(state, version, active, job) -> None:
    from services.decide_revision import execute_revision_job, load_job

    st.session_state["ws_revision_applying"] = True
    try:
        with st.status(job.phase_label or "Preparing the revision", expanded=True) as status:

            def progress(msg: str) -> None:
                status.update(label=msg, state="running")
                status.write(msg)

            updated = execute_revision_job(
                campaign_dir=state.path,
                job=job,
                version=version,
                active=active,
                brand_id=DEFAULT_BRAND_ID,
                campaign_goal=state.goal or "",
                platform=_platform_for(state, version),
                progress=progress,
            )
            if updated.status == "ready":
                status.update(label="Revision ready", state="complete")
                st.session_state["ws_decide_focus_finish_id"] = updated.new_finish_version_id
                st.session_state["ws_revision_job_id"] = updated.job_id
                st.session_state["ws_show_revision"] = False
                st.session_state["betty_flash"] = (
                    "Revision ready. Review the new version — it is not approved yet."
                )
                target_key = updated.new_version_key or version.key
                nav.goto_workspace("decide", version_key=target_key)
            else:
                status.update(label="Revision stopped", state="error")
                st.session_state["ws_revision_job_id"] = updated.job_id
                st.session_state["betty_flash"] = updated.error or "Revision could not finish."
                st.rerun()
    finally:
        st.session_state["ws_revision_applying"] = False


def _resolve_decide_preview(version, active) -> Path | None:
    """Backward-compatible helper — canonical deliverable only, never poster."""
    from ui.decide_media import resolve_decide_media

    return resolve_decide_media(version, active).canonical


def _confidence_for(active) -> str | None:
    if active is None:
        return None
    decision = active.edit_decision or {}
    if not isinstance(decision, dict):
        return None
    for key in ("confidence", "confidence_label", "overall_confidence"):
        value = decision.get(key)
        if value:
            return str(value).replace("_", " ").title()
    scores = decision.get("scores") or {}
    if isinstance(scores, dict) and scores.get("overall") is not None:
        try:
            return f"{float(scores['overall']):.0%}" if float(scores["overall"]) <= 1 else str(scores["overall"])
        except (TypeError, ValueError):
            return str(scores["overall"])
    return "Medium"


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


def _show_preview_path(path: Path) -> None:
    compact_media_preview(path, key=f"path_{path.name}")


# --- Deliver -----------------------------------------------------------------
def _stage_deliver(state: CampaignState, continuation) -> None:
    from datetime import datetime

    approved = state.approved_versions
    if not approved and state.export_count == 0:
        empty_state(
            "Nothing approved yet",
            "Approve a draft in Decide before downloading a campaign package.",
        )
        if st.button("Review Draft", type="primary"):
            nav.goto_workspace("decide")
        return

    from src.campaign_intelligence.downloads import show_in_finder
    from ui.export_service import actionable_incomplete_exclusions

    plan = build_plan(state, mode=PUBLISHING_MODE, selected_keys=set())
    summary = plan.summary
    by_platform = _deliver_platform_groups(plan)

    with st.container(border=True):
        if plan.is_blocked or plan.is_empty:
            st.markdown(
                '<div class="betty-section">Campaign package blocked</div>',
                unsafe_allow_html=True,
            )
            for blocker in plan.blockers or ["No publishable final assets."]:
                quiet(blocker)
            blocking = [
                e for e in actionable_incomplete_exclusions(plan) if e.missing_fields
            ]
            if blocking and st.button("Complete Publishing Copy", key="ws_complete_blocking_copy"):
                st.session_state["ws_complete_excluded"] = True
                st.rerun()
        else:
            st.markdown(
                '<div class="betty-section">Campaign Ready</div>',
                unsafe_allow_html=True,
            )
            key_values(
                [
                    ("Assets", str(summary.ready_item_count or len(plan.included))),
                    ("Package size", human_size(plan.total_bytes) if plan.total_bytes else "—"),
                    ("Runway", _deliver_runway_label(state) or "—"),
                ]
            )
            st.write("")
            for platform, items in by_platform.items():
                st.markdown(
                    f'<div class="betty-platform-block"><div class="plat">{platform.title()}</div>',
                    unsafe_allow_html=True,
                )
                for item in items:
                    label = item.content_type or item.label
                    st.markdown(
                        f'<span class="betty-check">✓</span> {label}',
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

        if plan.summary.blocking_copy_lines or (
            plan.validation_status == "ready_with_warnings" and plan.warnings
        ):
            st.write("")
            note("Required publishing copy needs attention")
            for warning in (plan.summary.blocking_copy_lines or plan.warnings)[:3]:
                quiet(warning)
            if st.button("Complete Publishing Copy", key="ws_complete_selected_copy"):
                st.session_state["ws_complete_excluded"] = True
                st.rerun()
            acknowledge = st.checkbox(
                "I understand these warnings",
                key="ws_ack_warnings",
            )
        else:
            acknowledge = True

        create_disabled = plan.is_empty or plan.is_blocked
        if plan.validation_status == "ready_with_warnings" and not acknowledge:
            create_disabled = True

        last = st.session_state.get("ws_last_export")
        last_path = Path(last) if last else None
        package_ready = last_path is not None and last_path.is_file()

        st.write("")
        if package_ready:
            st.markdown("**Package Ready**")
            quiet(
                f"{last_path.name} · {human_size(last_path.stat().st_size)} · "
                f"{datetime.fromtimestamp(last_path.stat().st_mtime).strftime('%-d %b %Y, %H:%M')}"
            )
            st.download_button(
                "Download Campaign Package",
                data=last_path.read_bytes(),
                file_name=last_path.name,
                mime="application/zip",
                type="primary",
                key="ws_zip_dl",
                use_container_width=True,
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Show in Finder", key="ws_pkg_finder", use_container_width=True):
                    ok, message = show_in_finder(last_path)
                    st.session_state["betty_flash"] = message
                    st.rerun()
            with c2:
                if st.button("View Package Contents", key="ws_pkg_contents", use_container_width=True):
                    st.session_state["ws_show_plan"] = True
                    st.rerun()
            with c3:
                if st.button("Rebuild", key="ws_download", use_container_width=True, disabled=create_disabled):
                    _create_campaign_package(state, acknowledge)
        else:
            if st.button(
                "Build Campaign Package",
                type="primary",
                key="ws_download",
                disabled=create_disabled,
                use_container_width=True,
            ):
                _create_campaign_package(state, acknowledge)

    if st.session_state.get("ws_complete_excluded"):
        _deliver_complete_excluded(state, plan)

    if st.session_state.get("ws_show_plan"):
        with st.expander("Package contents", expanded=True):
            quiet(f"Publishable items: {len(plan.included)}")
            for item in plan.included:
                quiet(f"✓ {item.label} · {item.platform}")
            excluded_count = len(plan.excluded)
            if excluded_count:
                quiet(f"{excluded_count} excluded (drafts, superseded, incomplete)")
            if st.button("Hide contents", key="ws_hide_plan"):
                st.session_state["ws_show_plan"] = False
                st.rerun()

    packages = list_existing_packages(state)
    with st.expander("Package archive", expanded=False):
        quiet("Older campaign packages.")
        if not packages:
            quiet("No earlier packages for this campaign.")
        else:
            for path, created, size in packages[:8]:
                is_newest = last_path is not None and path.resolve() == last_path.resolve()
                label = f"{'Newest · ' if is_newest else ''}{path.name} · {created} · {size}"
                quiet(label)
                if path.is_file() and not is_newest:
                    st.download_button(
                        f"Download {path.name}",
                        data=path.read_bytes(),
                        file_name=path.name,
                        key=f"ws_pkg_{path.name}",
                    )


def _create_campaign_package(state: CampaignState, acknowledge: bool) -> None:
    result = create_export_package(
        state,
        mode=PUBLISHING_MODE,
        selected_keys=set(),
        acknowledge_warnings=acknowledge,
    )
    if result.ok and result.path:
        st.session_state["betty_flash"] = "Campaign package ready."
        st.session_state["ws_last_export"] = str(result.path)
        st.rerun()
    else:
        report(result)


def _deliver_platform_groups(plan) -> dict:
    groups = {}
    for item in plan.included:
        platform = (item.platform or "other").lower()
        groups.setdefault(platform, []).append(item)
    order = ["instagram", "pinterest", "carousel", "website", "email", "waitlist", "other"]
    ordered = {key: groups[key] for key in order if key in groups}
    ordered.update({k: v for k, v in groups.items() if k not in order})
    return ordered


def _deliver_runway_label(state: CampaignState):
    if state.path is None:
        return None
    try:
        from src.campaign_intelligence import load_intelligence

        intel = load_intelligence(state.path)
        if intel is None:
            return None
        runway = intel.current_runway()
        if runway is None:
            return None
        return f"{runway.days.min_days}–{runway.days.max_days} days"
    except Exception:
        return None


def _deliver_complete_excluded(state: CampaignState, plan) -> None:
    from ui.publishing_copy_fix import (
        approve_draft,
        edit_draft,
        mark_needs_revision,
        open_completion_session,
        revalidate_after_completion,
    )

    session = st.session_state.get("ws_completion_session")
    if session is None:
        session = open_completion_session(state, plan)
        st.session_state["ws_completion_session"] = session

    with st.expander("Complete excluded publishing copy", expanded=True):
        if not session.drafts:
            quiet("No actionable incomplete records to complete.")
            if st.button("Close", key="ws_complete_close_empty"):
                st.session_state["ws_complete_excluded"] = False
                st.session_state.pop("ws_completion_session", None)
                st.rerun()
            return

        quiet(
            "One Brand Guide-aligned description per record. "
            "Approve to save a clean metadata file. Records enter the package only "
            "when paired with final Pin media."
        )
        for index, draft in enumerate(session.drafts):
            st.markdown(f"**{draft.exclusion.label}**")
            if draft.exclusion.missing_fields:
                quiet(f"Missing: {', '.join(draft.exclusion.missing_fields)}")
            quiet(f"Platform: {draft.platform}")
            if draft.content_piece_id:
                quiet(f"Content piece: {draft.content_piece_id}")
            edited = st.text_area(
                "Description",
                value=draft.description,
                key=f"ws_complete_desc_{index}",
                height=120,
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Approve", key=f"ws_complete_approve_{index}"):
                    approve_draft(draft, text=edited)
                    st.session_state["betty_flash"] = draft.message
                    plan = revalidate_after_completion(state)
                    st.session_state["ws_completion_session"] = open_completion_session(
                        state, plan
                    )
                    st.rerun()
            with c2:
                if st.button("Needs Revision", key=f"ws_complete_needs_{index}"):
                    mark_needs_revision(draft)
                    st.session_state["betty_flash"] = draft.message
                    st.rerun()
            with c3:
                if st.button("Save Edit", key=f"ws_complete_edit_{index}"):
                    edit_draft(draft, edited)
                    st.session_state["betty_flash"] = draft.message
                    st.rerun()
            if draft.message:
                quiet(draft.message)
            st.write("")

        if st.button("Revalidate package", key="ws_complete_revalidate"):
            plan = revalidate_after_completion(state)
            st.session_state["ws_completion_session"] = open_completion_session(state, plan)
            st.session_state["betty_flash"] = (
                f"Revalidated: {plan.summary.readiness_headline}"
            )
            st.rerun()
        if st.button("Close", key="ws_complete_close"):
            st.session_state["ws_complete_excluded"] = False
            st.session_state.pop("ws_completion_session", None)
            st.rerun()


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
        quiet("Workflow stage (troubleshooting)")
        stage_cols = st.columns(len(STAGE_OPTIONS))
        for col, label in zip(stage_cols, STAGE_OPTIONS):
            with col:
                if st.button(label, key=f"adv_stage_{label}", use_container_width=True):
                    st.session_state[STAGE_STATE_KEY] = label
                    st.session_state[STAGE_WIDGET_KEY] = label
                    st.rerun()
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


def _is_user_facing_version(version) -> bool:
    from src.asset_visibility import is_user_facing_asset_folder

    return is_user_facing_asset_folder(getattr(version, "folder", None))


def _focus_version(state: CampaignState, continuation):
    key = continuation.focus_version_key or nav.focus_version_key()
    if key:
        for version in state.versions:
            if version.key == key and _is_user_facing_version(version):
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
