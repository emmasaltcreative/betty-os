"""Navigation and the one active campaign every page reads.

Primary destinations stay minimal. Pipeline stages live inside the campaign
workspace and are reached through Continue Campaign / Today actions.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.common import OUTPUTS_DIR

# Primary navigation — founder destinations only.
NAV_ITEMS: tuple[str, ...] = (
    "Today",
    "Campaigns",
    "Library",
    "Insights",
    "Settings",
)

# Contextual destinations (not in the sidebar). Routed by app.py.
WORKSPACE = "workspace"
CONTEXTUAL_DESTINATIONS: tuple[str, ...] = (
    WORKSPACE,
    # Legacy aliases kept so older deep links and tests keep working.
    "Home",
    "Create",
    "Studio",
    "Review",
    "Revisions",
    "Approvals",
    "Export",
)

ACTIVE_CAMPAIGN = "active_campaign"
NAV = "nav"
PENDING_NAV = "pending_nav"
PENDING_TAB = "pending_tab"
PENDING_STAGE = "pending_workspace_stage"
SELECTED_PIECE = "selected_piece"
FOCUS_VERSION = "focus_version_key"
INTERRUPTED_FLOW = "interrupted_flow"
WORKSPACE_CONTEXT_FILE = "betty_workspace_context.json"

# Map retired primary-nav names → workspace stage.
LEGACY_TO_STAGE = {
    "Create": "create",
    "Studio": "create",
    "Review": "decide",
    "Revisions": "decide",
    "Approvals": "decide",
    "Export": "deliver",
    "Home": None,  # Today
}


def init_state() -> None:
    defaults: dict[str, object] = {
        NAV: "Today",
        ACTIVE_CAMPAIGN: None,
        PENDING_NAV: None,
        PENDING_TAB: None,
        PENDING_STAGE: None,
        SELECTED_PIECE: None,
        FOCUS_VERSION: None,
        INTERRUPTED_FLOW: None,
        "campaign_goal": "Grow a qualified waitlist for First Edition: The Reading Hour",
        "campaign_platforms": ["Instagram", "Pinterest"],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Migrate prior default label.
    if st.session_state.get(NAV) == "Home":
        st.session_state[NAV] = "Today"

    if st.session_state[ACTIVE_CAMPAIGN] is None:
        newest = _newest_campaign()
        if newest is not None:
            st.session_state[ACTIVE_CAMPAIGN] = newest.name
            _restore_persisted_context(newest)

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
    elif requested in CONTEXTUAL_DESTINATIONS:
        # Contextual pages are not sidebar items; keep NAV on Today/Campaigns
        # but record the contextual target for app.py.
        st.session_state["_contextual_page"] = requested
        if requested in LEGACY_TO_STAGE and LEGACY_TO_STAGE[requested]:
            st.session_state[PENDING_STAGE] = LEGACY_TO_STAGE[requested]
            st.session_state["_contextual_page"] = WORKSPACE
        elif requested == "Home":
            st.session_state[NAV] = "Today"
            st.session_state["_contextual_page"] = None
        elif requested == WORKSPACE:
            st.session_state["_contextual_page"] = WORKSPACE
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
    st.session_state[FOCUS_VERSION] = None
    if path is not None:
        persist_workspace_context(path)
        _restore_persisted_context(path)


def goto(destination: str, tab: str | None = None, stage: str | None = None) -> None:
    """Move to another area, optionally landing on a workspace stage or legacy tab."""
    # Normalize legacy pipeline destinations into the workspace.
    if destination in LEGACY_TO_STAGE and LEGACY_TO_STAGE[destination]:
        stage = stage or LEGACY_TO_STAGE[destination]
        destination = WORKSPACE
    elif destination == "Home":
        destination = "Today"

    st.session_state[PENDING_NAV] = destination
    st.session_state[PENDING_TAB] = tab
    if stage:
        st.session_state[PENDING_STAGE] = stage
    st.rerun()


def goto_workspace(stage: str | None = None, *, piece_id: str | None = None,
                   version_key: str | None = None) -> None:
    if piece_id:
        select_piece(piece_id)
    if version_key:
        st.session_state[FOCUS_VERSION] = version_key
        st.session_state["studio_pending_version_key"] = version_key
    goto(WORKSPACE, stage=stage)


def take_pending_stage(options: list[str]) -> str | None:
    requested = st.session_state.get(PENDING_STAGE)
    if not requested:
        return None
    for option in options:
        if _bare(option) == _bare(str(requested)):
            st.session_state[PENDING_STAGE] = None
            return option
    # Allow raw keys: brief, plan, …
    keys = {_bare(o): o for o in options}
    if _bare(str(requested)) in keys:
        st.session_state[PENDING_STAGE] = None
        return keys[_bare(str(requested))]
    return None


def contextual_page() -> str | None:
    """Non-sidebar page currently being shown (workspace or legacy alias)."""
    return st.session_state.get("_contextual_page")


def clear_contextual_page() -> None:
    st.session_state["_contextual_page"] = None


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
    """Ask the current page to switch step."""
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


def focus_version_key() -> str | None:
    value = st.session_state.get(FOCUS_VERSION)
    return str(value) if value else None


def set_interrupted_flow(payload: dict | None) -> None:
    """Remember an interrupted action (e.g. logo upload mid-create)."""
    st.session_state[INTERRUPTED_FLOW] = payload
    path = active_campaign_path()
    if path is not None:
        persist_workspace_context(path, interrupted=payload)


def take_interrupted_flow() -> dict | None:
    payload = st.session_state.get(INTERRUPTED_FLOW)
    st.session_state[INTERRUPTED_FLOW] = None
    return payload if isinstance(payload, dict) else None


def persist_workspace_context(
    campaign_dir: Path,
    *,
    stage: str | None = None,
    interrupted: dict | None = None,
) -> None:
    """Durable enough context to survive a restart without moving campaign data."""
    from src.persistence import atomic_write_json, load_json

    path = campaign_dir / WORKSPACE_CONTEXT_FILE
    existing = load_json(path, default={}) or {}
    data = {
        "campaign_id": campaign_dir.name,
        "active": True,
        "stage": stage or existing.get("stage") or st.session_state.get(PENDING_STAGE),
        "selected_piece": st.session_state.get(SELECTED_PIECE),
        "focus_version": st.session_state.get(FOCUS_VERSION),
        "interrupted_flow": interrupted
        if interrupted is not None
        else st.session_state.get(INTERRUPTED_FLOW),
    }
    try:
        atomic_write_json(path, data)
    except OSError:
        return


def _restore_persisted_context(campaign_dir: Path) -> None:
    from src.persistence import load_json

    path = campaign_dir / WORKSPACE_CONTEXT_FILE
    data = load_json(path, default={}) or {}
    if not data:
        return
    if data.get("selected_piece") and not st.session_state.get(SELECTED_PIECE):
        st.session_state[SELECTED_PIECE] = data.get("selected_piece")
    if data.get("focus_version") and not st.session_state.get(FOCUS_VERSION):
        st.session_state[FOCUS_VERSION] = data.get("focus_version")
    if data.get("interrupted_flow") and not st.session_state.get(INTERRUPTED_FLOW):
        st.session_state[INTERRUPTED_FLOW] = data.get("interrupted_flow")
    if data.get("stage") and not st.session_state.get(PENDING_STAGE):
        st.session_state[PENDING_STAGE] = data.get("stage")
