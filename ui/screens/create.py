"""Create — content, template, and render in one place, one piece at a time."""

from __future__ import annotations

import streamlit as st

from src.templates.registry import list_templates
from ui import nav
from ui.campaign_state import CampaignState, PieceState, count_phrase
from ui.capability import effective_status, renderability, template_note
from ui.components import (
    Stat,
    blocked_state,
    caption_body,
    empty_state,
    file_summary,
    key_values,
    media_preview,
    note,
    page_header,
    progress_rail,
    quiet,
    report,
    saved_note,
    section,
    show_badges,
    stat_strip,
)
from ui.status import content_status, content_status_for_approval, template_status
from ui.workflow_service import (
    copy_fields_for_piece,
    render_piece,
    render_ready_pieces,
    save_piece_template_override,
)

STEPS = ["1. Content", "2. Template", "3. Render"]
STEP_KEY = "create_step"


def render(state: CampaignState) -> None:
    page_header("Create", "Turn each content piece into a finished render.")
    progress_rail(state.steps)

    if not state.exists:
        empty_state("No campaign selected", "Open a campaign before creating renders.")
        if st.button("Go to Campaigns", type="primary"):
            nav.goto("Campaigns")
        return

    if not state.pieces:
        empty_state(
            "No campaign content yet",
            "This campaign has no content pieces. Create a campaign with content to begin.",
        )
        if st.button("Go to Campaigns", type="primary", key="create_to_campaigns"):
            nav.goto("Campaigns")
        return

    step = nav.step_selector("Step", STEPS, key=STEP_KEY)
    st.write("")

    if step == STEPS[0]:
        _step_content(state)
    elif step == STEPS[1]:
        _step_template(state)
    else:
        _step_render(state)


# --- Step 1: Content --------------------------------------------------------

def _step_content(state: CampaignState) -> None:
    counts = state.counts
    stat_strip(
        [
            Stat("Pieces", counts["pieces"]),
            Stat(
                "Ready",
                counts["ready_to_render"],
                "attention" if counts["ready_to_render"] else "neutral",
            ),
            Stat("Rendered", counts["rendered"], "positive" if counts["rendered"] else "neutral"),
            Stat(
                "Missing inputs",
                counts["missing_inputs"],
                "blocked" if counts["missing_inputs"] else "neutral",
            ),
            Stat(
                "Not supported",
                counts["unsupported"],
                "blocked" if counts["unsupported"] else "neutral",
            ),
        ]
    )
    section("Content pieces", "Open a piece to choose its template and create a render.")

    for piece in state.pieces:
        with st.container(border=True):
            columns = st.columns([3, 1], gap="medium", vertical_alignment="center")
            with columns[0]:
                show_badges([content_status(piece.status_key)])
                st.markdown(
                    f'<div class="betty-section">{piece.record.title}</div>',
                    unsafe_allow_html=True,
                )
                key_values(
                    [
                        ("Platform", piece.record.platform or "Not set"),
                        ("Objective", piece.record.objective or "Not set"),
                        ("Template", _template_label(piece)),
                        (
                            "Renders",
                            count_phrase(len(piece.versions), "version")
                            if piece.versions
                            else "None yet",
                        ),
                    ]
                )
                if piece.missing_inputs:
                    quiet(piece.missing_inputs[0])
                elif not piece.can_render:
                    quiet(piece.blocked_reason)
            with columns[1]:
                if st.button(
                    "Open",
                    key=f"open_piece_{piece.record.piece_id}",
                    type="primary",
                    use_container_width=True,
                ):
                    nav.select_piece(piece.record.piece_id)
                    nav.request_step(STEPS[1])


# --- Piece selection --------------------------------------------------------

def _template_label(piece: PieceState) -> str:
    """Template name plus what it can really do, in one line."""
    status = template_status(piece.template_status)
    if status.key == "ready":
        return piece.template_name
    return f"{piece.template_name} — {status.label}"


def _current_piece(state: CampaignState) -> PieceState | None:
    piece_id = nav.selected_piece_id()
    for piece in state.pieces:
        if piece.record.piece_id == piece_id:
            return piece
    return None


def _piece_switcher(state: CampaignState, piece: PieceState, *, key: str) -> PieceState:
    titles = {p.record.title: p for p in state.pieces}
    chosen = st.selectbox(
        "Content piece",
        options=list(titles.keys()),
        index=list(titles.keys()).index(piece.record.title),
        key=key,
    )
    selected = titles[chosen]
    if selected.record.piece_id != piece.record.piece_id:
        nav.select_piece(selected.record.piece_id)
        st.rerun()
    return selected


def _require_piece(state: CampaignState, *, key: str) -> PieceState | None:
    piece = _current_piece(state)
    if piece is None:
        empty_state(
            "No content piece open",
            "Choose a piece in step 1, or pick one below.",
        )
        titles = {p.record.title: p for p in state.pieces}
        chosen = st.selectbox("Content piece", options=list(titles.keys()), key=key)
        if st.button("Open this piece", type="primary", key=f"{key}_open"):
            nav.select_piece(titles[chosen].record.piece_id)
            st.rerun()
        return None
    return _piece_switcher(state, piece, key=key)


# --- Step 2: Template -------------------------------------------------------

def _template_options() -> tuple[list[str], dict[str, str]]:
    labels: dict[str, str] = {}
    ids: list[str] = []
    for template in list_templates():
        honest = effective_status(template.template_id, template.renderer_status)
        labels[template.template_id] = (
            f"{template.display_name} — {template_status(honest).label}"
        )
        ids.append(template.template_id)
    return ids, labels


def _step_template(state: CampaignState) -> None:
    piece = _require_piece(state, key="template_piece_select")
    if piece is None:
        return

    left, right = st.columns([1, 1], gap="large")

    with left:
        section("This content piece")
        with st.container(border=True):
            show_badges([content_status(piece.status_key)])
            key_values(
                [
                    ("Title", piece.record.title),
                    ("Platform", piece.record.platform or "Not set"),
                    ("Objective", piece.record.objective or "Not set"),
                    ("Suggested format", piece.record.format or "Not set"),
                ]
            )
        _source_assets(piece)

    with right:
        section("Template", "One template per content piece. Your choice is remembered.")
        ids, labels = _template_options()
        current = piece.template_id if piece.template_id in ids else ids[0]
        chosen = st.selectbox(
            "Template",
            options=ids,
            index=ids.index(current),
            format_func=lambda tid: labels.get(tid, tid),
            key=f"template_choice_{piece.record.piece_id}",
        )
        _template_detail(chosen)

        if st.button(
            "Save template",
            type="primary",
            key=f"save_template_{piece.record.piece_id}",
            disabled=chosen == piece.template_id or state.package_path is None,
            help="Already saved." if chosen == piece.template_id else None,
        ):
            with st.spinner("Saving…"):
                result = save_piece_template_override(
                    state.package_path,
                    piece_id=piece.record.piece_id,
                    template_id=chosen,
                )
            report(result)
            if result.ok:
                st.rerun()

        if chosen == piece.template_id:
            saved_note("Template choice is saved to disk.")

        if st.button("Continue to Render", key=f"to_render_{piece.record.piece_id}"):
            nav.request_step(STEPS[2])

        note("Browse every template under Library › Templates.")


def _template_detail(template_id: str) -> None:
    template = next((t for t in list_templates() if t.template_id == template_id), None)
    if template is None:
        return
    honest = effective_status(template_id, template.renderer_status)
    check = renderability(template_id, template.renderer_status, template.renderer_module)
    with st.container(border=True):
        show_badges([template_status(honest)])
        quiet(template.description)
        key_values(
            [
                ("Needs", ", ".join(template.required_inputs) or "Nothing"),
                ("Produces", ", ".join(template.output_types).upper() or "—"),
                ("Sizes", ", ".join(template.supported_aspect_ratios) or "—"),
            ]
        )
        caveat = template_note(template_id)
        if not check.can_render:
            blocked_state("This template cannot render", check.reason)
        elif caveat:
            note(f"What it actually does: {caveat}")


def _source_assets(piece: PieceState) -> None:
    section("Source media")
    if not piece.record.source_assets:
        blocked_state("No source media", "This piece has no media attached, so it cannot render.")
        return
    from renderers.primitives import resolve_media_path

    rows: list[tuple[str, object]] = []
    for relative in piece.record.source_assets:
        path = resolve_media_path(relative)
        rows.append((path.name, "Found" if path.exists() else "Missing from disk"))
    with st.container(border=True):
        key_values(rows)


# --- Step 3: Render ---------------------------------------------------------

def _step_render(state: CampaignState) -> None:
    piece = _require_piece(state, key="render_piece_select")
    if piece is None:
        _batch_render(state)
        return

    left, right = st.columns([1, 1], gap="large")

    with left:
        section("What will be rendered")
        with st.container(border=True):
            show_badges([content_status(piece.status_key)])
            key_values(
                [
                    ("Content piece", piece.record.title),
                    ("Template", _template_label(piece)),
                    ("Platform", piece.record.platform or "Not set"),
                    (
                        "Required inputs",
                        ", ".join(piece.template.required_inputs) if piece.template else "—",
                    ),
                ]
            )
        _source_assets(piece)

    with right:
        _render_controls(state, piece)

    st.write("")
    _render_history(piece)
    st.write("")
    _batch_render(state)


def _render_controls(state: CampaignState, piece: PieceState) -> None:
    section("Create a render")

    if not piece.can_render:
        blocked_state("Rendering is not available", piece.blocked_reason)
        note("Choose a different template in step 2 to render this piece.")
        return
    if piece.missing_inputs:
        blocked_state("Missing inputs", piece.missing_inputs[0])
        return

    is_video = piece.template is not None and piece.template.renderer_module == "video"
    duration = None
    cta_at = None

    with st.container(border=True):
        if is_video:
            duration = st.slider(
                "Length (seconds)",
                min_value=8,
                max_value=30,
                value=15,
                key=f"duration_{piece.record.piece_id}",
            )
            cta_at = st.slider(
                "Call to action appears at (seconds)",
                min_value=2,
                max_value=int(duration),
                value=min(10, int(duration)),
                key=f"cta_{piece.record.piece_id}",
            )
        else:
            quiet("This template has no options to set. Copy comes from the content piece.")

        caveat = template_note(piece.template_id)
        if caveat:
            note(f"What this produces: {caveat}")

        if st.button(
            "Create render",
            type="primary",
            key=f"render_{piece.record.piece_id}",
            use_container_width=True,
        ):
            with st.status("Rendering…", expanded=True) as status:
                result = render_piece(
                    template_id=piece.template_id,
                    content_piece_id=piece.record.piece_id,
                    source_assets=piece.record.source_assets,
                    campaign_dir=state.path,
                    copy_fields=copy_fields_for_piece(piece.record),
                    title=piece.record.title,
                    duration_seconds=float(duration) if duration else None,
                    cta_appear_at_seconds=float(cta_at) if cta_at else None,
                )
                report(result)
                status.update(
                    label=result.message,
                    state="complete" if result.ok else "error",
                )
            if result.ok:
                st.rerun()


def _render_history(piece: PieceState) -> None:
    section("Render history")
    if not piece.versions:
        empty_state(
            "No renders yet",
            "Create this piece's first render using the button above.",
        )
        return

    for version in piece.versions:
        with st.expander(
            f"{version.display_name} · version {version.version}",
            expanded=version.is_latest,
        ):
            show_badges([content_status_for_approval(version.approval_status)])
            key_values(
                [
                    ("Created", _readable(version.created_at)),
                    ("Files", file_summary(version)),
                    ("Decision note", version.approval_note or "None"),
                ]
            )
            media_preview(version)
            if version.caption and version.kind != "copy":
                note("Caption")
                caption_body(version.caption)
            if version.kind in {"image", "video"}:
                if st.button(
                    "Open in Studio",
                    key=f"open_studio_{version.key}",
                    use_container_width=True,
                ):
                    st.session_state["studio_pending_version_key"] = version.key
                    nav.goto("Studio")
            quiet("Approve or reject this version under Approvals.")


def _readable(iso: str) -> str:
    from ui.capability import parse_iso

    moment = parse_iso(iso)
    return moment.strftime("%-d %b %Y, %H:%M") if moment else "—"


def _batch_render(state: CampaignState) -> None:
    ready = [p for p in state.pieces if p.status_key == "ready_to_render"]
    section("Render everything that is ready")
    if not ready:
        quiet("No content piece is currently ready to render.")
        return
    with st.container(border=True):
        quiet(
            f"{count_phrase(len(ready), 'piece')} ready: "
            + ", ".join(p.record.title for p in ready[:4])
            + ("…" if len(ready) > 4 else "")
        )
        if st.button("Render all ready pieces", key="render_all_ready"):
            with st.status(f"Rendering {len(ready)} pieces…", expanded=True) as status:
                result = render_ready_pieces(state.path, ready)
                report(result)
                if result.detail:
                    for line in str(result.detail).splitlines():
                        quiet(line)
                status.update(
                    label=result.message,
                    state="complete" if result.ok else "error",
                )
            if result.ok:
                st.rerun()
