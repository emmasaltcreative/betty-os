"""Campaigns — open, create, and archive campaigns. Nothing else lives here."""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import (
    CampaignState,
    CampaignSummary,
    build_campaign_state,
    list_archived_campaigns,
    list_campaigns,
)
from ui.components import (
    empty_state,
    key_values,
    note,
    page_header,
    quiet,
    report,
    section,
    show_badges,
)
from ui.status import campaign_status
from ui.workflow_service import (
    archive_campaign,
    create_campaign_folder,
    restore_campaign,
    run_ingest_folder,
    run_plan_campaign,
    run_repurpose_package,
)

PLATFORM_OPTIONS = ["Instagram", "Pinterest", "TikTok", "Email", "Waitlist", "YouTube Shorts"]
TIME_OPTIONS = ["30 minutes", "1 hour", "2 hours", "Half day", "Full day"]


def render(state: CampaignState) -> None:
    page_header("Campaigns", "Every campaign, and the one you are working on now.")

    if state.exists:
        _current_campaign(state)

    campaigns = list_campaigns()
    others = [c for c in campaigns if state.path is None or c.path != state.path]

    section("All campaigns" if not state.exists else "Other campaigns")
    if not others:
        if not campaigns:
            empty_state(
                "No campaigns yet",
                "Create your first campaign below to start producing content.",
            )
        else:
            quiet("This is your only active campaign.")
    for summary in others:
        _campaign_row(summary)

    st.write("")
    _create_campaign()
    _archived()


def _current_campaign(state: CampaignState) -> None:
    section("Current campaign", "Where this campaign stands and what comes next.")
    with st.container(border=True):
        show_badges([campaign_status(state.stage)])
        st.markdown(f'<div class="betty-section">{state.name}</div>', unsafe_allow_html=True)
        key_values(
            [
                ("Goal", state.goal),
                ("Stage", campaign_status(state.stage).label),
                ("Next action", state.next_step.label),
                ("Last updated", state.updated_at),
            ]
        )
        if st.button(
            f"Continue: {state.next_step.label}",
            type="primary",
            key="campaigns_continue",
        ):
            from ui.continue_campaign import resolve_continuation

            continuation = resolve_continuation(state)
            nav.goto_workspace(
                continuation.current_stage,
                piece_id=continuation.focus_piece_id,
                version_key=continuation.focus_version_key,
            )


def _campaign_row(summary: CampaignSummary) -> None:
    other = build_campaign_state(summary.path)
    with st.container(border=True):
        columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
        with columns[0]:
            show_badges([campaign_status(other.stage)])
            st.markdown(
                f'<div class="betty-section">{summary.name}</div>', unsafe_allow_html=True
            )
            key_values(
                [
                    ("Goal", other.goal),
                    ("Created", summary.created_at),
                    ("Last updated", summary.updated_at),
                    (
                        "Progress",
                        f"{sum(1 for s in other.steps if s.state == 'complete')} of "
                        f"{len(other.steps)} steps complete",
                    ),
                    ("Current blocker", other.blockers[0] if other.blockers else "None"),
                ]
            )
        with columns[1]:
            if st.button(
                "Open Campaign",
                key=f"open_{summary.path.name}",
                type="primary",
                use_container_width=True,
            ):
                nav.set_active_campaign(summary.path)
                nav.goto_workspace()
            if st.button(
                "Archive",
                key=f"archive_{summary.path.name}",
                use_container_width=True,
                help="Hides the campaign from this list. No files are deleted.",
            ):
                result = archive_campaign(summary.path)
                report(result)
                if result.ok:
                    st.rerun()


def _create_campaign() -> None:
    with st.expander("Create Campaign", expanded=False):
        note(
            "BettyOS reads your media, then writes a set of content pieces for this "
            "campaign. This takes a minute or two."
        )
        with st.form("create_campaign"):
            name = st.text_input("Campaign name", value="The Reading Hour")
            goal = st.text_area(
                "Goal",
                value=st.session_state.get("campaign_goal", ""),
                height=80,
                help="What this campaign should achieve.",
            )
            columns = st.columns(2)
            with columns[0]:
                time_available = st.selectbox("Production time available", TIME_OPTIONS, index=2)
            with columns[1]:
                piece_count = st.number_input(
                    "Content pieces to plan", min_value=1, max_value=12, value=5
                )
            platforms = st.multiselect(
                "Platforms",
                PLATFORM_OPTIONS,
                default=st.session_state.get("campaign_platforms", ["Instagram"]),
            )
            media_folder = st.text_input(
                "Media folder",
                value="assets/reading-hour-shoot",
                help="Folder of photos or video to draw the content from.",
            )
            index_media = st.checkbox("Index this media folder first", value=True)
            notes = st.text_area("Notes for BettyOS (optional)", height=70)
            submitted = st.form_submit_button("Create Campaign", type="primary")

        if not submitted:
            return

        st.session_state["campaign_goal"] = goal
        st.session_state["campaign_platforms"] = platforms or ["Instagram"]

        if index_media and media_folder.strip():
            with st.status("Indexing media…", expanded=True) as status:
                ingest = run_ingest_folder(media_folder.strip())
                report(ingest)
                if not ingest.ok:
                    status.update(label="Could not index that folder.", state="error")
                    return
                status.update(label="Media indexed.", state="complete")

        with st.status("Planning the production session…", expanded=True) as status:
            plan = run_plan_campaign(
                campaign_name=name,
                campaign_goal=goal,
                time_available=time_available,
                platforms=platforms or ["Instagram"],
                notes=notes,
            )
            report(plan)
            if not plan.ok:
                status.update(label="Planning failed.", state="error")
                return
            status.update(label="Production plan written.", state="complete")

        with st.status("Writing campaign content…", expanded=True) as status:
            package = run_repurpose_package(
                campaign_goal=goal,
                platforms=platforms or ["Instagram"],
                content_count=int(piece_count),
                notes=notes or None,
            )
            report(package)
            if not package.ok:
                status.update(label="Content could not be written.", state="error")
                return
            status.update(label="Campaign content written.", state="complete")

        folder = create_campaign_folder()
        report(folder, success_prefix="Campaign created.")
        if folder.ok and folder.path is not None:
            nav.set_active_campaign(folder.path)
            nav.goto_workspace("plan")


def _archived() -> None:
    archived = list_archived_campaigns()
    if not archived:
        return
    with st.expander(f"Archived campaigns ({len(archived)})", expanded=False):
        note("Archived campaigns keep all their files. Restore one to work on it again.")
        for summary in archived:
            columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
            with columns[0]:
                quiet(f"{summary.name} · last updated {summary.updated_at}")
            with columns[1]:
                if st.button(
                    "Restore",
                    key=f"restore_{summary.path.name}",
                    use_container_width=True,
                ):
                    result = restore_campaign(summary.path)
                    report(result)
                    if result.ok:
                        st.rerun()
