"""Navigation and the one active campaign every page reads.

The campaign is chosen once and held in session state. Moving between areas
never asks for it again, and the sidebar always shows the same campaign the page
body is working on.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.common import OUTPUTS_DIR

NAV_ITEMS: tuple[str, ...] = (
    "Home",
    "Campaigns",
    "Create",
    "Studio",
    "Review",
    "Revisions",
    "Approvals",
    "Export",
    "Library",
    "Settings",
)

ACTIVE_CAMPAIGN = "active_campaign"
NAV = "nav"
PENDING_NAV = "pending_nav"
PENDING_TAB = "pending_tab"
SELECTED_PIECE = "selected_piece"


def init_state() -> None:
    defaults: dict[str, object] = {
        NAV: "Home",
        ACTIVE_CAMPAIGN: None,
        PENDING_NAV: None,
        PENDING_TAB: None,
        SELECTED_PIECE: None,
        "campaign_goal": "Grow a qualified waitlist for First Edition: The Reading Hour",
        "campaign_platforms": ["Instagram", "Pinterest"],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state[ACTIVE_CAMPAIGN] is None:
        newest = _newest_campaign()
        if newest is not None:
            st.session_state[ACTIVE_CAMPAIGN] = newest.name

    _apply_pending_destination()


def _apply_pending_destination() -> None:
    """Move the sidebar before it is drawn.

    Streamlit refuses writes to a widget's key once the widget exists, so a
    destination requested from the page body is parked here and applied on the
    next run, ahead of the sidebar.
    """
    requested = st.session_state.get(PENDING_NAV)
    if requested in NAV_ITEMS:
        st.session_state[NAV] = requested
    st.session_state[PENDING_NAV] = None


def _newest_campaign() -> Path | None:
    from ui.campaign_state import list_campaigns

    campaigns = list_campaigns()
    return campaigns[0].path if campaigns else None


def active_campaign_path() -> Path | None:
    name = st.session_state.get(ACTIVE_CAMPAIGN)
    if not name:
        return None
    path = OUTPUTS_DIR / str(name)
    if not path.is_dir():
        st.session_state[ACTIVE_CAMPAIGN] = None
        return None
    return path


def set_active_campaign(path: Path | None) -> None:
    st.session_state[ACTIVE_CAMPAIGN] = path.name if path else None
    st.session_state[SELECTED_PIECE] = None


def goto(destination: str, tab: str | None = None) -> None:
    """Move to another area, optionally landing on a specific step."""
    st.session_state[PENDING_NAV] = destination
    st.session_state[PENDING_TAB] = tab
    st.rerun()


def _bare(label: str) -> str:
    """`3. Render` and `Render` are the same step to a deep link."""
    return label.split(". ", 1)[-1].strip().lower()


def take_pending_tab(options: list[str]) -> str | None:
    """Consume a requested step if it belongs to this page."""
    requested = st.session_state.get(PENDING_TAB)
    if not requested:
        return None
    for option in options:
        if _bare(option) == _bare(str(requested)):
            st.session_state[PENDING_TAB] = None
            return option
    return None


def request_step(tab: str) -> None:
    """Ask the current page to switch step.

    Like `goto`, this defers the change: a step control cannot be reassigned
    after Streamlit has drawn it, so the request is applied on the next run.
    """
    st.session_state[PENDING_TAB] = tab
    st.rerun()


def step_selector(
    label: str,
    options: list[str],
    *,
    key: str,
) -> str:
    """A controllable step switcher, so deep links can land on a given step."""
    requested = take_pending_tab(options)
    if requested is not None:
        st.session_state[key] = requested
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    selected = st.segmented_control(
        label,
        options=options,
        key=key,
        label_visibility="collapsed",
    )
    return selected or st.session_state[key]


def select_piece(piece_id: str | None) -> None:
    st.session_state[SELECTED_PIECE] = piece_id


def selected_piece_id() -> str | None:
    value = st.session_state.get(SELECTED_PIECE)
    return str(value) if value else None
