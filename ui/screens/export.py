"""Export — build a publishing package or an archive dump."""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import CampaignState, count_phrase
from ui.components import (
    Stat,
    blocked_state,
    download_file,
    empty_state,
    item_list,
    key_values,
    note,
    page_header,
    progress_rail,
    quiet,
    section,
    stat_strip,
)
from ui.export_service import (
    ARCHIVE_MODE,
    MODES,
    PUBLISHING_MODE,
    build_plan,
    create_export_package,
    human_size,
    list_existing_packages,
)

RESULT_KEY = "export_result"
MODE_KEYS = [key for key, _, _ in MODES]
MODE_LABELS = {key: label for key, label, _ in MODES}
MODE_HELP = {key: help_text for key, _, help_text in MODES}


def render(state: CampaignState) -> None:
    page_header("Export", "Create a publishing package or an archive dump.")
    progress_rail(state.steps)

    if not state.exists:
        empty_state("No campaign selected", "Open a campaign to export its work.")
        if st.button("Go to Campaigns", type="primary"):
            nav.goto("Campaigns")
        return

    if not state.versions:
        blocked_state(
            "Export unavailable",
            "There is nothing to package. Create and approve at least one render first.",
        )
        if st.button("Go to Create", type="primary"):
            nav.goto("Create", "3. Render")
        return

    counts = state.counts
    approved = state.approved_versions
    stat_strip(
        [
            Stat("Approved", counts["approved"], "positive" if approved else "neutral"),
            Stat(
                "Awaiting decision",
                counts["awaiting_approval"],
                "attention" if counts["awaiting_approval"] else "neutral",
            ),
            Stat("Render versions", counts["renders"]),
            Stat("Packages made", state.export_count),
        ]
    )

    if not approved:
        blocked_state(
            "Export unavailable",
            "Approve at least one valid render before creating an export package.",
        )
        if st.button("Go to Approvals", type="primary", key="export_to_approvals"):
            nav.goto("Approvals")
        st.write("")
        _existing(state)
        return

    mode = st.radio(
        "Package type",
        options=MODE_KEYS,
        format_func=lambda key: MODE_LABELS[key],
        horizontal=True,
        key="export_mode",
        index=0,
    )
    quiet(MODE_HELP[mode])
    if mode == ARCHIVE_MODE:
        note("Archive Package is for history and diagnostics. It is not the default publishing package.")

    plan = build_plan(state, mode=mode, selected_keys=None)
    _plan_preview(plan, mode)
    _create(state, mode, plan)
    st.write("")
    _existing(state)


def _plan_preview(plan, mode: str) -> None:
    section("Publishing package ready" if mode == PUBLISHING_MODE else "Archive contents")
    columns = st.columns([1, 1], gap="large")
    summary = plan.summary

    with columns[0]:
        with st.container(border=True):
            st.markdown('<div class="betty-section">Included</div>', unsafe_allow_html=True)
            if summary.included_lines:
                item_list([(line, "") for line in summary.included_lines])
            elif plan.included:
                item_list(
                    [
                        (
                            item.label,
                            f"{count_phrase(item.file_count, 'file')}, "
                            f"{human_size(item.total_bytes)}"
                            + (
                                f" · {item.finish_version_id}"
                                if item.finish_version_id
                                else ""
                            ),
                        )
                        for item in plan.included
                    ]
                )
            else:
                quiet("Nothing matches this option yet.")
            if plan.included:
                st.write("")
                quiet(
                    f"{count_phrase(plan.file_count, 'file')} in total, about "
                    f"{human_size(plan.total_bytes)}."
                )

    with columns[1]:
        with st.container(border=True):
            st.markdown('<div class="betty-section">Excluded</div>', unsafe_allow_html=True)
            if summary.excluded_lines:
                item_list(
                    [
                        (line.split(" — ", 1)[0], line.split(" — ", 1)[1] if " — " in line else "")
                        for line in summary.excluded_lines
                    ]
                )
            elif plan.excluded:
                item_list([(item.label, item.reason) for item in plan.excluded])
            else:
                quiet("Nothing is being left out.")

    if plan.info_notes or plan.summary.info_lines:
        for info in plan.info_notes or plan.summary.info_lines:
            quiet(info)

    if plan.warnings:
        note("Warnings must be acknowledged before creating the package.")
        for warning in plan.warnings:
            quiet(warning)

    if plan.blockers:
        blocked_state("Package blocked", plan.blockers[0])


def _create(state: CampaignState, mode: str, plan) -> None:
    acknowledge = True
    if plan.validation_status == "ready_with_warnings" or plan.warnings:
        acknowledge = st.checkbox(
            "I understand the warnings listed above",
            key="export_ack_warnings",
        )

    disabled = plan.is_empty or plan.is_blocked or (
        plan.validation_status == "ready_with_warnings" and not acknowledge
    )
    primary_label = (
        "Create Publishing Package" if mode == PUBLISHING_MODE else "Create Archive Package"
    )
    if st.button(
        primary_label,
        type="primary",
        disabled=disabled,
        key="create_export",
        help="Nothing is included yet." if plan.is_empty else None,
    ):
        with st.status("Building the package…", expanded=True) as status:
            result = create_export_package(
                state,
                mode=mode,
                selected_keys=None,
                acknowledge_warnings=acknowledge,
            )
            status.update(
                label=result.message,
                state="complete" if result.ok else "error",
            )
        st.session_state[RESULT_KEY] = result
        st.rerun()

    result = st.session_state.get(RESULT_KEY)
    if result is None:
        return

    if not result.ok:
        blocked_state("The package was not created", result.message)
        if result.detail:
            quiet(str(result.detail))
        return

    section("Package ready")
    with st.container(border=True):
        key_values(
            [
                ("File", result.path.name if result.path else "—"),
                ("Files inside", result.file_count),
                ("Total size", human_size(result.total_bytes)),
                ("Created", result.created_at),
            ]
        )
        with st.expander(f"Included items ({len(result.included)})", expanded=True):
            item_list([(label, "") for label in result.included])
        if result.excluded:
            with st.expander(
                f"Excluded ({len(result.excluded)}) and why",
                expanded=False,
            ):
                item_list([(item.label, item.reason) for item in result.excluded])
        if result.path and result.path.is_file():
            download_file(
                result.path,
                label="Download ZIP",
                key=f"download_{result.path.name}",
            )
        else:
            blocked_state(
                "The package file is missing",
                "It was created but is no longer on disk. Create it again.",
            )


def _existing(state: CampaignState) -> None:
    packages = list_existing_packages(state)
    section("Earlier packages")
    if not packages:
        quiet("No packages have been created for this campaign yet.")
        return
    for path, created, size in packages:
        with st.container(border=True):
            columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
            with columns[0]:
                key_values([("Created", created), ("Size", size), ("File", path.name)])
            with columns[1]:
                download_file(path, label="Download", key=f"redownload_{path.name}")
