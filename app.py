"""BettyOS — campaign → create → studio → review → revise → approve → export.

This module is only the shell: theme, sidebar, the active campaign, and routing.
Every screen lives in `ui/screens/`, and every action goes through
`ui/workflow_service.py` so the command line tools and this interface stay in step.
"""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import build_campaign_state
from ui.components import inject_theme, quiet
from ui.screens import approvals, campaigns, create, export, home, library, review, settings, studio
from ui.status import campaign_status


def _sidebar(state) -> str:
    with st.sidebar:
        st.markdown(
            '<p class="betty-brand">BettyOS</p>'
            '<p class="betty-brand-note">Content studio</p>',
            unsafe_allow_html=True,
        )

        # Bound to the same key `goto()` writes, so deep links move the sidebar too.
        choice = st.radio(
            "Go to",
            options=list(nav.NAV_ITEMS),
            key=nav.NAV,
            label_visibility="collapsed",
        )

        st.divider()
        if state.exists:
            status = campaign_status(state.stage)
            st.markdown(
                '<p class="betty-brand-note" style="margin-bottom:0.25rem;">Active campaign</p>'
                f'<p style="margin:0 0 0.35rem;font-weight:600;">{state.name}</p>'
                f'<span class="betty-badge {status.tone}">{status.label}</span>',
                unsafe_allow_html=True,
            )
            st.progress(state.progress_fraction)
        else:
            quiet("No campaign open.")
            if st.button("Choose a campaign", use_container_width=True):
                nav.goto("Campaigns")

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
    page = _sidebar(state)

    if page == "Home":
        home.render(state)
    elif page == "Campaigns":
        campaigns.render(state)
    elif page == "Create":
        create.render(state)
    elif page == "Studio":
        studio.render(state)
    elif page == "Review":
        review.render(state)
    elif page == "Revisions":
        # Revisions is Review's second step, reachable directly from the sidebar.
        st.session_state[nav.PENDING_TAB] = "Revisions"
        review.render(state)
    elif page == "Approvals":
        approvals.render(state)
    elif page == "Export":
        export.render(state)
    elif page == "Library":
        library.render()
    else:
        settings.render()


if __name__ == "__main__":
    main()
