"""Home — what am I working on, what stage is it in, what needs me, what next."""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import CampaignState
from ui.components import (
    Stat,
    blocked_list,
    empty_state,
    key_values,
    page_header,
    progress_rail,
    quiet,
    section,
    stat_strip,
)
from ui.status import campaign_status


def render(state: CampaignState) -> None:
    if not state.exists:
        page_header("Home", "Your campaign at a glance.")
        empty_state(
            "No campaign selected",
            "Choose or create a campaign to begin.",
        )
        if st.button("Go to Campaigns", type="primary"):
            nav.goto("Campaigns")
        return

    stage = campaign_status(state.stage)
    page_header(state.name, state.goal, badges=[stage])
    progress_rail(state.steps)

    counts = state.counts
    stat_strip(
        [
            Stat("Content pieces", counts["pieces"]),
            Stat(
                "Ready to render",
                counts["ready_to_render"],
                "attention" if counts["ready_to_render"] else "neutral",
            ),
            Stat("Rendered", counts["renders"], "positive" if counts["renders"] else "neutral"),
            Stat(
                "Needs revision",
                counts["needs_revision"],
                "attention" if counts["needs_revision"] else "neutral",
            ),
            Stat(
                "Awaiting approval",
                counts["awaiting_approval"],
                "attention" if counts["awaiting_approval"] else "neutral",
            ),
            Stat("Approved", counts["approved"], "positive" if counts["approved"] else "neutral"),
        ]
    )

    _next_action(state)

    left, right = st.columns([1, 1], gap="large")
    with left:
        _attention(state)
    with right:
        _activity(state)


def _next_action(state: CampaignState) -> None:
    step = state.next_step
    with st.container(border=True):
        columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
        with columns[0]:
            st.markdown(
                f'<div class="betty-section">Next: {step.label}</div>'
                f'<p class="betty-section-note" style="margin-bottom:0;">{step.reason}</p>',
                unsafe_allow_html=True,
            )
        with columns[1]:
            if st.button(
                "Continue Campaign",
                type="primary",
                use_container_width=True,
                disabled=not step.actionable,
                help=None if step.actionable
                else "Every content piece is blocked. Clear a blocker below first.",
            ):
                nav.goto(step.destination, step.tab)


def _attention(state: CampaignState) -> None:
    section("Needs your attention")
    counts = state.counts
    if state.blockers:
        blocked_list("Blockers", state.blockers)
        st.write("")

    items: list[tuple[str, object]] = []
    if counts["ready_to_render"]:
        items.append(("Ready to render", f"{counts['ready_to_render']} pieces"))
    if counts["missing_inputs"]:
        items.append(("Missing source media", f"{counts['missing_inputs']} pieces"))
    if counts["unsupported"]:
        items.append(("No working template", f"{counts['unsupported']} pieces"))
    revisions = state.revision_counts
    if revisions["awaiting_decision"]:
        items.append(("Revisions waiting on a decision", revisions["awaiting_decision"]))
    if revisions["ready_to_apply"]:
        items.append(("Revisions chosen and ready to apply", revisions["ready_to_apply"]))
    if revisions["needs_human"]:
        items.append(("Revisions waiting on something to supply", revisions["needs_human"]))
    if revisions["failed"]:
        items.append(("Revisions that failed to apply", revisions["failed"]))
    if counts["awaiting_approval"]:
        items.append(("Render versions awaiting a decision", counts["awaiting_approval"]))
    if counts["needs_revision"]:
        items.append(("Render versions marked for revision", counts["needs_revision"]))

    if not items and not state.blockers:
        quiet("Nothing is waiting on you.")
        return
    key_values(items)


def _activity(state: CampaignState) -> None:
    section("Latest activity")
    if not state.activity:
        quiet("Nothing has happened in this campaign yet.")
        return
    for entry in state.activity:
        quiet(entry)
