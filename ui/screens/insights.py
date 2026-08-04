"""Insights — what BettyOS has learned, not an analytics dashboard."""

from __future__ import annotations

import streamlit as st

from src.common import DEFAULT_BRAND_ID
from studio.learning import (
    list_approval_events,
    list_creative_findings,
    list_performance_findings,
    list_performance_records,
)
from ui import nav
from ui.components import empty_state, key_values, note, page_header, quiet, section
from ui.continue_campaign import resolve_continuation
from ui.campaign_state import build_campaign_state


def render() -> None:
    page_header(
        "Insights",
        "What BettyOS has learned from approvals, creative reviews, and recorded performance.",
    )

    findings = list_creative_findings(DEFAULT_BRAND_ID, active_only=False)
    promoted = [f for f in findings if f.status == "promoted" or f.evidence_count >= 3]
    candidates = [f for f in findings if f not in promoted and (f.finding or f.statement)]

    section("What BettyOS has learned")
    if not promoted and not candidates:
        empty_state(
            "No durable findings yet",
            "As you approve, revise, and reject drafts, BettyOS will record patterns here. "
            "Connected platform evidence is not available yet.",
        )
    else:
        for finding in promoted or candidates[:5]:
            _finding_card(finding, evidence_kind="Observed from approvals")

    perf_findings = list_performance_findings(DEFAULT_BRAND_ID)
    if perf_findings:
        section("Observed from manually entered performance")
        for finding in perf_findings[:5]:
            text = getattr(finding, "finding", None) or getattr(finding, "statement", None) or str(finding)
            with st.container(border=True):
                st.write(text)
                quiet("Source: manually entered performance")

    records = list_performance_records(DEFAULT_BRAND_ID)
    events = list_approval_events(DEFAULT_BRAND_ID)
    with st.expander("Evidence sources", expanded=False):
        key_values(
            [
                ("Observed from approvals", f"{len(events)} events"),
                ("Creative preference findings", f"{len(findings)}"),
                ("Manually entered performance records", f"{len(records)}"),
                ("Connected platform evidence", "Not connected yet"),
            ]
        )
        note(
            "BettyOS does not imply platform performance exists when it does not. "
            "Findings below the promotion threshold remain candidates."
        )

    state = build_campaign_state(nav.active_campaign_path())
    continuation = resolve_continuation(state)
    section("Recommended next action")
    with st.container(border=True):
        st.write(continuation.headline)
        quiet(continuation.why)
        if st.button(continuation.primary_action.label, type="primary", key="insights_next"):
            action = continuation.primary_action
            if action.destination in {"workspace", "Create", "Studio", "Review", "Approvals", "Export"}:
                nav.goto_workspace(
                    action.stage,
                    piece_id=continuation.focus_piece_id,
                    version_key=continuation.focus_version_key,
                )
            else:
                nav.goto(action.destination, stage=action.stage)


def _finding_card(finding, *, evidence_kind: str) -> None:
    text = (finding.finding or finding.statement or "").strip()
    if not text:
        return
    with st.container(border=True):
        st.write(text)
        key_values(
            [
                ("Evidence", f"{finding.evidence_count} signal(s)"),
                ("Confidence", str(finding.confidence or "low").title()),
                ("Scope", _scope_label(finding.scope)),
                ("Source", evidence_kind),
                (
                    "Limitation",
                    "Based on approval patterns inside BettyOS, not live platform metrics."
                    if evidence_kind.startswith("Observed from approvals")
                    else "Limited sample.",
                ),
            ]
        )
        quiet("Recommended application: weigh this on the next Create Best Draft decision.")


def _scope_label(scope: dict | None) -> str:
    if not scope:
        return "Brand-wide"
    parts = [f"{k}: {v}" for k, v in list(scope.items())[:3] if v]
    return ", ".join(parts) if parts else "Brand-wide"
