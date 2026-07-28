"""Review — the creative critique, and the revisions that come out of it.

Every recommendation is read in context and shown with what BettyOS can actually
do about it: apply it, propose wording for it, or say plainly what has to be
supplied first. Nothing is applied without an explicit approval, and every button
here writes to `revisions/revision_requests.json` rather than to session state.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from services import revision_store as store
from services import revision_types as rt
from services.revision_classifier import Classification, load_classifications
from ui import nav
from ui.campaign_state import CampaignState, count_phrase, finished_versions_sent_to_review
from ui.components import (
    Stat,
    blocked_state,
    caption_body,
    comparison,
    download_file,
    empty_state,
    flash,
    key_values,
    note,
    option_card,
    page_header,
    progress_rail,
    quiet,
    report,
    requirement_panel,
    section,
    show_badges,
    show_flashes,
    stat_strip,
)
from ui.data_access import load_latest_scores
from ui.status import (
    Status,
    capability_status,
    content_status_for_approval,
    priority_status,
    recommendation_status,
    revision_request_status,
)
from ui.workflow_service import (
    apply_revision_request,
    attach_revision_asset,
    cancel_revision_selection,
    classify_recommendations,
    defer_revision,
    dismiss_recommendation,
    dismiss_revision,
    edit_revision_selection,
    generate_revision_options,
    resume_revision,
    retry_revision,
    revision_preview,
    run_creative_review,
    save_revision_instruction,
    select_revision_option,
    set_revision_change,
    start_revision,
)

SECTIONS = ["Creative Review", "Revisions"]
SECTION_KEY = "review_section"

SCORE_ORDER = (
    "brand_alignment",
    "business_alignment",
    "emotional_specificity",
    "editorial_quality",
    "visual_consistency",
    "conversion_potential",
)

OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _acted(result) -> None:
    """Report an action and redraw, so what shows is what was saved."""
    flash(result)
    st.rerun()


def render(state: CampaignState) -> None:
    page_header("Review", "What a creative director would say, and what to do about it.")
    progress_rail(state.steps)
    show_flashes()

    if not state.exists:
        empty_state("No campaign selected", "Open a campaign to review its work.")
        if st.button("Go to Campaigns", type="primary"):
            nav.goto("Campaigns")
        return

    choice = nav.step_selector("Section", SECTIONS, key=SECTION_KEY)
    st.write("")
    if choice == SECTIONS[0]:
        _creative_review(state)
    else:
        _revisions(state)


# --- Creative review --------------------------------------------------------

def _creative_review(state: CampaignState) -> None:
    if not state.versions:
        blocked_state(
            "Review unavailable",
            "This campaign must have at least one render before Creative Review can run.",
        )
        if st.button("Go to Create", type="primary"):
            nav.goto("Create", "3. Render")
        return

    scores = load_latest_scores()
    _run_control(state, has_review=bool(scores))
    _finished_versions(state)

    if not scores:
        empty_state(
            "No review yet",
            "Run Creative Review to score this campaign and get specific improvements.",
        )
        return

    _scores(scores)
    _improvements(scores)
    _recommendations(state, scores)


def _run_control(state: CampaignState, *, has_review: bool) -> None:
    with st.container(border=True):
        columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
        with columns[0]:
            if not has_review:
                quiet("Creative Review reads your content and renders, then scores the campaign.")
            elif state.review_is_current:
                quiet("This review covers the current renders.")
            else:
                quiet("Renders have changed since this review. Run it again for current scores.")
        with columns[1]:
            label = "Run Creative Review" if not has_review else "Run again"
            if st.button(label, type="primary", use_container_width=True, key="run_review"):
                with st.status("Reviewing the campaign…", expanded=True) as status:
                    result = run_creative_review(
                        package_path=state.package_path,
                        campaign_dir=state.path,
                    )
                    status.update(
                        label=result.message,
                        state="complete" if result.ok else "error",
                    )
                _acted(result)


def _score_value(entry: Any) -> float | None:
    if not isinstance(entry, dict):
        return None
    try:
        return float(entry.get("score"))
    except (TypeError, ValueError):
        return None


def _scores(scores: dict[str, Any]) -> None:
    overall = scores.get("overall_readiness")
    overall_score = _score_value(overall)
    if overall_score is None:
        try:
            overall_score = float(scores.get("overall_readiness_score"))
        except (TypeError, ValueError):
            overall_score = None

    stats = [Stat("Overall", f"{overall_score:.1f}" if overall_score is not None else "—",
                  "positive" if (overall_score or 0) >= 7 else "attention")]
    for key in SCORE_ORDER:
        entry = scores.get(key)
        value = _score_value(entry)
        if value is None:
            continue
        label = str((entry or {}).get("label") or key.replace("_", " ").title())
        stats.append(Stat(label, f"{value:.1f}"))
    stat_strip(stats)

    if isinstance(overall, dict) and overall.get("reason"):
        quiet(str(overall["reason"]))

    with st.expander("Why each score", expanded=False):
        for key in SCORE_ORDER:
            entry = scores.get(key)
            value = _score_value(entry)
            if value is None:
                continue
            label = str((entry or {}).get("label") or key.replace("_", " ").title())
            st.markdown(f"**{label} — {value:.1f}**")
            quiet(str((entry or {}).get("reason") or ""))


# --- Finished versions from Studio ------------------------------------------

_FINISH_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


def _finished_versions(state: CampaignState) -> None:
    """Finished versions Studio handed to Review, and where they go next.

    Send to Review is what puts a finish here. Review shows the finished file
    itself — not the render it came from — so the work being judged is the work
    that would ship. The decision is still made once, under Approvals.
    """
    from studio.versions import resolve_finish_output

    pairs = finished_versions_sent_to_review(state.versions)
    if not pairs:
        return

    section(
        "Finished versions from Studio",
        "Sent from Studio. The sign-off itself happens under Approvals.",
    )
    for version, record in pairs:
        output = resolve_finish_output(version.folder, record)
        with st.container(border=True):
            show_badges([content_status_for_approval(record.approval_status)])
            st.markdown(
                f'<div class="betty-section">{version.display_name} — version '
                f"{version.version} · {record.finish_version_id}</div>",
                unsafe_allow_html=True,
            )
            left, right = st.columns([1, 1], gap="large")

            with left:
                if output is None:
                    blocked_state(
                        "Finished file missing",
                        "The finished output recorded for this version is no longer on disk.",
                    )
                elif output.suffix.lower() in {".mp4", ".mov"}:
                    st.video(str(output))
                else:
                    st.image(str(output), use_container_width=True)

            with right:
                key_values(
                    [
                        ("Finished version", record.finish_version_id),
                        ("Built from", f"{version.display_name} version {version.version}"),
                        ("Colour recipe", record.recipe_id or "None applied"),
                        ("Finished file", output.name if output else "Missing"),
                        ("Sent to Review", _stamp(record.updated_at)),
                        (
                            "Decision",
                            content_status_for_approval(record.approval_status).label,
                        ),
                    ]
                )
                if output is not None:
                    download_file(
                        output,
                        label="Download finished file",
                        key=f"dl_finish_{version.key}_{record.finish_version_id}",
                        mime=_FINISH_MIME.get(output.suffix.lower(), "application/octet-stream"),
                    )
                if st.button(
                    "Go to Approvals",
                    key=f"finish_to_approvals_{version.key}_{record.finish_version_id}",
                    use_container_width=True,
                ):
                    nav.goto("Approvals")


def _stamp(iso: str | None) -> str:
    from ui.capability import parse_iso

    moment = parse_iso(iso)
    return moment.strftime("%-d %b %Y, %H:%M") if moment else "—"


def _improvements(scores: dict[str, Any]) -> None:
    items = [str(i) for i in scores.get("highest_impact_improvements") or []]
    if not items:
        return
    section("Highest-impact improvements")
    with st.container(border=True):
        for index, item in enumerate(items, start=1):
            st.markdown(f"**{index}.** {item}")


# --- Capability classification ----------------------------------------------

def _classifications(
    state: CampaignState, recommendations: list[dict[str, Any]]
) -> dict[str, Classification]:
    """Cached capability readings, classifying anything new or edited."""
    from services.revision_classifier import fingerprint

    stored = load_classifications(state.path)
    pending = [
        rec
        for rec in recommendations
        if str(rec.get("recommendation_id") or "") not in stored
        or stored[str(rec.get("recommendation_id"))].fingerprint != fingerprint(rec)
    ]
    if not pending:
        return stored

    with st.status(
        f"Working out what BettyOS can do about "
        f"{count_phrase(len(pending), 'recommendation')}…",
        expanded=False,
    ) as status:
        result = classify_recommendations(state.path, pending)
        status.update(
            label=result.message,
            state="complete" if result.ok else "error",
        )
    if not result.ok:
        report(result)
        return stored
    return load_classifications(state.path)


def _recommendations(state: CampaignState, scores: dict[str, Any]) -> None:
    recommendations = [r for r in scores.get("recommendations") or [] if isinstance(r, dict)]
    section(
        "Recommendations",
        "BettyOS proposes the change; you approve it. No render is ever overwritten.",
    )
    if not recommendations:
        empty_state("No recommendations", "This review did not propose specific changes.")
        return

    classifications = _classifications(state, recommendations)

    columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
    with columns[0]:
        tally: dict[str, int] = {}
        for rec in recommendations:
            found = classifications.get(str(rec.get("recommendation_id") or ""))
            if found:
                tally[found.capability] = tally.get(found.capability, 0) + 1
        parts = [
            f"{count} {capability_status(key).label.lower()}"
            for key, count in tally.items()
        ]
        quiet("; ".join(parts) if parts else "Not checked yet.")
    with columns[1]:
        if st.button("Re-check capability", key="reclassify_all", use_container_width=True):
            with st.spinner("Reading every recommendation again…"):
                result = classify_recommendations(state.path, recommendations, force=True)
            _acted(result)

    for rec in recommendations:
        _recommendation_card(state, rec, classifications.get(str(rec.get("recommendation_id"))))


def _asset_line(rec: dict[str, Any], classification: Classification | None) -> str:
    """The asset as this campaign knows it, plus the reviewer's name for it."""
    reviewed = str(rec.get("affected_asset") or "").strip()
    resolved = str(classification.asset_name if classification else "").strip()
    if not resolved:
        return reviewed or "—"
    if reviewed and reviewed.lower() != resolved.lower():
        return f"{resolved} — the review calls it {reviewed}"
    return resolved


def _recommendation_card(
    state: CampaignState,
    rec: dict[str, Any],
    classification: Classification | None,
) -> None:
    rec_id = str(rec.get("recommendation_id") or "")
    status = recommendation_status(str(rec.get("status") or "proposed"))
    priority = priority_status(str(rec.get("priority") or "medium"))
    request = store.open_request_for_recommendation(state.path, rec_id)
    applied = [
        r
        for r in store.requests_for_recommendation(state.path, rec_id)
        if str(r.get("status")) == store.APPLIED
    ]

    badges: list[Status] = [status, priority]
    if classification is not None:
        badges.append(capability_status(classification.capability))
    if request is not None:
        badges.append(revision_request_status(str(request.get("status") or "")))

    with st.container(border=True):
        show_badges(badges)
        st.markdown(
            f'<div class="betty-section">{rec.get("title") or "Recommendation"}</div>',
            unsafe_allow_html=True,
        )
        key_values(
            [
                ("Affected asset", _asset_line(rec, classification)),
                ("Why it matters", rec.get("rationale") or "—"),
                ("Expected outcome", rec.get("expected_changes") or "—"),
                (
                    "What BettyOS can do",
                    capability_status(classification.capability).label
                    if classification
                    else "Not checked yet",
                ),
            ]
        )
        with st.expander("The full recommendation as written", expanded=False):
            quiet(str(rec.get("full_instruction") or "No instruction recorded."))

        if applied and request is None:
            _applied_outcome(state, applied)
            return

        if classification is None:
            note("BettyOS has not worked out what it can do about this one yet.")
            return
        note(classification.rationale)

        if classification.needs_human:
            _human_panel(state, rec, rec_id, classification, request)
        elif classification.is_ready:
            _ready_panel(state, rec, rec_id, classification, request)
        else:
            _ai_panel(state, rec, rec_id, classification, request)


def _applied_outcome(state: CampaignState, applied: list[dict[str, Any]]) -> None:
    """What a revision on this recommendation actually produced."""
    st.divider()
    latest = applied[-1]
    replacement = store.selected_value(latest)
    if latest.get("original_value") or replacement:
        comparison(
            latest.get("original_value") or "—",
            replacement or "—",
            before_label="Was",
            after_label="Now",
        )
    key_values(
        [
            ("Produced", f"version {latest.get('resulting_render_version_id')}"),
            ("Applied", latest.get("applied_at") or "—"),
            ("Waiting on", "Your approval of the new version, under Approvals"),
        ]
    )
    columns = st.columns([1, 1, 2], gap="small")
    with columns[0]:
        if st.button(
            "Open New Version",
            key=f"applied_open_{latest.get('revision_request_id')}",
            type="primary",
            use_container_width=True,
        ):
            nav.goto("Approvals")
    with columns[1]:
        if st.button(
            "See the revision",
            key=f"applied_see_{latest.get('revision_request_id')}",
            use_container_width=True,
        ):
            nav.goto("Revisions")


# --- AI-assisted flow -------------------------------------------------------

def _ai_panel(
    state: CampaignState,
    rec: dict[str, Any],
    rec_id: str,
    classification: Classification,
    request: dict[str, Any] | None,
) -> None:
    st.divider()
    revision_field = rt.field_for(str(classification.target_field or ""))
    section(revision_field.label if revision_field else "Current wording", "As it stands now.")
    caption_body(classification.original_value)

    if request is None:
        _ai_start(state, rec, rec_id, classification)
        return

    request_id = str(request.get("revision_request_id"))
    _instruction_editor(state, request, request_id)
    _deferred_note(state, request, request_id)

    if request.get("failure_reason"):
        blocked_state("That did not work", str(request["failure_reason"]))

    options = list(request.get("generated_options") or [])
    if not options:
        _generate_controls(state, request_id, has_options=False)
        return

    _options_list(state, request, request_id, options)
    _generate_controls(state, request_id, has_options=True)

    if request.get("selected_option_id"):
        _apply_panel(state, request, request_id)


def _ai_start(
    state: CampaignState,
    rec: dict[str, Any],
    rec_id: str,
    classification: Classification,
) -> None:
    quiet(
        "BettyOS will write options from the Brand Guide. Nothing is applied until you "
        "approve one."
    )
    columns = st.columns([1, 1, 1], gap="small")
    with columns[0]:
        if st.button(
            "Generate Suggestions",
            key=f"generate_{rec_id}",
            type="primary",
            use_container_width=True,
        ):
            _run_generation(state, rec, rec_id, classification)
    with columns[1]:
        if st.button("Edit Instruction", key=f"edit_instruction_{rec_id}", use_container_width=True):
            result = start_revision(
                state.path, recommendation=rec, classification=classification
            )
            _acted(result)
    with columns[2]:
        if st.button("Dismiss", key=f"dismiss_rec_{rec_id}", use_container_width=True):
            result = dismiss_recommendation(rec_id)
            _acted(result)


def _run_generation(
    state: CampaignState,
    rec: dict[str, Any],
    rec_id: str,
    classification: Classification,
) -> None:
    with st.status("Writing options from the Brand Guide…", expanded=True) as status:
        opened = start_revision(state.path, recommendation=rec, classification=classification)
        if not opened.ok:
            report(opened)
            status.update(label=opened.message, state="error")
            return
        request = (opened.data or {}).get("request") or {}
        result = generate_revision_options(
            state.path, str(request.get("revision_request_id")), count=3
        )
        status.update(label=result.message, state="complete" if result.ok else "error")
    _acted(result)


def _deferred_note(state: CampaignState, request: dict[str, Any], request_id: str) -> None:
    """Saved for later is a real state, so it has to be visible and reversible."""
    if not request.get("deferred_at"):
        return
    columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
    with columns[0]:
        note(
            f"Saved for later on {request['deferred_at']}. Everything generated so far is kept."
        )
    with columns[1]:
        if st.button("Pick this up", key=f"resume_card_{request_id}", use_container_width=True):
            _acted(resume_revision(state.path, request_id))


def _instruction_editor(
    state: CampaignState, request: dict[str, Any], request_id: str
) -> None:
    with st.expander("The instruction BettyOS is following", expanded=False):
        quiet(
            "Edit this to steer the suggestions. The recommendation itself is kept as written."
        )
        edited = st.text_area(
            "Instruction",
            value=str(request.get("instruction") or ""),
            key=f"instruction_{request_id}",
            height=100,
            label_visibility="collapsed",
        )
        if edited.strip() != str(request.get("instruction") or "").strip():
            if st.button(
                "Save Instruction", key=f"save_instruction_{request_id}", type="primary"
            ):
                result = save_revision_instruction(state.path, request_id, edited)
                _acted(result)
        elif str(request.get("instruction") or "").strip() != str(
            request.get("default_instruction") or ""
        ).strip():
            note("Edited. The original recommendation is unchanged.")


def _verdict_badge(option: dict[str, Any]) -> Status:
    from services.revision_validation import (
        NEEDS_ATTENTION,
        PASS,
        REJECTED,
        VERDICT_LABELS,
    )

    verdict = str((option.get("validation") or {}).get("verdict") or PASS)
    tone = {PASS: "positive", NEEDS_ATTENTION: "attention", REJECTED: "blocked"}.get(
        verdict, "neutral"
    )
    return Status(verdict, VERDICT_LABELS.get(verdict, verdict), tone)


def _options_list(
    state: CampaignState,
    request: dict[str, Any],
    request_id: str,
    options: list[dict[str, Any]],
) -> None:
    from services.revision_validation import REJECTED

    st.write("")
    section("Suggested options", "Each one is checked against the Brand Guide before you see it.")
    selected_id = str(request.get("selected_option_id") or "")

    for index, option in enumerate(options):
        option_id = str(option.get("option_id") or f"option_{index + 1:03d}")
        verdict = str((option.get("validation") or {}).get("verdict") or "pass")
        rejected = verdict == REJECTED
        chosen = option_id == selected_id
        letter = OPTION_LETTERS[index % len(OPTION_LETTERS)]

        with st.container(border=True):
            show_badges([_verdict_badge(option)])
            option_card(
                f"Option {letter}",
                str(option.get("text") or ""),
                why=str(option.get("rationale") or ""),
                tone="chosen" if chosen else ("rejected" if rejected else ""),
            )
            issues = (option.get("validation") or {}).get("issues") or []
            if issues:
                for issue in issues:
                    note(str(issue.get("message") or ""))

            columns = st.columns([1, 1, 1.4], gap="small")
            with columns[0]:
                if st.button(
                    "Selected" if chosen else "Select",
                    key=f"select_{request_id}_{option_id}",
                    type="primary" if not chosen else "secondary",
                    disabled=chosen or rejected,
                    use_container_width=True,
                    help=(
                        "This option did not pass the brand checks. Edit it and it will be "
                        "checked again."
                        if rejected
                        else None
                    ),
                ):
                    result = select_revision_option(state.path, request_id, option_id)
                    _acted(result)
            with columns[1]:
                if st.button(
                    "Edit",
                    key=f"open_edit_{request_id}_{option_id}",
                    use_container_width=True,
                ):
                    st.session_state[f"editing_{request_id}"] = option_id
                    st.rerun()
            with columns[2]:
                if st.button(
                    "Regenerate Similar",
                    key=f"similar_{request_id}_{option_id}",
                    use_container_width=True,
                ):
                    with st.status("Taking that direction further…", expanded=True) as status:
                        result = generate_revision_options(
                            state.path,
                            request_id,
                            count=3,
                            similar_to_option_id=option_id,
                        )
                        status.update(
                            label=result.message, state="complete" if result.ok else "error"
                        )
                    _acted(result)

            if st.session_state.get(f"editing_{request_id}") == option_id:
                _option_editor(state, request, request_id, option)


def _option_editor(
    state: CampaignState,
    request: dict[str, Any],
    request_id: str,
    option: dict[str, Any],
) -> None:
    option_id = str(option.get("option_id"))
    starting = (
        str(request.get("edited_value") or "")
        if str(request.get("selected_option_id") or "") == option_id
        else ""
    ) or str(option.get("text") or "")

    constraints = request.get("constraints_used") or {}
    limit_parts = []
    if constraints.get("max_words"):
        limit_parts.append(f"{int(constraints['max_words'])} words at most")
    if constraints.get("max_chars"):
        limit_parts.append(f"{int(constraints['max_chars'])} characters at most")
    if limit_parts:
        note(" · ".join(limit_parts))

    edited = st.text_area(
        "Your wording",
        value=starting,
        key=f"option_text_{request_id}_{option_id}",
        height=90,
    )
    columns = st.columns([1, 1], gap="small")
    with columns[0]:
        if st.button(
            "Save wording",
            key=f"save_option_{request_id}_{option_id}",
            type="primary",
            use_container_width=True,
        ):
            result = edit_revision_selection(
                state.path, request_id, edited, option_id=option_id
            )
            if result.ok:
                st.session_state[f"editing_{request_id}"] = None
            _acted(result)
    with columns[1]:
        if st.button(
            "Stop editing",
            key=f"close_edit_{request_id}_{option_id}",
            use_container_width=True,
        ):
            st.session_state[f"editing_{request_id}"] = None
            st.rerun()


def _generate_controls(state: CampaignState, request_id: str, *, has_options: bool) -> None:
    st.write("")
    columns = st.columns([1.2, 1, 1, 1], gap="small")
    with columns[0]:
        label = "Generate More Options" if has_options else "Generate Suggestions"
        if st.button(
            label,
            key=f"generate_more_{request_id}",
            type="primary" if not has_options else "secondary",
            use_container_width=True,
        ):
            with st.status("Writing options from the Brand Guide…", expanded=True) as status:
                result = generate_revision_options(state.path, request_id, count=3)
                status.update(label=result.message, state="complete" if result.ok else "error")
            _acted(result)
    with columns[1]:
        if st.button(
            "Start Again",
            key=f"regenerate_all_{request_id}",
            use_container_width=True,
            disabled=not has_options,
            help="Replace every option with a fresh set.",
        ):
            with st.status("Starting again…", expanded=True) as status:
                result = generate_revision_options(
                    state.path, request_id, count=3, replace=True
                )
                status.update(label=result.message, state="complete" if result.ok else "error")
            _acted(result)
    with columns[2]:
        if st.button("Save for Later", key=f"defer_{request_id}", use_container_width=True):
            result = defer_revision(state.path, request_id)
            _acted(result)
    with columns[3]:
        if st.button("Cancel", key=f"cancel_request_{request_id}", use_container_width=True):
            result = dismiss_revision(state.path, request_id)
            _acted(result)


def _apply_panel(state: CampaignState, request: dict[str, Any], request_id: str) -> None:
    preview = revision_preview(state.path, request)
    st.write("")
    with st.container(border=True):
        section("Before you apply this")
        if not preview.get("ok"):
            blocked_state("This cannot be applied yet", str(preview.get("reason") or ""))
            if st.button("Clear selection", key=f"clear_{request_id}"):
                result = cancel_revision_selection(state.path, request_id)
                _acted(result)
            return

        comparison(preview.get("before"), preview.get("after"))
        key_values(
            [
                ("Field", preview.get("field_label")),
                ("Asset", preview.get("asset_name")),
                (
                    "Version",
                    f"version {preview.get('from_version')} stays as it is; this creates "
                    f"version {preview.get('to_version')}",
                ),
                (
                    "New version arrives as",
                    "Awaiting Review, for you to approve under Approvals",
                ),
            ]
        )
        verdict = preview.get("validation") or {}
        if verdict.get("issues"):
            for issue in verdict["issues"]:
                note(str(issue.get("message") or ""))

        columns = st.columns([1.2, 1, 1], gap="small")
        with columns[0]:
            if st.button(
                "Apply Revision",
                key=f"apply_{request_id}",
                type="primary",
                use_container_width=True,
            ):
                _run_apply(state, request_id)
        with columns[1]:
            if st.button(
                "Change selection", key=f"unselect_{request_id}", use_container_width=True
            ):
                result = cancel_revision_selection(state.path, request_id)
                _acted(result)
        with columns[2]:
            if st.button(
                "Save for Later", key=f"defer_selected_{request_id}", use_container_width=True
            ):
                result = defer_revision(state.path, request_id)
                _acted(result)


def _run_apply(state: CampaignState, request_id: str) -> None:
    with st.status("Building the new version…", expanded=True) as status:
        result = apply_revision_request(state.path, request_id)
        status.update(label=result.message, state="complete" if result.ok else "error")
    _acted(result)


# --- Ready to apply ---------------------------------------------------------

def _ready_panel(
    state: CampaignState,
    rec: dict[str, Any],
    rec_id: str,
    classification: Classification,
    request: dict[str, Any] | None,
) -> None:
    st.divider()
    if request is None:
        quiet(
            "BettyOS can make this change itself. Opening it will show the exact setting "
            "change before anything is applied."
        )
        columns = st.columns([1, 1, 2], gap="small")
        with columns[0]:
            if st.button(
                "Review the change",
                key=f"open_ready_{rec_id}",
                type="primary",
                use_container_width=True,
            ):
                result = start_revision(
                    state.path, recommendation=rec, classification=classification
                )
                _acted(result)
        with columns[1]:
            if st.button("Dismiss", key=f"dismiss_ready_{rec_id}", use_container_width=True):
                result = dismiss_recommendation(rec_id)
                _acted(result)
        return

    request_id = str(request.get("revision_request_id"))
    _deferred_note(state, request, request_id)
    if request.get("failure_reason"):
        blocked_state("That did not work", str(request["failure_reason"]))

    if classification.required_inputs:
        _change_controls(state, request, request_id, classification)

    preview = revision_preview(state.path, request)
    if preview.get("ok"):
        section("The exact change")
        for label, before, after in preview.get("change_rows") or []:
            key_values([(label, "")])
            comparison(before, after)
        key_values(
            [
                (
                    "Version",
                    f"version {preview.get('from_version')} stays as it is; this creates "
                    f"version {preview.get('to_version')}",
                ),
                ("New version arrives as", "Awaiting Review"),
            ]
        )
        columns = st.columns([1.2, 1, 1], gap="small")
        with columns[0]:
            if st.button(
                "Apply Revision",
                key=f"apply_ready_{request_id}",
                type="primary",
                use_container_width=True,
            ):
                _run_apply(state, request_id)
        with columns[1]:
            if st.button(
                "Save for Later", key=f"defer_ready_{request_id}", use_container_width=True
            ):
                result = defer_revision(state.path, request_id)
                _acted(result)
        with columns[2]:
            if st.button("Dismiss", key=f"dismiss_req_{request_id}", use_container_width=True):
                result = dismiss_revision(state.path, request_id)
                _acted(result)
    else:
        note(str(preview.get("reason") or "Confirm the value above before applying."))


def _change_controls(
    state: CampaignState,
    request: dict[str, Any],
    request_id: str,
    classification: Classification,
) -> None:
    """Controls for a change BettyOS can make once the value is confirmed."""
    from services.revision_context import available_source_assets, load_render_config, resolve_asset

    target = resolve_asset(
        state.path,
        affected_asset=str(request.get("affected_asset_name") or ""),
        affected_files=[str(request.get("affected_asset_id") or "")],
    )
    if target is None:
        blocked_state("Asset not found", "BettyOS can no longer find this asset in the campaign.")
        return
    config = load_render_config(state.path, target)
    clips = config.clip_names()
    revision_type = str(request.get("revision_type") or "")
    current = dict(request.get("proposed_change") or {})

    section("Confirm the change", "; ".join(classification.required_inputs))
    change: dict[str, Any] = {}

    if revision_type in {"cta_timing_change", "overlay_timing_change"}:
        change["cta_appear_at_seconds"] = st.number_input(
            "The call to action should appear at",
            min_value=0.0,
            max_value=float(config.target_duration_seconds or 60.0),
            value=float(current.get("cta_appear_at_seconds") or config.cta_appear_at_seconds or 0.0),
            step=0.5,
            key=f"cta_at_{request_id}",
            help="Seconds from the start of the video.",
        )
    elif revision_type == "duration_change":
        change["target_duration_seconds"] = st.number_input(
            "Total duration in seconds",
            min_value=2.0,
            max_value=120.0,
            value=float(current.get("target_duration_seconds") or config.target_duration_seconds or 15.0),
            step=1.0,
            key=f"duration_{request_id}",
        )
    elif revision_type == "clip_remove":
        change["remove_clips"] = st.multiselect(
            "Clips to remove",
            options=clips,
            default=[c for c in current.get("remove_clips") or [] if c in clips],
            key=f"remove_{request_id}",
            help="At least one clip has to remain.",
        )
    elif revision_type in {"clip_reorder", "slide_reorder"}:
        change["clip_order"] = st.multiselect(
            "Play the clips in this order",
            options=clips,
            default=[c for c in current.get("clip_order") or [] if c in clips] or clips,
            key=f"order_{request_id}",
            help="Pick them in the order you want them to play.",
        )
    elif revision_type == "source_asset_replace":
        columns = st.columns(2, gap="small")
        with columns[0]:
            replace = st.selectbox(
                "Replace this clip",
                options=clips,
                key=f"replace_{request_id}",
            )
        with columns[1]:
            available = [
                path for path in available_source_assets(state.path)
                if not any(name in path for name in clips)
            ]
            replacement = st.selectbox(
                "With this source asset",
                options=available,
                key=f"replacement_{request_id}",
                format_func=lambda path: path.rsplit("/", 1)[-1],
            ) if available else None
        if replacement:
            change = {"replace_clips": [replace], "replacement_asset": replacement}
        else:
            blocked_state(
                "No other source asset",
                "Every indexed clip is already in this render, so there is nothing to swap in.",
            )
            return

    if st.button("Save the change", key=f"save_change_{request_id}", type="primary"):
        result = set_revision_change(state.path, request_id, change)
        _acted(result)


# --- Human input required ---------------------------------------------------

def _human_panel(
    state: CampaignState,
    rec: dict[str, Any],
    rec_id: str,
    classification: Classification,
    request: dict[str, Any] | None,
) -> None:
    st.divider()
    requirement = classification.requirement or {}
    headline = str(requirement.get("headline") or "Human input needed")
    specifics = [str(item) for item in requirement.get("specifics") or []]
    action = str(requirement.get("action") or "")
    unlocks = str(requirement.get("unlocks") or "")

    requirement_panel(headline, specifics, unlocks=unlocks)

    if not action:
        st.write("")
        quiet("There is nothing to upload for this one — it needs a change to BettyOS itself.")
        if st.button("Dismiss", key=f"dismiss_human_{rec_id}", use_container_width=False):
            result = dismiss_recommendation(rec_id)
            _acted(result)
        return

    if request is None:
        st.write("")
        columns = st.columns([1, 1, 2], gap="small")
        with columns[0]:
            if st.button(
                action, key=f"open_human_{rec_id}", type="primary", use_container_width=True
            ):
                result = start_revision(
                    state.path, recommendation=rec, classification=classification
                )
                _acted(result)
        with columns[1]:
            if st.button("Dismiss", key=f"dismiss_human_{rec_id}", use_container_width=True):
                result = dismiss_recommendation(rec_id)
                _acted(result)
        return

    request_id = str(request.get("revision_request_id"))
    supplied = list(request.get("supplied_assets") or [])
    if supplied:
        key_values([("Supplied", ", ".join(str(item.get("filename")) for item in supplied))])
        quiet(
            "These are now in this campaign's source assets. Rebuild the piece in Create to "
            "use them."
        )

    accepts = [str(x).lstrip(".") for x in requirement.get("accepts") or []]
    uploaded = st.file_uploader(
        action,
        type=accepts or None,
        key=f"upload_{request_id}",
        accept_multiple_files=False,
    )
    columns = st.columns([1, 1, 2], gap="small")
    with columns[0]:
        if st.button(
            "Add to campaign",
            key=f"attach_{request_id}",
            type="primary",
            disabled=uploaded is None,
            use_container_width=True,
        ):
            result = attach_revision_asset(
                state.path,
                request_id,
                filename=uploaded.name,
                data=uploaded.getvalue(),
            )
            _acted(result)
    with columns[1]:
        if st.button("Dismiss", key=f"dismiss_human_req_{request_id}", use_container_width=True):
            result = dismiss_revision(state.path, request_id)
            _acted(result)


# --- Revisions --------------------------------------------------------------

def _revisions(state: CampaignState) -> None:
    counts = state.revision_counts
    stat_strip(
        [
            Stat(
                "Awaiting decision",
                counts["awaiting_decision"],
                "attention" if counts["awaiting_decision"] else "neutral",
            ),
            Stat(
                "Ready to apply",
                counts["ready_to_apply"],
                "attention" if counts["ready_to_apply"] else "neutral",
            ),
            Stat(
                "Needs your input",
                counts["needs_human"],
                "attention" if counts["needs_human"] else "neutral",
            ),
            Stat("Failed", counts["failed"], "blocked" if counts["failed"] else "neutral"),
            Stat(
                "Applied",
                counts["applied"],
                "positive" if counts["applied"] else "neutral",
            ),
        ]
    )

    groups = store.grouped_requests(state.path)
    if not groups:
        empty_state(
            "No revisions yet",
            "Open a recommendation in Creative Review to start one.",
        )
        if st.button("Go to Creative Review", type="primary", key="to_review"):
            nav.goto("Review", "Creative Review")
        return

    quiet("Final sign-off for a new version stays on Approvals.")
    for label, requests in groups:
        section(label)
        for request in requests:
            _revision_row(state, request)


def _revision_row(state: CampaignState, request: dict[str, Any]) -> None:
    request_id = str(request.get("revision_request_id"))
    status_key = str(request.get("status") or "")
    status = revision_request_status(status_key)
    capability = capability_status(str(request.get("capability") or ""))
    recommendation = request.get("original_recommendation") or {}

    with st.container(border=True):
        show_badges([status, capability])
        st.markdown(
            f'<div class="betty-section">{store.describe(request)}</div>',
            unsafe_allow_html=True,
        )
        replacement = store.selected_value(request)
        key_values(
            [
                ("Content piece", request.get("affected_asset_name") or "—"),
                ("Change", rt.type_label(str(request.get("revision_type") or ""))),
                (
                    "From recommendation",
                    recommendation.get("title") or request.get("recommendation_id") or "—",
                ),
                ("Started", request.get("created_at") or "—"),
            ]
        )
        if request.get("original_value") or replacement:
            comparison(
                request.get("original_value") or "—",
                replacement or "Not chosen yet",
                after_label="Chosen replacement" if replacement else "No choice made yet",
            )
        if request.get("proposed_change"):
            key_values(
                [
                    (
                        "Setting change",
                        ", ".join(
                            f"{key.replace('_', ' ')}: {value}"
                            for key, value in (request["proposed_change"] or {}).items()
                        ),
                    )
                ]
            )
        if request.get("resulting_render_version_id"):
            key_values(
                [
                    ("Produced", f"version {request['resulting_render_version_id']}"),
                    ("Applied", request.get("applied_at") or "—"),
                ]
            )
        if request.get("failure_reason"):
            blocked_state("This revision failed", str(request["failure_reason"]))
        if request.get("deferred_at") and status_key not in {store.APPLIED, store.DISMISSED}:
            note("Saved for later.")

        _revision_row_actions(state, request, request_id, status_key)


def _revision_row_actions(
    state: CampaignState,
    request: dict[str, Any],
    request_id: str,
    status_key: str,
) -> None:
    if status_key == store.APPLIED:
        if st.button(
            "Open New Version",
            key=f"open_version_{request_id}",
            type="primary",
            use_container_width=False,
        ):
            nav.goto("Approvals")
        return

    if status_key == store.DISMISSED:
        quiet("Nothing was changed. Start again from Creative Review if you want to revisit it.")
        return

    if status_key == store.APPLYING:
        quiet("A new version is being built. This page will show it when it is done.")
        return

    columns = st.columns([1.2, 1, 1, 1], gap="small")
    with columns[0]:
        if status_key == store.FAILED:
            if st.button(
                "Retry",
                key=f"retry_{request_id}",
                type="primary",
                use_container_width=True,
            ):
                result = retry_revision(state.path, request_id)
                _acted(result)
        elif status_key in {store.SELECTED, store.APPROVED_TO_APPLY}:
            if st.button(
                "Apply Revision",
                key=f"apply_row_{request_id}",
                type="primary",
                use_container_width=True,
            ):
                _run_apply(state, request_id)
        else:
            if st.button(
                "Review Options",
                key=f"review_options_{request_id}",
                type="primary",
                use_container_width=True,
            ):
                nav.goto("Review", "Creative Review")
    with columns[1]:
        if st.button(
            "Edit Selection",
            key=f"edit_selection_{request_id}",
            use_container_width=True,
            disabled=not request.get("generated_options"),
        ):
            nav.goto("Review", "Creative Review")
    with columns[2]:
        if request.get("deferred_at"):
            if st.button("Reopen", key=f"resume_{request_id}", use_container_width=True):
                _acted(resume_revision(state.path, request_id))
        else:
            if st.button(
                "Save for Later", key=f"defer_row_{request_id}", use_container_width=True
            ):
                result = defer_revision(state.path, request_id)
                _acted(result)
    with columns[3]:
        if st.button("Dismiss", key=f"dismiss_row_{request_id}", use_container_width=True):
            result = dismiss_revision(state.path, request_id)
            _acted(result)
