"""Approvals — the only place a render version is signed off."""

from __future__ import annotations

import streamlit as st

from ui import nav
from ui.campaign_state import (
    CampaignState,
    RenderVersion,
    count_phrase,
    finish_records_for_version,
)
from ui.capability import parse_iso
from ui.components import (
    Stat,
    blocked_state,
    caption_body,
    empty_state,
    file_summary,
    key_values,
    media_preview,
    page_header,
    progress_rail,
    quiet,
    report,
    saved_note,
    section,
    show_badges,
    stat_strip,
)
from ui.data_access import load_latest_scores
from ui.status import content_status_for_approval
from ui.workflow_service import save_version_decision

DECISIONS = {
    "approved": "Approve",
    "needs_revision": "Needs Revision",
    "rejected": "Reject",
}
DECISION_KEYS = list(DECISIONS.keys())


def render(state: CampaignState) -> None:
    page_header("Approvals", "One decision per render version. This is what Export uses.")
    progress_rail(state.steps)

    if not state.exists:
        empty_state("No campaign selected", "Open a campaign to approve its renders.")
        if st.button("Go to Campaigns", type="primary"):
            nav.goto("Campaigns")
        return

    if not state.versions:
        blocked_state(
            "Nothing to approve yet",
            "There are no renders in this campaign. Create a render first.",
        )
        if st.button("Go to Create", type="primary"):
            nav.goto("Create", "3. Render")
        return

    counts = state.counts
    stat_strip(
        [
            Stat("Render versions", counts["renders"]),
            Stat(
                "Awaiting decision",
                counts["awaiting_approval"],
                "attention" if counts["awaiting_approval"] else "neutral",
            ),
            Stat("Approved", counts["approved"], "positive" if counts["approved"] else "neutral"),
            Stat(
                "Needs revision",
                counts["needs_revision"],
                "attention" if counts["needs_revision"] else "neutral",
            ),
            Stat("Rejected", counts["rejected"], "blocked" if counts["rejected"] else "neutral"),
        ]
    )

    only_pending = st.toggle(
        "Show only versions awaiting a decision",
        value=counts["awaiting_approval"] > 0,
        key="approvals_pending_only",
    )

    score = _campaign_score()
    groups = _group_by_piece(state)

    shown = 0
    for heading, versions in groups:
        visible = [
            v for v in versions if not only_pending or v.approval_status == "awaiting_review"
        ]
        if not visible:
            continue
        shown += len(visible)
        section(heading)
        for version in visible:
            _version_card(state, version, score)

    if shown == 0:
        empty_state(
            "Every version has a decision",
            "Turn off the filter above to revisit an earlier decision.",
        )
        if counts["approved"]:
            if st.button("Go to Export", type="primary", key="approvals_to_export"):
                nav.goto("Export")


def _campaign_score() -> str | None:
    scores = load_latest_scores() or {}
    entry = scores.get("overall_readiness")
    value = None
    if isinstance(entry, dict):
        try:
            value = float(entry.get("score"))
        except (TypeError, ValueError):
            value = None
    return f"{value:.1f} out of 10 (whole campaign)" if value is not None else None


def _group_by_piece(state: CampaignState) -> list[tuple[str, list[RenderVersion]]]:
    """Group versions under their content piece, with unattached renders last."""
    groups: list[tuple[str, list[RenderVersion]]] = []
    claimed: set[str] = set()

    for piece in state.pieces:
        if not piece.versions:
            continue
        groups.append((piece.record.title, piece.versions))
        claimed.update(v.key for v in piece.versions)

    orphans = [v for v in state.versions if v.key not in claimed]
    if orphans:
        groups.append(("Renders not linked to a content piece", orphans))
    return groups


def _version_card(state: CampaignState, version: RenderVersion, score: str | None) -> None:
    status = content_status_for_approval(version.approval_status)

    with st.container(border=True):
        left, right = st.columns([1, 1], gap="large")

        with left:
            show_badges([status])
            st.markdown(
                f'<div class="betty-section">{version.display_name} · version {version.version}'
                "</div>",
                unsafe_allow_html=True,
            )
            media_preview(version)
            _finished_links(version)

        with right:
            key_values(
                [
                    ("Template", version.display_name),
                    ("Version", f"{version.version}{' (latest)' if version.is_latest else ''}"),
                    ("Created", _readable(version.created_at)),
                    ("Files", file_summary(version)),
                    ("Review score", score or "Not reviewed yet"),
                    (
                        "Revisions addressed",
                        count_phrase(len(version.addressed_recommendation_ids), "recommendation")
                        if version.addressed_recommendation_ids
                        else "None",
                    ),
                    ("Current status", status.label),
                ]
            )
            if version.reviewed_at:
                saved_note(
                    f"{status.label} recorded on disk",
                    _readable(version.reviewed_at),
                )
            # A copy render is its own caption; showing it twice reads as two files.
            if version.caption and version.kind != "copy":
                with st.expander("Caption", expanded=False):
                    caption_body(version.caption)

            _decision_form(state, version)


def _decision_form(state: CampaignState, version: RenderVersion) -> None:
    current = version.approval_status
    default_index = DECISION_KEYS.index(current) if current in DECISION_KEYS else None

    choice = st.radio(
        "Decision",
        options=DECISION_KEYS,
        index=default_index,
        format_func=lambda key: DECISIONS[key],
        horizontal=True,
        key=f"decision_{version.key}",
    )
    comment = st.text_area(
        "Note (optional)",
        value=version.approval_note,
        key=f"note_{version.key}",
        height=80,
        placeholder="Why this decision? Anyone reading the export will see this.",
    )

    unchanged = choice == current and comment.strip() == (version.approval_note or "").strip()
    if st.button(
        "Save decision",
        key=f"save_decision_{version.key}",
        type="primary",
        disabled=choice is None or unchanged,
        help="Nothing has changed since the last save." if unchanged else None,
        use_container_width=True,
    ):
        with st.spinner("Saving…"):
            result = save_version_decision(
                state.path,
                version=version,
                status=choice,
                note=comment,
            )
        report(result)
        if result.ok:
            st.rerun()

    if current == "awaiting_review":
        quiet("No decision recorded yet. Export skips versions without an approval.")


def _finished_links(version: RenderVersion) -> None:
    """Studio finished versions built from this render version, and only this one.

    The decision made on this card covers these finished files too, so a
    reviewer has to be able to see the finish they are signing off rather than
    the original render alone.
    """
    from studio.versions import resolve_finish_output

    records = finish_records_for_version(version)
    if not records:
        return

    for record in records:
        out = resolve_finish_output(version.folder, record)
        submitted = record.status == "ready_for_review"
        st.markdown(
            f'<p class="betty-note">Studio finish · {record.finish_version_id}'
            f'{"" if submitted else " (draft — not sent to Review)"}</p>',
            unsafe_allow_html=True,
        )
        if out is None:
            quiet("The finished file for this version is no longer on disk.")
        elif out.suffix.lower() in {".mp4", ".mov"}:
            st.video(str(out))
        elif out.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            st.image(str(out), use_container_width=True)
        if st.button(
            f"Open {record.finish_version_id} in Studio",
            key=f"view_finish_{version.key}_{record.finish_version_id}",
        ):
            st.session_state["studio_pending_version_key"] = version.key
            nav.goto("Studio")


def _readable(iso: str | None) -> str:
    moment = parse_iso(iso)
    return moment.strftime("%-d %b %Y, %H:%M") if moment else "—"
