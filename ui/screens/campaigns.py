"""Campaigns — list, create, and the campaign shell.

When a campaign is open, Campaigns is the campaign product container:
Overview · Creative · Publishing · Timeline.
"""

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
from src.platforms import PLATFORM_OPTIONS, multiselect_platform_defaults
from src.campaign_meta import (
    coverage_summary,
    ensure_campaign_meta,
    next_recommended_deliverable,
    save_campaign_meta,
    suggest_campaign_title,
    why_next_matters,
    CampaignMeta,
)

TIME_OPTIONS = ["30 minutes", "1 hour", "2 hours", "Half day", "Full day"]
SHELL_TABS = ("Overview", "Creative", "Publishing", "Timeline")


def render(state: CampaignState) -> None:
    if state.exists:
        _campaign_shell(state)
        st.write("")
        with st.expander("All campaigns", expanded=False):
            _campaign_list(state)
            _create_campaign()
            _archived()
        return

    page_header("Campaigns", "Every campaign, and the one you are working on now.")
    _campaign_list(state)
    st.write("")
    _create_campaign()
    _archived()


def _campaign_shell(state: CampaignState) -> None:
    from ui.continue_campaign import resolve_continuation

    meta = ensure_campaign_meta(state.path, objective=state.goal, pieces=state.pieces)
    coverage = coverage_summary(meta)
    next_item = next_recommended_deliverable(meta)
    continuation = resolve_continuation(state)
    runway = _runway_label(state)

    # Title acceptance for migrated timestamp campaigns
    if not meta.title_accepted and meta.display_title:
        with st.container(border=True):
            quiet("Suggested campaign name")
            edited = st.text_input(
                "Campaign name",
                value=meta.display_title,
                key="shell_title_edit",
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Use this name", type="primary", key="shell_accept_title"):
                    meta.display_title = (edited or meta.display_title).strip()
                    meta.title_accepted = True
                    save_campaign_meta(state.path, meta)
                    st.rerun()
            with c2:
                if st.button("Keep editing later", key="shell_defer_title"):
                    meta.title_accepted = True
                    save_campaign_meta(state.path, meta)
                    st.rerun()

    page_header(state.name, state.goal)

    if st.session_state.get("campaign_shell_tab") not in SHELL_TABS:
        st.session_state["campaign_shell_tab"] = "Overview"
    tab = st.radio(
        "Campaign",
        list(SHELL_TABS),
        key="campaign_shell_tab",
        horizontal=True,
        label_visibility="collapsed",
    )

    if tab == "Overview":
        _shell_overview(state, meta, coverage, next_item, continuation, runway)
    elif tab == "Creative":
        _shell_creative(state, meta, coverage, next_item)
    elif tab == "Publishing":
        _shell_publishing(state, meta, coverage)
    else:
        from ui.timeline import render_timeline

        with st.container(border=True):
            render_timeline(state)


def _shell_overview(state, meta, coverage, next_item, continuation, runway) -> None:
    with st.container(border=True):
        key_values(
            [
                ("Status", (meta.readiness or state.stage).replace("_", " ").title()),
                ("Target milestone", meta.milestone_date or "Not set"),
                ("Progress", coverage["progress_label"]),
                ("Estimated runway", runway or "—"),
                (
                    "Recommended cadence",
                    _cadence_label(state) or "—",
                ),
            ]
        )
        st.write("")
        quiet("Planned deliverables")
        for item in meta.deliverables:
            if item.status == "intentionally_removed":
                continue
            mark = "✓" if item.status == "approved" else "·"
            quiet(f"{mark} {item.title} · {item.platform} · {item.status.replace('_', ' ')}")

        if coverage["remaining"]:
            st.write("")
            quiet("Remaining")
            for item in coverage["remaining"]:
                quiet(f"· {item.title}")

        st.write("")
        if next_item is not None:
            st.markdown(
                f'<div class="betty-section">Next: {next_item.title}</div>',
                unsafe_allow_html=True,
            )
            st.write(why_next_matters(next_item))
            if st.button("Continue Campaign", type="primary", key="shell_ov_continue"):
                _open_deliverable(next_item)
        else:
            st.markdown(
                '<div class="betty-section">Campaign ready to deliver</div>',
                unsafe_allow_html=True,
            )
            quiet("All required deliverables are approved.")
            if st.button("Open Publishing", type="primary", key="shell_ov_publish"):
                st.session_state["campaign_shell_tab"] = "Publishing"
                st.rerun()


def _shell_creative(state, meta, coverage, next_item) -> None:
    with st.container(border=True):
        quiet(coverage["progress_label"])
        st.write("")
        for item in meta.deliverables:
            if item.status == "intentionally_removed":
                continue
            cols = st.columns([3, 1], gap="small")
            with cols[0]:
                quiet(f"{item.title}")
                quiet(
                    f"{item.platform} · {item.format_name} · {item.role} · "
                    f"{item.status.replace('_', ' ')}"
                )
                preview = _preview_for_piece(state, item.piece_id)
                if preview is not None:
                    from ui.components import compact_media_preview

                    compact_media_preview(preview, key=f"shell_prev_{item.deliverable_id}")
            with cols[1]:
                if item.status == "approved":
                    quiet("Approved")
                elif st.button("Open", key=f"shell_open_{item.deliverable_id}"):
                    _open_deliverable(item)

        st.write("")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if next_item and st.button(
                "Review Next Recommended", type="primary", key="shell_review_next"
            ):
                _open_deliverable(next_item)
        with c2:
            if st.button("Review Ready Assets", key="shell_review_ready"):
                ready = next(
                    (d for d in meta.deliverables if d.status == "in_review"),
                    None,
                )
                if ready:
                    _open_deliverable(ready)
                else:
                    st.session_state["betty_flash"] = "No assets are waiting for review."
                    st.rerun()
        with c3:
            if st.button("View Approved", key="shell_view_approved"):
                st.session_state["shell_filter"] = "approved"
                st.rerun()
        with c4:
            if st.button("View Gaps", key="shell_view_gaps"):
                st.session_state["shell_filter"] = "gaps"
                st.rerun()

        filt = st.session_state.get("shell_filter")
        if filt == "approved":
            quiet("Approved campaign creative")
            for item in coverage["approved"]:
                quiet(f"✓ {item.title}")
        elif filt == "gaps":
            quiet("Remaining gaps")
            for item in coverage["remaining"]:
                quiet(f"· {item.title} ({item.status.replace('_', ' ')})")

        st.write("")
        from services.brand_compliance import campaign_brand_consistency

        brand = campaign_brand_consistency(state)
        st.markdown(
            '<div class="betty-section">Campaign Brand Consistency</div>',
            unsafe_allow_html=True,
        )
        quiet(f"{brand['checked']} assets checked")
        quiet(f"Passed: {brand['passed']}")
        quiet(f"Needs review: {brand['needs_review']}")
        if brand.get("details"):
            with st.expander("Consistency details", expanded=False):
                for line in brand["details"][:8]:
                    quiet(line)


def _shell_publishing(state, meta, coverage) -> None:
    from datetime import datetime

    from src.campaign_intelligence.downloads import show_in_finder
    from ui.export_service import (
        PUBLISHING_MODE,
        build_plan,
        create_export_package,
        human_size,
        list_existing_packages,
    )

    required_total = coverage["required_total"]
    approved_count = coverage["approved_count"]
    from services.brand_compliance import campaign_has_blocking_brand_failure

    brand_blocked = campaign_has_blocking_brand_failure(state)
    ready = (
        not brand_blocked
        and (
            meta.readiness == "ready_to_deliver"
            or (required_total > 0 and approved_count >= required_total)
        )
    )
    plan = build_plan(state, mode=PUBLISHING_MODE, selected_keys=set())

    with st.container(border=True):
        if brand_blocked:
            st.markdown(
                '<div class="betty-section">Campaign Incomplete</div>',
                unsafe_allow_html=True,
            )
            quiet(
                "A required asset has a blocking Brand Check failure. "
                "The campaign cannot be marked Ready to Deliver until it is fixed."
            )
        elif ready and not plan.is_blocked and not plan.is_empty:
            st.markdown(
                '<div class="betty-section">Campaign Ready</div>',
                unsafe_allow_html=True,
            )
        elif approved_count:
            st.markdown(
                '<div class="betty-section">Campaign Incomplete</div>',
                unsafe_allow_html=True,
            )
            quiet(
                f"{approved_count} of {required_total} required deliverables are ready."
            )
            quiet("Remaining:")
            for item in coverage["remaining"]:
                quiet(f"· {item.title}")
        else:
            st.markdown(
                '<div class="betty-section">Publishing</div>',
                unsafe_allow_html=True,
            )
            quiet("Approve required deliverables before campaign delivery.")

        key_values(
            [
                ("Deliverables", str(required_total or len(plan.included))),
                (
                    "Platforms",
                    str(len({(i.platform or "") for i in plan.included}) or len(state.platforms)),
                ),
                ("Estimated runway", _runway_label(state) or "—"),
            ]
        )

        st.write("")
        quiet("Included")
        by_platform = {}
        for item in meta.deliverables:
            if item.status == "intentionally_removed":
                continue
            by_platform.setdefault(item.platform or "Other", []).append(item)
        for platform, items in by_platform.items():
            quiet(platform)
            for item in items:
                mark = "✓" if item.status == "approved" else "·"
                quiet(f"  {mark} {item.title}")
        quiet("Documents")
        for doc in (
            "Campaign Overview",
            "Production Brief",
            "Posting Plan",
            "Campaign Copybook",
        ):
            quiet(f"  · {doc}")

        st.write("")
        if not ready:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Continue Campaign", type="primary", key="pub_continue"):
                    nxt = next_recommended_deliverable(meta)
                    if nxt:
                        _open_deliverable(nxt)
                    else:
                        nav.goto_workspace("create")
            with c2:
                if st.button("Finalize Without These Items", key="pub_finalize"):
                    st.session_state["shell_finalize"] = True
                    st.rerun()
            if st.session_state.get("shell_finalize"):
                reason = st.text_area(
                    "Why finalize without the remaining items?",
                    key="shell_finalize_reason",
                )
                if st.button("Confirm finalize", type="primary", key="shell_finalize_ok"):
                    if not reason.strip():
                        note("Add a short reason to finalize without remaining items.")
                    else:
                        meta.finalize_without = [
                            d.deliverable_id for d in coverage["remaining"]
                        ]
                        meta.finalize_reason = reason.strip()
                        meta.readiness = "ready_to_deliver"
                        save_campaign_meta(state.path, meta)
                        st.session_state["shell_finalize"] = False
                        st.session_state["betty_flash"] = (
                            "Campaign marked ready without the remaining items."
                        )
                        st.rerun()
            quiet("An advanced working-package export remains available below.")
            if st.button("Build Working Package", key="pub_working"):
                _deliver_package(state, acknowledge=True)
        else:
            last = st.session_state.get("ws_last_export")
            last_path = __import__("pathlib").Path(last) if last else None
            packages = list_existing_packages(state)
            if (last_path is None or not last_path.is_file()) and packages:
                last_path = packages[0][0]
                st.session_state["ws_last_export"] = str(last_path)

            if last_path is not None and last_path.is_file():
                st.markdown(
                    '<div class="betty-section">Campaign Delivery Ready</div>',
                    unsafe_allow_html=True,
                )
                quiet(
                    f"{len(plan.included)} deliverables · "
                    f"{human_size(last_path.stat().st_size)} · "
                    f"Created {datetime.fromtimestamp(last_path.stat().st_mtime).strftime('%-d %b %Y, %-I:%M %p')}"
                )
                st.download_button(
                    "Download Campaign Delivery",
                    data=last_path.read_bytes(),
                    file_name=last_path.name,
                    mime="application/zip",
                    type="primary",
                    key="shell_zip_dl",
                    use_container_width=True,
                )
                a, b = st.columns(2)
                with a:
                    if st.button("Show in Finder", key="shell_finder", use_container_width=True):
                        ok, message = show_in_finder(last_path)
                        st.session_state["betty_flash"] = message
                        st.rerun()
                with b:
                    if st.button("Rebuild Delivery", key="shell_rebuild", use_container_width=True):
                        _deliver_package(state, acknowledge=True)
            else:
                if st.button(
                    "Deliver Campaign",
                    type="primary",
                    key="shell_deliver",
                    disabled=plan.is_empty or plan.is_blocked,
                    use_container_width=True,
                ):
                    _deliver_package(state, acknowledge=True)

    with st.expander("Package archive", expanded=False):
        packages = list_existing_packages(state)
        if not packages:
            quiet("No earlier packages for this campaign.")
        else:
            for path, created, size in packages[:8]:
                quiet(f"{path.name} · {created} · {size}")
                if path.is_file():
                    st.download_button(
                        f"Download {path.name}",
                        data=path.read_bytes(),
                        file_name=path.name,
                        key=f"shell_arch_{path.name}",
                    )


def _deliver_package(state, *, acknowledge: bool) -> None:
    from ui.export_service import PUBLISHING_MODE, create_export_package

    result = create_export_package(
        state,
        mode=PUBLISHING_MODE,
        selected_keys=set(),
        acknowledge_warnings=acknowledge,
    )
    report(result)
    if result.ok and result.path:
        st.session_state["betty_flash"] = "Campaign delivery ready."
        st.session_state["ws_last_export"] = str(result.path)
        st.rerun()


def _open_deliverable(item) -> None:
    if item.status == "in_review":
        nav.goto_workspace("decide", piece_id=item.piece_id)
    elif item.status == "missing_footage":
        nav.goto_workspace("capture", piece_id=item.piece_id)
    elif item.status == "approved":
        nav.goto_workspace("decide", piece_id=item.piece_id)
    else:
        nav.goto_workspace("create", piece_id=item.piece_id)


def _preview_for_piece(state, piece_id: str | None):
    if not piece_id:
        return None
    for version in state.versions:
        if version.piece_id != piece_id:
            continue
        if version.primary_path and version.primary_path.is_file():
            return version.primary_path
    return None


def _runway_label(state) -> str | None:
    try:
        from src.campaign_intelligence import load_intelligence

        intel = load_intelligence(state.path)
        if intel is None:
            return None
        runway = intel.current_runway()
        if runway is None:
            return None
        return f"Approximately {runway.days.max_days} days"
    except Exception:
        return None


def _cadence_label(state) -> str | None:
    try:
        from src.campaign_intelligence import load_intelligence

        intel = load_intelligence(state.path)
        if intel is None or not intel.cadence:
            return None
        parts = [
            f"{c.platform}: {c.min_per_week}–{c.max_per_week}/week"
            for c in intel.cadence
            if getattr(c, "platform", None)
        ]
        return "; ".join(parts) if parts else None
    except Exception:
        return None


def _campaign_list(state: CampaignState) -> None:
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
                st.session_state["campaign_shell_tab"] = "Overview"
                nav.clear_contextual_page()
                nav.goto("Campaigns")
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
            name = st.text_input("Campaign name", value="Reading Hour Waitlist")
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
                list(PLATFORM_OPTIONS),
                default=multiselect_platform_defaults(
                    st.session_state.get("campaign_platforms"),
                    fallback=("Instagram",),
                    source="campaigns.create",
                ),
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
            meta = CampaignMeta(
                display_title=(name.strip() or suggest_campaign_title(goal)),
                objective=goal,
                title_accepted=True,
            )
            save_campaign_meta(folder.path, meta)
            nav.set_active_campaign(folder.path)
            st.session_state["campaign_shell_tab"] = "Overview"
            nav.clear_contextual_page()
            nav.goto("Campaigns")


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
