"""Today — the home and hero of BettyOS.

One recommendation. One conversational summary. One primary action.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui import nav
from ui.campaign_state import CampaignState
from ui.components import quiet
from ui.continue_campaign import (
    CampaignContinuation,
    primary_blockers_for_display,
    resolve_continuation,
    soft_attention_items,
)
from ui.journal import recent_learning_summary


def render(state: CampaignState) -> None:
    continuation = resolve_continuation(state)
    greeting = _greeting()

    st.markdown(
        f'<p class="betty-subtitle" style="margin-bottom:0.35rem;">{greeting}</p>'
        f'<h1 class="betty-title" style="margin-bottom:0.15rem;">Your best next move</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="betty-section" style="margin-top:0.85rem;">{continuation.headline}</p>',
        unsafe_allow_html=True,
    )

    st.write("")
    with st.container(border=True):
        st.write(_conversational_summary(continuation))

        if continuation.required_from_user:
            st.write("")
            quiet("What I need from you")
            for item in continuation.required_from_user:
                st.markdown(f"- {item}")

        if continuation.estimated_effort and continuation.estimated_effort != "—":
            quiet(continuation.estimated_effort)

        hard = primary_blockers_for_display(continuation)
        if hard:
            st.write("")
            quiet(hard[0])

        st.write("")
        _primary_button(continuation)

        # Quiet secondary: Not today only — campaign details live in one disclosure below.
        not_today = next(
            (a for a in continuation.secondary_actions if a.label.lower() == "not today"),
            None,
        )
        if not_today is not None:
            if st.button("Not today", key="today_not_today"):
                _run_action(not_today, continuation)

    attention = soft_attention_items(state, continuation)
    if attention:
        with st.expander("Needs attention", expanded=False):
            for item in attention:
                st.markdown(f"**{item['title']}**")
                quiet(item["detail"])
                quiet(f"Blocks approval: {item['blocks_approval']}")
            with st.expander("View technical details", expanded=False):
                for blocker in continuation.blockers:
                    quiet(blocker)
                failed = int(state.revision_counts.get("failed") or 0)
                if failed:
                    quiet(f"Internal: {failed} failed revision request(s) in revision_requests.json")

    if state.exists:
        with st.expander("View campaign", expanded=False):
            quiet(state.name)
            quiet(state.goal)
            quiet(f"Stage: {continuation.founder_stage_label}")
            if st.button("Open Campaigns", key="today_open_campaigns"):
                nav.goto("Campaigns")

    learning = recent_learning_summary()
    if learning:
        with st.expander("Recently learned", expanded=False):
            for line in learning:
                quiet(line)


def _conversational_summary(continuation: CampaignContinuation) -> str:
    """One concise paragraph: recommendation reason + what follows."""
    parts: list[str] = []
    why = (continuation.why or "").strip()
    message = (continuation.message or "").strip()
    if why:
        parts.append(why)
    elif message and message != continuation.headline:
        parts.append(message)

    aftermath = (continuation.aftermath or "").strip()
    if aftermath and aftermath not in why:
        # Keep aftermath as a short closing clause when it adds direction.
        if parts:
            parts.append(aftermath)
        else:
            parts.append(aftermath)

    if not parts:
        return continuation.headline
    return " ".join(parts)


def _primary_button(continuation: CampaignContinuation) -> None:
    action = continuation.primary_action
    if st.button(action.label, type="primary", use_container_width=True, key="today_primary"):
        _run_action(action, continuation)


def _run_action(action, continuation: CampaignContinuation) -> None:
    dest = action.destination
    stage = getattr(action, "stage", None)
    context = getattr(action, "context", None) or {}
    piece_id = context.get("piece_id") or continuation.focus_piece_id
    version_key = context.get("version_key") or continuation.focus_version_key

    if dest in {"workspace", "Create", "Studio", "Review", "Revisions", "Approvals", "Export"}:
        nav.goto_workspace(stage, piece_id=piece_id, version_key=version_key)
        return
    if dest == "Today":
        st.session_state["betty_flash"] = "Understood. I will keep this recommendation ready."
        st.rerun()
        return
    nav.goto(dest, tab=getattr(action, "tab", None), stage=stage)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        lead = "Good morning"
    elif hour < 17:
        lead = "Good afternoon"
    else:
        lead = "Good evening"
    return f"{lead}."
