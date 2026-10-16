"""BettyOS — guided creative operating system.

This module is only the shell: theme, sidebar, the active campaign, and routing.
Pipeline stages live inside the campaign workspace. Every action still goes
through `ui/workflow_service.py` so the command line tools stay in step.
"""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import build_campaign_state
from ui.components import brand_mark_svg, inject_theme, quiet
from ui.continue_campaign import resolve_continuation
from ui.screens import campaigns, library, settings, today, workspace
from ui.status import Status


def _sidebar(state) -> str:
    with st.sidebar:
        st.markdown(
            '<div class="betty-mark">'
            + brand_mark_svg("bettyPetal")
            + '<p class="betty-wordmark">Oh Betty Jaletti</p>'
            '<p class="betty-atelier">Atelier</p>'
            "</div>",
            unsafe_allow_html=True,
        )

        choice = st.radio(
            "Go to",
            options=list(nav.NAV_ITEMS),
            key=nav.NAV,
            label_visibility="collapsed",
        )

        collapsed = st.session_state.get("betty_sidebar_campaign_collapsed", False)
        st.divider()
        if state.exists:
            _active_campaign_panel(state, collapsed=collapsed)
        else:
            quiet("No campaign open.")

    return choice


def _active_campaign_panel(state, *, collapsed: bool) -> None:
    from src.campaign_meta import (
        coverage_summary,
        ensure_campaign_meta,
        next_recommended_deliverable,
    )

    continuation = resolve_continuation(state)
    meta = None
    coverage = None
    next_item = None
    runway = None
    try:
        meta = ensure_campaign_meta(state.path, objective=state.goal, pieces=state.pieces)
        coverage = coverage_summary(meta)
        next_item = next_recommended_deliverable(meta)
        runway = _sidebar_runway(state)
    except Exception:
        pass

    st.markdown(
        '<p class="betty-brand-note" style="margin-bottom:0.25rem;">Active campaign</p>',
        unsafe_allow_html=True,
    )
    if st.button(state.name, key="betty_sidebar_open_overview", use_container_width=True):
        nav.clear_contextual_page()
        st.session_state["campaign_shell_tab"] = "Overview"
        nav.goto("Campaigns")

    if collapsed:
        if st.button("Show", key="betty_toggle_campaign_panel"):
            st.session_state["betty_sidebar_campaign_collapsed"] = False
            st.rerun()
        return

    readiness = (meta.readiness if meta else continuation.founder_stage_label).replace("_", " ")
    tone = {
        "blocked": "blocked",
        "ready_to_export": "positive",
        "ready_to_deliver": "positive",
        "complete": "positive",
        "delivered": "positive",
        "draft_ready": "attention",
        "awaiting_approval": "attention",
        "reviewing": "attention",
        "human_input_required": "attention",
    }.get(meta.readiness if meta else continuation.current_state, "active")
    badge = Status(
        meta.readiness if meta else continuation.current_state,
        readiness.title() if meta else continuation.founder_stage_label,
        tone,
    )
    st.markdown(
        f'<span class="betty-badge {badge.tone}">{badge.label}</span>',
        unsafe_allow_html=True,
    )
    quiet(f"Objective: {state.goal}", extra_class="betty-aside-long")
    if coverage:
        quiet(f"Progress: {coverage['progress_label']}", extra_class="betty-aside-long")
    if runway:
        quiet(f"Estimated runway: {runway}", extra_class="betty-aside-long")
    if next_item is not None:
        quiet(f"Next: {next_item.title}", extra_class="betty-aside-long")
        if st.button("Open next action", key="betty_sidebar_next", use_container_width=True):
            _open_next_deliverable(state, next_item)
    elif continuation.primary_action:
        quiet(f"Next: {continuation.primary_action.label}")

    if st.button("Hide", key="betty_toggle_campaign_panel"):
        st.session_state["betty_sidebar_campaign_collapsed"] = True
        st.rerun()


def _sidebar_runway(state) -> str | None:
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


def _open_next_deliverable(state, item) -> None:
    piece_id = item.piece_id
    if item.status == "in_review":
        nav.goto_workspace("decide", piece_id=piece_id)
    elif item.status in {"ready_to_create", "planned"}:
        nav.goto_workspace("create", piece_id=piece_id)
    elif item.status == "missing_footage":
        nav.goto_workspace("capture", piece_id=piece_id)
    else:
        nav.clear_contextual_page()
        st.session_state["campaign_shell_tab"] = "Creative"
        nav.goto("Campaigns")


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

    # Draw sidebar first so we can honor a destination change while workspace is open.
    page = _sidebar(state)
    left_workspace = nav.sync_sidebar_leaving_workspace(page)

    contextual = nav.contextual_page()
    if contextual == nav.WORKSPACE and not left_workspace:
        workspace.render(state)
        return

    if page == "Today":
        today.render(state)
    elif page == "Campaigns":
        campaigns.render(state)
    elif page == "Library":
        library.render()
    elif page == "Insights":
        # Hidden from NAV_ITEMS; keep route for legacy deep links.
        from ui.screens import insights

        insights.render()
    else:
        settings.render()


if __name__ == "__main__":
    main()
