"""BettyOS — guided creative operating system.

This module is only the shell: theme, sidebar, the active campaign, and routing.
Pipeline stages live inside the campaign workspace. Every action still goes
through `ui/workflow_service.py` so the command line tools stay in step.
"""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import build_campaign_state
from ui.components import inject_theme, quiet
from ui.continue_campaign import resolve_continuation
from ui.screens import campaigns, insights, library, settings, today, workspace
from ui.status import Status


def _sidebar(state) -> str:
    with st.sidebar:
        st.markdown(
            '<p class="betty-brand">BettyOS</p>'
            '<p class="betty-brand-note">Creative studio</p>',
            unsafe_allow_html=True,
        )

        choice = st.radio(
            "Go to",
            options=list(nav.NAV_ITEMS),
            key=nav.NAV,
            label_visibility="collapsed",
        )

        st.divider()
        if state.exists:
            continuation = resolve_continuation(state)
            tone = {
                "blocked": "blocked",
                "ready_to_export": "positive",
                "complete": "positive",
                "draft_ready": "attention",
                "awaiting_approval": "attention",
                "human_input_required": "attention",
            }.get(continuation.current_state, "active")
            badge = Status(
                continuation.current_state,
                continuation.founder_stage_label,
                tone,
            )
            # Orientation only — no duplicate Continue / action labels.
            st.markdown(
                '<p class="betty-brand-note" style="margin-bottom:0.25rem;">Active campaign</p>'
                f'<p style="margin:0 0 0.35rem;font-weight:600;">{state.name}</p>'
                f'<span class="betty-badge {badge.tone}">{badge.label}</span>',
                unsafe_allow_html=True,
            )
            st.progress(state.progress_fraction)
        else:
            quiet("No campaign open.")

    return choice


def main() -> None:
    st.set_page_config(
        page_title="BettyOS",
        page_icon="◍",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_theme()
    nav.init_state()

    state = build_campaign_state(nav.active_campaign_path())

    # Contextual workspace takes over the main pane without a sidebar item.
    contextual = nav.contextual_page()
    if contextual == nav.WORKSPACE:
        _sidebar(state)
        workspace.render(state)
        return

    page = _sidebar(state)

    if page == "Today":
        today.render(state)
    elif page == "Campaigns":
        campaigns.render(state)
    elif page == "Library":
        library.render()
    elif page == "Insights":
        insights.render()
    else:
        settings.render()


if __name__ == "__main__":
    main()
