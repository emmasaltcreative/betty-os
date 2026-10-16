"""Campaign Timeline — founder-facing milestones for the campaign object.

Version history remains on disk; this surface replaces it as the primary
narrative of where the campaign stands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ui.campaign_state import CampaignState

EventState = Literal["complete", "current", "upcoming"]


@dataclass(frozen=True)
class TimelineEvent:
    key: str
    label: str
    state: EventState
    detail: str = ""
    at: str | None = None


def campaign_timeline(state: CampaignState) -> list[TimelineEvent]:
    """Derive a calm campaign timeline from existing campaign state + documents."""
    if not state.exists or state.path is None:
        return [
            TimelineEvent("created", "Campaign Created", "upcoming"),
            TimelineEvent("brief", "Brief Approved", "upcoming"),
            TimelineEvent("production_brief", "Production Brief Generated", "upcoming"),
            TimelineEvent("capture", "Capture Complete", "upcoming"),
            TimelineEvent("created_assets", "Creative Generated", "upcoming"),
            TimelineEvent("approved", "Creative Approved", "upcoming"),
            TimelineEvent("package", "Publishing Package Built", "upcoming"),
            TimelineEvent("published", "Published", "upcoming"),
            TimelineEvent("performance", "Performance Imported", "upcoming"),
        ]

    path = state.path
    has_goal = bool(state.goal and state.goal != "No goal recorded")
    has_pieces = bool(state.pieces)
    has_brief_doc = _has_production_brief(path)
    has_capture = _capture_complete(state)
    has_renders = bool(state.versions)
    has_approved = bool(state.approved_versions)
    has_package = state.export_count > 0
    has_performance = _has_performance(path)

    # Current stage hint from workflow steps
    current_key = _current_key(state)

    milestones = [
        ("created", "Campaign Created", True, state.created_at),
        ("brief", "Brief Approved", has_goal or has_pieces, None),
        ("production_brief", "Production Brief Generated", has_brief_doc, None),
        ("capture", "Capture Complete", has_capture or has_renders, None),
        ("created_assets", "Creative Generated", has_renders, None),
        ("approved", "Creative Approved", has_approved, None),
        ("package", "Publishing Package Built", has_package, None),
        ("published", "Published", has_package and has_approved, None),
        ("performance", "Performance Imported", has_performance, None),
    ]

    events: list[TimelineEvent] = []
    found_current = False
    for key, label, done, at in milestones:
        if done:
            state_name: EventState = "complete"
        elif not found_current and key == current_key:
            state_name = "current"
            found_current = True
        elif not found_current and not done:
            state_name = "current"
            found_current = True
        else:
            state_name = "upcoming"
        events.append(
            TimelineEvent(
                key=key,
                label=label,
                state=state_name,
                detail=_detail_for(key, state),
                at=at if at and at != "—" else None,
            )
        )
    if not found_current:
        # Mark first incomplete as current
        for index, event in enumerate(events):
            if event.state != "complete":
                events[index] = TimelineEvent(
                    event.key, event.label, "current", event.detail, event.at
                )
                break
    return events


def render_timeline(state: CampaignState, *, compact: bool = False) -> None:
    import streamlit as st
    from ui.components import quiet

    events = campaign_timeline(state)
    if compact:
        current = next((e for e in events if e.state == "current"), None)
        completed = sum(1 for e in events if e.state == "complete")
        quiet(f"Timeline · {completed} of {len(events)} milestones")
        if current:
            st.markdown(
                f'<p class="betty-timeline-current">{current.label}</p>',
                unsafe_allow_html=True,
            )
        return

    items = []
    for event in events:
        mark = {"complete": "●", "current": "◉", "upcoming": "○"}[event.state]
        cls = f"betty-timeline-{event.state}"
        detail = f'<span class="betty-timeline-detail">{event.detail}</span>' if event.detail else ""
        when = f'<span class="betty-timeline-when">{event.at}</span>' if event.at else ""
        items.append(
            f'<div class="betty-timeline-item {cls}">'
            f'<span class="betty-timeline-mark">{mark}</span>'
            f'<span class="betty-timeline-label">{event.label}</span>'
            f"{when}{detail}"
            f"</div>"
        )
    st.markdown(
        f'<div class="betty-timeline">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


def _current_key(state: CampaignState) -> str:
    incomplete = [s for s in state.steps if s.state != "complete"]
    if not incomplete:
        return "package" if state.export_count else "approved"
    step = incomplete[0].key
    mapping = {
        "brief": "brief",
        "plan": "production_brief",
        "capture": "capture",
        "create": "created_assets",
        "decide": "approved",
        "deliver": "package",
    }
    return mapping.get(step, "brief")


def _detail_for(key: str, state: CampaignState) -> str:
    if key == "created_assets" and state.versions:
        return f"{len(state.versions)} version{'s' if len(state.versions) != 1 else ''}"
    if key == "approved" and state.approved_versions:
        return f"{len(state.approved_versions)} approved"
    if key == "package" and state.export_count:
        return f"{state.export_count} package{'s' if state.export_count != 1 else ''}"
    return ""


def _has_production_brief(campaign_dir: Path) -> bool:
    try:
        from src.campaign_intelligence import newest_brief, resolve_brief_file

        record = newest_brief(campaign_dir)
        if record is None:
            return False
        return resolve_brief_file(campaign_dir, record) is not None
    except Exception:
        briefs = campaign_dir / "production_briefs"
        return briefs.is_dir() and any(briefs.glob("*.pdf"))


def _capture_complete(state: CampaignState) -> bool:
    if not state.pieces:
        return False
    missing = [p for p in state.pieces if p.status_key == "missing_inputs"]
    return len(missing) == 0


def _has_performance(campaign_dir: Path) -> bool:
    for name in ("performance.json", "analytics.json", "performance_imported.json"):
        if (campaign_dir / name).is_file():
            return True
    return False
