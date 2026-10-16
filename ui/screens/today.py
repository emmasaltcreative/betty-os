"""Today — the house desk.

One campaign recommendation. One next step. One CTA.
Set like the atelier site: a dateline, an italic name, a letter, a square button.
"""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from ui import nav
from ui.campaign_state import CampaignState
from ui.components import brand_mark_svg
from ui.continue_campaign import (
    CampaignContinuation,
    primary_blockers_for_display,
    resolve_continuation,
)

_INTEL_KICKER = {
    "deadline": "On the calendar",
    "risk": "Needs a decision",
    "opportunity": "Worth making",
}


def render(state: CampaignState) -> None:
    continuation = resolve_continuation(state)
    _dateline()
    _show_kept()

    if state.exists and _render_campaign_recommendation(state, continuation):
        return

    intel_card = _intelligence_card(state)
    if intel_card and _prefer_intelligence(continuation, intel_card):
        sign_bits = [intel_card.get("filming"), intel_card.get("runway")]
        sign = " · ".join(bit for bit in sign_bits if bit) or None
        body = (intel_card.get("body") or "").strip()
        title_line = (intel_card.get("title") or "").strip()
        if title_line and title_line not in body:
            body = f"{title_line} {body}".strip()
        _piece(
            kicker=_INTEL_KICKER.get(str(intel_card.get("kind")), "From the house"),
            title=state.name,
            body=body or title_line,
            sign=sign,
        )
        if st.button(
            intel_card["action_label"],
            type="primary",
            key="today_intel_primary",
        ):
            nav.goto_workspace("plan")
        return

    if not state.exists:
        _piece(
            kicker="The house",
            title="Nothing open",
            body="When a campaign is open, the next piece of work waits here.",
        )
    else:
        _piece(
            kicker=continuation.founder_stage_label,
            title=state.name,
            body=_letter_body(continuation),
            sign=_sign(continuation),
        )
    _primary_button(continuation)
    _not_today(continuation)


def _render_campaign_recommendation(state: CampaignState, continuation: CampaignContinuation) -> bool:
    try:
        from src.campaign_meta import (
            coverage_summary,
            ensure_campaign_meta,
            next_recommended_deliverable,
        )
    except Exception:
        return False

    meta = ensure_campaign_meta(state.path, objective=state.goal, pieces=state.pieces)
    coverage = coverage_summary(meta)
    nxt = next_recommended_deliverable(meta)
    if nxt is None and meta.readiness not in {"ready_to_deliver", "delivered"}:
        # Fall back when coverage has not been seeded yet
        return False

    if nxt is not None:
        effort = (continuation.estimated_effort or "").strip()
        progress = str(coverage["progress_label"]).replace("deliverables", "pieces")
        sign_bits = [progress]
        if effort and effort != "—":
            sign_bits.append(effort)
        _piece(
            kicker=state.name,
            title=_display_title(nxt.title),
            body=_piece_letter(nxt),
            sign=". ".join(sign_bits),
        )
        label = "Create Next Asset"
        if nxt.status == "in_review":
            label = "Review Next Asset"
        elif nxt.status == "missing_footage":
            label = "Add Footage"
        if st.button(label, type="primary", key="today_primary"):
            if nxt.status == "in_review":
                nav.goto_workspace("decide", piece_id=nxt.piece_id)
            elif nxt.status == "missing_footage":
                nav.goto_workspace("capture", piece_id=nxt.piece_id)
            else:
                nav.goto_workspace("create", piece_id=nxt.piece_id)
        return True

    _piece(
        kicker=state.name,
        title="Ready to go out",
        body="The pieces for this campaign are finished. They can leave the house when you are ready.",
    )
    if st.button("Open Publishing", type="primary", key="today_primary"):
        st.session_state["campaign_shell_tab"] = "Publishing"
        nav.goto("Campaigns")
    return True


def _display_title(title: str) -> str:
    text = (title or "The next piece").replace("*", " ").strip()
    if text.endswith(")") and "(" in text:
        text = text[: text.rfind("(")].strip()
    return text or "The next piece"


def _piece_letter(item) -> str:
    status = getattr(item, "status", "") or ""
    if status == "in_review":
        return "It is waiting for a decision."
    if status == "missing_footage":
        return "It needs footage before it can be made."
    platform = (getattr(item, "platform", "") or "").strip()
    if platform:
        return f"A piece for {platform}."
    return "It is ready to be made."


def _dateline() -> None:
    label = datetime.now().strftime("%A, %-d %B")
    st.markdown(
        '<div class="betty-house">'
        f'<div class="house-mark">{brand_mark_svg("bettyPetalPage")}</div>'
        f'<p class="house-date">{html.escape(label)}</p>'
        "</div>",
        unsafe_allow_html=True,
    )


def _piece(*, kicker: str, title: str, body: str, sign: str | None = None) -> None:
    sign_html = f'<p class="house-sign">{html.escape(sign)}</p>' if sign else ""
    st.markdown(
        '<article class="house-piece">'
        f'<p class="house-kicker">{html.escape(kicker)}</p>'
        f'<h1 class="house-title">{html.escape(title)}</h1>'
        f'<p class="house-body">{html.escape(body)}</p>'
        f"{sign_html}"
        "</article>",
        unsafe_allow_html=True,
    )


def _letter_body(continuation: CampaignContinuation) -> str:
    why = (continuation.why or "").strip()
    if why:
        return why
    message = (continuation.message or "").strip()
    if message and message != continuation.headline:
        return message
    return continuation.headline


def _sign(continuation: CampaignContinuation) -> str | None:
    hard = primary_blockers_for_display(continuation)
    if hard:
        return hard[0]
    effort = (continuation.estimated_effort or "").strip()
    if effort and effort != "—":
        return effort
    return None


def _intelligence_card(state: CampaignState) -> dict | None:
    if not state.exists or state.path is None:
        return None
    try:
        from src.campaign_intelligence import today_intelligence_card

        return today_intelligence_card(state.path)
    except Exception:
        return None


def _prefer_intelligence(continuation: CampaignContinuation, card: dict) -> bool:
    if card.get("kind") in {"deadline", "risk", "opportunity"}:
        if continuation.current_state in {
            "no_active_campaign",
            "campaign_needs_brief",
            "content_plan_ready",
            "human_input_required",
        }:
            return True
        if card.get("kind") in {"deadline", "risk"}:
            return True
    return False


def _primary_button(continuation: CampaignContinuation) -> None:
    action = continuation.primary_action
    if st.button(action.label, type="primary", key="today_primary"):
        _run_action(action, continuation)


def _not_today(continuation: CampaignContinuation) -> None:
    not_today = next(
        (a for a in continuation.secondary_actions if a.label.lower() == "not today"),
        None,
    )
    if not_today is None:
        return
    if st.button("Not today", key="today_not_today"):
        _run_action(not_today, continuation)


def _show_kept() -> None:
    message = st.session_state.pop("betty_flash", None)
    if isinstance(message, str) and message.strip():
        st.markdown(
            f'<p class="house-sign">{html.escape(message.strip())}</p>',
            unsafe_allow_html=True,
        )


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
        st.session_state["betty_flash"] = "Kept for another day."
        st.rerun()
        return
    nav.goto(dest, tab=getattr(action, "tab", None), stage=stage)
