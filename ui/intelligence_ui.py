"""Streamlit helpers for campaign intelligence — additive UI, not a second workflow."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from src.campaign_intelligence import (
    CampaignInputs,
    RecommendationDecision,
    accept_plan_and_generate_brief,
    accept_portfolio,
    load_intelligence,
    missing_material_inputs,
    newest_brief,
    plan_campaign_intelligence,
    record_recommendation_decision,
    resolve_brief_file,
    update_estimates_after_capture,
)
from src.campaign_intelligence.downloads import confirm_readable_file, human_size, show_in_finder
from src.common import DEFAULT_BRAND_ID
from src.platforms import PLATFORM_OPTIONS, multiselect_platform_defaults
from ui.components import key_values, note, quiet, section


def _parse_optional_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def render_brief_intelligence_inputs(campaign_dir: Path, *, default_goal: str = "") -> None:
    """Progressive campaign inputs on the Brief stage."""
    intel = load_intelligence(campaign_dir)
    existing = intel.inputs if intel else CampaignInputs()
    goal_default = existing.business_objective or default_goal

    section("Campaign intelligence", "Only what changes the recommendation.")
    with st.container(border=True):
        objective = st.text_input(
            "Business objective",
            value=goal_default,
            key="intel_objective",
            help="Example: grow the waitlist",
        )
        platforms = st.multiselect(
            "Preferred platforms",
            list(PLATFORM_OPTIONS),
            default=multiselect_platform_defaults(
                existing.preferred_platforms,
                st.session_state.get("campaign_platforms"),
                fallback=("Instagram", "Pinterest"),
                source="intelligence.brief",
            ),
            key="intel_platforms",
        )

        missing = missing_material_inputs(
            CampaignInputs(
                business_objective=objective,
                preferred_platforms=platforms,
                target_milestone_date=existing.target_milestone_date,
                filming_minutes_available=existing.filming_minutes_available,
                filming_availability=existing.filming_availability,
            )
        )

        with st.expander("Dates that affect timing", expanded="target_milestone_date" in missing):
            target = st.text_input(
                "Target milestone or launch date (YYYY-MM-DD)",
                value=existing.target_milestone_date.isoformat()
                if existing.target_milestone_date
                else "",
                key="intel_target_date",
            )
            product_avail = st.text_input(
                "Product availability date (optional)",
                value=existing.product_availability_date.isoformat()
                if existing.product_availability_date
                else "",
                key="intel_product_date",
            )
            shipping = st.text_input(
                "Shipping cutoff (optional)",
                value=existing.shipping_cutoff.isoformat() if existing.shipping_cutoff else "",
                key="intel_shipping",
            )
            uncertain = st.checkbox(
                "Target date is uncertain — confirm before treating as hard",
                value=(existing.date_certainty or {}).get("target_launch") == "uncertain",
                key="intel_date_uncertain",
            )

        with st.expander(
            "Filming and production capacity",
            expanded="filming_availability" in missing,
        ):
            filming_minutes = st.number_input(
                "Filming time available (minutes)",
                min_value=15,
                max_value=480,
                value=int(existing.filming_minutes_available or 60),
                key="intel_film_mins",
            )
            filming_notes = st.text_input(
                "Founder / filming availability notes",
                value=existing.filming_availability or existing.founder_availability,
                key="intel_film_notes",
            )

        with st.expander("More context (optional)", expanded=False):
            inventory = st.selectbox(
                "Inventory available?",
                ["Use brand default", "No", "Yes"],
                index=0
                if existing.inventory_available is None
                else (1 if existing.inventory_available is False else 2),
                key="intel_inventory",
            )
            deps = st.text_area(
                "Known campaign dependencies",
                value="\n".join(existing.known_dependencies),
                height=70,
                key="intel_deps",
            )
            existing_assets = st.text_area(
                "Existing assets available",
                value=existing.existing_assets_notes,
                height=70,
                key="intel_assets",
            )
            market = st.text_input(
                "Geographic or audience market",
                value=existing.geographic_market,
                key="intel_market",
            )
            budget = st.text_input("Budget notes (optional)", value=existing.budget_notes, key="intel_budget")
            paid = st.text_input(
                "Paid media notes (optional)", value=existing.paid_media_notes, key="intel_paid"
            )

        if st.button("Update campaign intelligence", type="primary", key="intel_save_inputs"):
            inv_value: bool | None
            if inventory == "No":
                inv_value = False
            elif inventory == "Yes":
                inv_value = True
            else:
                inv_value = None

            certainty = dict(existing.date_certainty or {})
            if uncertain:
                certainty["target_launch"] = "uncertain"
            elif "target_launch" in certainty:
                certainty["target_launch"] = "confirmed"

            inputs = CampaignInputs(
                business_objective=objective.strip(),
                target_milestone_date=_parse_optional_date(target),
                product_availability_date=_parse_optional_date(product_avail),
                shipping_cutoff=_parse_optional_date(shipping),
                filming_availability=filming_notes.strip(),
                founder_availability=filming_notes.strip(),
                filming_minutes_available=int(filming_minutes),
                preferred_platforms=list(platforms),
                existing_assets_notes=existing_assets.strip(),
                known_dependencies=[d.strip() for d in deps.splitlines() if d.strip()],
                geographic_market=market.strip(),
                budget_notes=budget.strip(),
                paid_media_notes=paid.strip(),
                inventory_available=inv_value,
                date_certainty=certainty,
            )
            plan_campaign_intelligence(
                campaign_dir=campaign_dir,
                campaign_name=st.session_state.get("active_campaign_name", ""),
                inputs=inputs,
                piece_count=5,
                brand_id=DEFAULT_BRAND_ID,
                persist=True,
            )
            st.session_state["campaign_goal"] = objective.strip()
            st.session_state["campaign_platforms"] = list(platforms)
            st.session_state["betty_flash"] = "Campaign intelligence updated."
            st.rerun()


def render_plan_intelligence(campaign_dir: Path, *, piece_count: int = 5) -> None:
    """Portfolio, estimates, and Accept Plan → Production Brief."""
    intel = load_intelligence(campaign_dir)
    if intel is None:
        quiet("Add a business objective in Brief to unlock campaign intelligence.")
        if st.button("Build intelligence from current goal", key="intel_bootstrap"):
            goal = st.session_state.get("campaign_goal", "grow the waitlist")
            plan_campaign_intelligence(
                campaign_dir=campaign_dir,
                campaign_name=campaign_dir.name,
                inputs=CampaignInputs(
                    business_objective=goal,
                    preferred_platforms=st.session_state.get(
                        "campaign_platforms", ["Instagram", "Pinterest"]
                    ),
                    filming_minutes_available=60,
                ),
                piece_count=piece_count,
                persist=True,
            )
            st.rerun()
        return

    section("Campaign portfolio")
    for rec in intel.recommendations:
        with st.container(border=True):
            role = rec.role.value.replace("_", " ").title()
            st.markdown(f"**{rec.campaign_name}** · {role}")
            quiet(rec.reason)
            key_values(
                [
                    ("Audience stage", rec.audience_stage),
                    (
                        "Start by",
                        rec.timing.latest_safe_start.isoformat()
                        if rec.timing.latest_safe_start
                        else "—",
                    ),
                    ("Runs", rec.relation.value),
                    (
                        "Additional filming",
                        f"{rec.estimated_additional_filming_minutes.min_days}–"
                        f"{rec.estimated_additional_filming_minutes.max_days} min",
                    ),
                    (
                        "Estimated runway",
                        f"{rec.estimated_runway_days.min_days}–"
                        f"{rec.estimated_runway_days.max_days} days",
                    ),
                    ("Confidence", rec.confidence),
                    ("Decision", rec.decision.value.replace("_", " ")),
                ]
            )
            if rec.role.value != "primary" and rec.decision.value == "pending":
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    if st.button("Accept", key=f"acc_{rec.recommendation_id}"):
                        record_recommendation_decision(
                            campaign_dir, rec.recommendation_id, RecommendationDecision.ACCEPT
                        )
                        accept_portfolio(campaign_dir)
                        st.rerun()
                with c2:
                    if st.button("Not Now", key=f"nn_{rec.recommendation_id}"):
                        record_recommendation_decision(
                            campaign_dir, rec.recommendation_id, RecommendationDecision.NOT_NOW
                        )
                        st.rerun()
                with c3:
                    if st.button("Dismiss", key=f"di_{rec.recommendation_id}"):
                        record_recommendation_decision(
                            campaign_dir, rec.recommendation_id, RecommendationDecision.DISMISS
                        )
                        st.rerun()
                with c4:
                    if st.button("Adjust Objective", key=f"ao_{rec.recommendation_id}"):
                        record_recommendation_decision(
                            campaign_dir,
                            rec.recommendation_id,
                            RecommendationDecision.ADJUST_OBJECTIVE,
                        )
                        from ui import nav

                        nav.goto_workspace("brief")

    if intel.production_session:
        section("Combined production session")
        session = intel.production_session
        with st.container(border=True):
            quiet(session.notes)
            key_values(
                [
                    ("Campaigns", ", ".join(session.campaign_names)),
                    (
                        "Estimated filming",
                        f"{session.filming_minutes.min_days}–"
                        f"{session.filming_minutes.max_days} minutes",
                    ),
                    (
                        "Expected assets",
                        f"{session.expected_assets.min_days}–"
                        f"{session.expected_assets.max_days}",
                    ),
                    (
                        "Combined runway",
                        f"{session.combined_runway_days.min_days}–"
                        f"{session.combined_runway_days.max_days} days",
                    ),
                    ("Formats", ", ".join(session.expected_formats)),
                ]
            )
            with st.expander("Shot plan", expanded=False):
                for shot in session.shots:
                    tag = "must-have" if shot.must_have else "optional"
                    shared = " · shared" if shot.shared else ""
                    quiet(f"{shot.sequence_order}. [{tag}{shared}] {shot.description}")

    if intel.deliverable_estimate:
        section("Expected from this shoot")
        d = intel.deliverable_estimate
        runway = intel.current_runway()
        with st.container(border=True):
            key_values(
                [
                    (
                        "Final assets",
                        f"{d.final_assets.min_days} to {d.final_assets.max_days}",
                    ),
                    (
                        "Filming",
                        f"{d.filming_minutes.min_days} to {d.filming_minutes.max_days} minutes",
                    ),
                    (
                        "Editing",
                        f"{d.editing_minutes.min_days} to {d.editing_minutes.max_days} minutes",
                    ),
                    (
                        "Content runway",
                        f"Approximately {runway.days.min_days} to {runway.days.max_days} days"
                        if runway
                        else "—",
                    ),
                    ("Confidence", d.confidence),
                ]
            )
            quiet(d.evidence.summary)
            if intel.cadence:
                quiet("Recommended cadence")
                for c in intel.cadence:
                    quiet(
                        f"{c.platform}: {c.min_per_week}–{c.max_per_week} posts per week — {c.reason}"
                    )
                quiet(intel.cadence[0].evidence.summary)

    high_alerts = [a for a in intel.alerts if a.high_value][:3]
    if high_alerts:
        with st.expander("Opportunities and risks", expanded=False):
            for alert in high_alerts:
                quiet(f"{alert.alert_type.value.upper()}: {alert.title}")
                quiet(alert.detail)

    # Relevant opportunities (filtered)
    relevant = [o for o in intel.opportunities if o.category != "novelty" and o.score >= 0.55][:4]
    if relevant:
        with st.expander("Relevant calendar moments", expanded=False):
            for opp in relevant:
                when = opp.occurrence_date.isoformat() if opp.occurrence_date else "unconfirmed"
                quiet(f"{opp.name} · {when} · {opp.reason}")


def render_production_brief_success(campaign_dir: Path) -> bool:
    """Show ready state with Download. Returns True if a brief is ready."""
    if st.session_state.get("ws_brief_ready"):
        payload = st.session_state.get("ws_brief_payload") or {}
        _render_brief_download_panel(campaign_dir, payload)
        return True

    record = newest_brief(campaign_dir)
    if record is None:
        return False
    path = resolve_brief_file(campaign_dir, record)
    if path is None:
        return False
    ok, size_label = confirm_readable_file(path)
    if not ok:
        return False
    _render_brief_download_panel(
        campaign_dir,
        {
            "path": path,
            "filename": record.filename,
            "bytes": path.read_bytes(),
            "file_size_bytes": record.file_size_bytes,
            "summary": record.summary,
            "page_count": record.page_count,
        },
    )
    return True


def _render_brief_download_panel(campaign_dir: Path, payload: dict) -> None:
    section("Your Production Brief is ready.")
    summary = payload.get("summary") or {}
    with st.container(border=True):
        key_values(
            [
                ("Estimated output", summary.get("final_assets") or "—"),
                ("Estimated filming", summary.get("filming") or "—"),
                ("Estimated content runway", summary.get("runway") or "—"),
            ]
        )
        path = Path(payload["path"]) if payload.get("path") else None
        data = payload.get("bytes")
        if data is None and path and path.is_file():
            data = path.read_bytes()
        filename = payload.get("filename") or (path.name if path else "production-brief.pdf")
        size = human_size(int(payload.get("file_size_bytes") or (len(data) if data else 0)))
        if data:
            st.download_button(
                "Download Production Brief",
                data=data,
                file_name=filename,
                mime="application/pdf",
                type="primary",
                key="ws_brief_download",
            )
            quiet(f"{filename} · {size}")
            note("Ready.")
        cols = st.columns(2)
        with cols[0]:
            if path and st.button("Show in Finder", key="ws_brief_finder"):
                ok, message = show_in_finder(path)
                st.session_state["betty_flash"] = message if ok else message
                st.rerun()
        with cols[1]:
            from ui import nav

            if st.button("Continue to Capture", key="ws_brief_to_capture"):
                st.session_state.pop("ws_brief_ready", None)
                nav.goto_workspace("capture")

        if st.button("Generate new Production Brief", key="ws_brief_regen"):
            accept_plan_with_brief(campaign_dir)
            st.session_state["betty_flash"] = "Production Brief regenerated."
            st.rerun()

    render_brief_history(campaign_dir)


def render_brief_history(campaign_dir: Path) -> None:
    from src.campaign_intelligence.store import load_briefs_index

    index = load_briefs_index(campaign_dir)
    briefs = index.get("briefs") or []
    with st.expander("Production Brief History", expanded=False):
        if not briefs:
            quiet("No earlier production briefs.")
            return
        for raw in briefs[:8]:
            from src.campaign_intelligence.models import ProductionBriefRecord

            record = ProductionBriefRecord.from_dict(raw)
            path = resolve_brief_file(campaign_dir, record)
            quiet(
                f"{record.filename} · {human_size(record.file_size_bytes)} · "
                f"{record.page_count} pages"
            )
            if path and path.is_file():
                st.download_button(
                    f"Download {record.filename}",
                    data=path.read_bytes(),
                    file_name=record.filename,
                    mime="application/pdf",
                    key=f"hist_brief_{record.brief_id}",
                )


def accept_plan_with_brief(campaign_dir: Path) -> dict:
    result = accept_plan_and_generate_brief(campaign_dir)
    brief = result["brief"]
    st.session_state["ws_brief_ready"] = True
    st.session_state["ws_brief_payload"] = {
        "path": brief["path"],
        "filename": brief["filename"],
        "bytes": brief["bytes"],
        "file_size_bytes": brief["file_size_bytes"],
        "summary": brief["summary"],
        "page_count": brief["page_count"],
    }
    return result


def render_capture_reestimate(campaign_dir: Path, planned_shots: int) -> None:
    intel = load_intelligence(campaign_dir)
    if intel is None:
        return
    with st.expander("Update runway after capture", expanded=False):
        quiet("After you review footage, revise the operational estimate. Pre-shoot history is kept.")
        usable = st.number_input(
            "Usable shots from this shoot",
            min_value=0,
            max_value=50,
            value=max(1, planned_shots - 1),
            key="intel_usable_shots",
        )
        note_text = st.text_input(
            "What changed?",
            value="",
            key="intel_capture_note",
            placeholder="Example: Lighting inconsistency reduced publishable lifestyle clips.",
        )
        actual_mins = st.number_input(
            "Actual filming minutes (optional)",
            min_value=0,
            max_value=600,
            value=0,
            key="intel_actual_mins",
        )
        if st.button("Update estimate", key="intel_revise_runway"):
            updated = update_estimates_after_capture(
                campaign_dir,
                usable_shots=int(usable),
                planned_shots=planned_shots,
                quality_note=note_text.strip(),
                actual_filming_minutes=int(actual_mins) or None,
            )
            latest = updated.current_runway("post_capture")
            prior = updated.current_runway("pre_shoot")
            if latest and prior:
                st.session_state["betty_flash"] = (
                    f"Runway updated: {prior.days.min_days}–{prior.days.max_days} days → "
                    f"{latest.days.min_days}–{latest.days.max_days} days. {latest.reason_for_change}"
                )
            st.rerun()
        # Show history
        if intel.runway_history:
            quiet("Estimate history")
            for item in intel.runway_history:
                quiet(
                    f"{item.phase}: {item.days.min_days}–{item.days.max_days} days "
                    f"({item.confidence})"
                    + (f" — {item.reason_for_change}" if item.reason_for_change else "")
                )
