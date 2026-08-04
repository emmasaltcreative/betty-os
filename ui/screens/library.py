"""Library — reference material: source media, templates, brand, production rules."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile

import streamlit as st

from src.common import DEFAULT_BRAND_ID
from src.templates.registry import list_templates
from studio.brand_assets import (
    ROLE_LABELS,
    archive_asset,
    assign_role,
    edit_usage_rules,
    jpg_transparency_note,
    list_assets,
    rename_asset,
    resolve_asset_path,
    restore_asset,
    set_as_default,
    upload_brand_asset,
)
from studio.capabilities import record_success
from studio.guardrails import ensure_guardrails, list_guardrails
from studio.luts import (
    archive_lut,
    list_luts,
    rename_lut,
    restore_lut,
    set_default_intensity,
    upload_lut,
    validate_lut_record,
)
from ui.capability import effective_status, renderability, template_note
from ui import nav
from ui.components import (
    Stat,
    blocked_state,
    empty_state,
    key_values,
    note,
    page_header,
    quiet,
    report,
    section,
    show_badges,
    stat_strip,
)
from ui.data_access import (
    count_indexed_assets,
    load_asset_summaries,
    load_brand_documents,
    production_rules,
    production_style_guide,
)
from ui.status import Status, TEMPLATE_STATUSES, template_status
from ui.workflow_service import register_planned_template

CATEGORY_LABELS = (
    ("video", "Video"),
    ("static", "Static"),
    ("multi_frame", "Multi-Frame"),
    ("commercial", "Commercial"),
    ("copy", "Copy"),
)


def render() -> None:
    page_header("Library", "Reference material, brand setup, and production guidance.")

    # Resume banner when returning from an interrupted workflow.
    interrupted = st.session_state.get(nav.INTERRUPTED_FLOW)
    if isinstance(interrupted, dict) and interrupted.get("return_to") == "workspace":
        with st.container(border=True):
            quiet("You were in the middle of creating. Return when the brand asset is ready.")
            if st.button("Resume campaign", type="primary", key="lib_resume"):
                nav.goto_workspace(
                    interrupted.get("stage") or "create",
                    piece_id=interrupted.get("piece_id"),
                    version_key=interrupted.get("version_key"),
                )

    assets_tab, brand_setup_tab, templates_tab, brand_tab, rules_tab = st.tabs(
        ["Assets", "Brand Setup", "Templates", "Brand Guide", "Production Rules"]
    )
    with assets_tab:
        _assets()
    with brand_setup_tab:
        _brand_setup()
    with templates_tab:
        _templates()
    with brand_tab:
        _brand()
    with rules_tab:
        _rules()


def _brand_setup() -> None:
    """Completeness checklist + brand mark upload (formerly Brand Assets + LUTs)."""
    from studio.brand_assets import ROLE_LABELS, list_assets

    section("Brand Setup", "What BettyOS needs to finish work with confidence.")
    assets = list_assets(DEFAULT_BRAND_ID, include_archived=False)
    by_role = {a.role: a for a in assets if getattr(a, "role", None)}

    checklist = [
        ("Brand Guide", _brand_guide_ready(), False),
        ("Production Rules", _rules_ready(), False),
        ("Primary Logo", "primary" in by_role or "wordmark" in by_role, False),
        ("Secondary Logo or Wordmark", "secondary" in by_role or "wordmark" in by_role, True),
        ("Light Logo", "light" in by_role, True),
        ("Dark Logo", "dark" in by_role, True),
        ("Optional Emblem or Monogram", "emblem" in by_role or "monogram" in by_role, True),
    ]
    rows = []
    for label, ready, optional in checklist:
        if ready:
            status = "Ready"
        elif optional:
            status = "Optional"
        else:
            status = "Missing"
        rows.append((label, status))
    key_values(rows)

    st.write("")
    _brand_assets()

    with st.expander("Color treatments (LUTs)", expanded=False):
        quiet("Optional. BettyOS manages finishing automatically; LUTs are for advanced brand setup.")
        _luts()

    with st.expander("Advanced Brand Asset Rules", expanded=False):
        quiet("Placement opacity, size, and safe-margin rules. Not required for initial setup.")


# --- Assets -----------------------------------------------------------------

def _assets() -> None:
    summaries = load_asset_summaries()
    if not summaries:
        empty_state(
            "No media indexed yet",
            "Add a media folder when you create a campaign, and BettyOS will index it here.",
        )
        return

    types = sorted({a.asset_type for a in summaries})
    missing = [a for a in summaries if not a.exists]
    stat_strip(
        [
            Stat("Indexed", count_indexed_assets()),
            Stat("Types", len(types)),
            Stat("Missing from disk", len(missing), "blocked" if missing else "neutral"),
        ]
    )

    columns = st.columns([2, 1], gap="medium")
    with columns[0]:
        query = st.text_input(
            "Search",
            key="asset_search",
            placeholder="Search by filename, product, or what is in the shot",
        )
    with columns[1]:
        kind = st.selectbox("Type", options=["All", *types], key="asset_type_filter")

    needle = query.strip().lower()
    filtered = [
        asset
        for asset in summaries
        if (kind == "All" or asset.asset_type == kind)
        and (
            not needle
            or needle in asset.filename.lower()
            or needle in asset.summary.lower()
            or any(needle in p.lower() for p in asset.products)
            or any(needle in o.lower() for o in asset.objects)
        )
    ]

    if not filtered:
        empty_state("Nothing matches that search", "Try a shorter search, or clear the type filter.")
        return

    quiet(f"Showing {len(filtered)} of {len(summaries)} files.")
    for row_start in range(0, len(filtered), 3):
        row = filtered[row_start : row_start + 3]
        grid = st.columns(3, gap="medium")
        for column, asset in zip(grid, row):
            with column, st.container(border=True):
                if asset.thumbnail and asset.thumbnail.is_file():
                    st.image(str(asset.thumbnail), use_container_width=True)
                elif not asset.exists:
                    blocked_state("File missing", "Indexed, but no longer on disk.")
                st.markdown(
                    f'<div class="betty-section" style="font-size:0.98rem;">{asset.filename}</div>',
                    unsafe_allow_html=True,
                )
                quiet(asset.asset_type.replace("_", " ").title())
                if asset.summary:
                    note(asset.summary[:160])
                if asset.products:
                    quiet("Products: " + ", ".join(asset.products[:3]))


# --- Templates --------------------------------------------------------------

def _templates() -> None:
    templates = list_templates()
    if not templates:
        empty_state("No templates defined", "The template registry is empty.")
        return

    honest = {t.template_id: effective_status(t.template_id, t.renderer_status) for t in templates}
    tally = {status.key: 0 for status in TEMPLATE_STATUSES}
    for value in honest.values():
        tally[value] = tally.get(value, 0) + 1

    stat_strip(
        [
            Stat("Ready", tally.get("ready", 0), "positive"),
            Stat("Partial", tally.get("partial", 0), "attention"),
            Stat("Planned", tally.get("planned", 0)),
            Stat("Manual only", tally.get("manual_only", 0)),
        ]
    )
    note(
        "Statuses here describe what the renderer actually produces today, not what the "
        "template describes."
    )

    status_filter = st.multiselect(
        "Show",
        options=[s.label for s in TEMPLATE_STATUSES],
        default=[s.label for s in TEMPLATE_STATUSES],
        key="template_status_filter",
    )
    allowed = {s.key for s in TEMPLATE_STATUSES if s.label in status_filter}

    for category, label in CATEGORY_LABELS:
        bucket = [
            t for t in templates if t.category == category and honest[t.template_id] in allowed
        ]
        if not bucket:
            continue
        section(label)
        for template in bucket:
            status = template_status(honest[template.template_id])
            check = renderability(
                template.template_id, template.renderer_status, template.renderer_module
            )
            with st.expander(f"{template.display_name} — {status.label}", expanded=False):
                show_badges([status])
                quiet(template.description)
                key_values(
                    [
                        ("Platforms", ", ".join(template.supported_platforms) or "—"),
                        ("Sizes", ", ".join(template.supported_aspect_ratios) or "—"),
                        ("Needs", ", ".join(template.required_inputs) or "Nothing"),
                        ("Produces", ", ".join(template.output_types).upper() or "—"),
                    ]
                )
                caveat = template_note(template.template_id)
                if not check.can_render:
                    blocked_state("Cannot render", check.reason)
                elif caveat:
                    note(f"What it actually does: {caveat}")
                else:
                    note(status.meaning)

    _planned_definition()


def _planned_definition() -> None:
    with st.expander("Define a planned template (advanced)", expanded=False):
        note(
            "This records a template description only. BettyOS cannot write renderer code, so "
            "the definition is saved as Planned and cannot produce output until a developer "
            "implements it."
        )
        with st.form("planned_template_form"):
            name = st.text_input("Name", placeholder="Rainy Afternoon Invitation")
            template_id = st.text_input("Identifier (lower_snake_case)")
            category = st.selectbox(
                "Category", options=[key for key, _ in CATEGORY_LABELS]
            )
            family = st.selectbox(
                "Renderer family",
                options=["VideoRenderer", "StaticRenderer", "CarouselRenderer", "CopyRenderer"],
            )
            platforms = st.multiselect(
                "Platforms",
                options=["instagram", "pinterest", "email", "website", "stories"],
                default=["instagram"],
            )
            aspect = st.selectbox("Size", options=["9:16", "4:5", "2:3", "1:1", "16:9"])
            required = st.text_input("Required inputs", value="source_assets, headline")
            outputs = st.text_input("Produces", value="png, caption")
            description = st.text_area("What it is for")
            submitted = st.form_submit_button("Save as Planned")

        if not submitted:
            return

        identifier = (template_id or "").strip()
        if not identifier or " " in identifier or identifier != identifier.lower():
            st.error("The identifier must be lower_snake_case with no spaces.")
            return

        module = {
            "VideoRenderer": "video",
            "StaticRenderer": "static",
            "CarouselRenderer": "carousel",
            "CopyRenderer": "copy",
        }[family]
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        result = register_planned_template(
            {
                "template_id": identifier,
                "display_name": name.strip() or identifier.replace("_", " ").title(),
                "description": description.strip() or "Planned template definition.",
                "category": category,
                "supported_platforms": platforms,
                "supported_aspect_ratios": [aspect],
                "required_inputs": [x.strip() for x in required.split(",") if x.strip()],
                "optional_inputs": [],
                "output_types": [x.strip() for x in outputs.split(",") if x.strip()],
                "renderer_module": module,
                "renderer_family": family,
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
        report(result)


# --- Brand guide ------------------------------------------------------------

def _brand_guide_ready() -> bool:
    documents = load_brand_documents()
    return any(
        text.strip() and text.strip() != "_Not written yet._"
        for text in documents.values()
    )


def _rules_ready() -> bool:
    return bool(production_rules())


def _brand() -> None:
    documents = load_brand_documents()
    written = {
        label: text
        for label, text in documents.items()
        if text.strip() and text.strip() != "_Not written yet._"
    }
    if not written:
        empty_state(
            "No brand guide yet",
            "Brand documents live in the brands folder. None have been written.",
        )
        return

    quiet("The voice, world, and visual language BettyOS writes and renders from.")
    for label, text in documents.items():
        with st.expander(label, expanded=False):
            if label not in written:
                quiet("Not written yet.")
            else:
                st.markdown(text)


# --- Production rules -------------------------------------------------------

def _rules() -> None:
    groups = production_rules()
    if not groups:
        empty_state(
            "No production rules found",
            "Production standards live in the production folder. None were found.",
        )
        return

    quiet("The output standards every render follows.")
    for title, rows in groups:
        section(title)
        with st.container(border=True):
            key_values(rows)

    guide = production_style_guide()
    if guide:
        with st.expander("Full written style guide", expanded=False):
            st.markdown(guide)

    ensure_guardrails(DEFAULT_BRAND_ID)
    section("Oh Betty Jaletti product guardrails")
    quiet("Not Automatically Verified — preserved for review and future semantic validation.")
    for rule in list_guardrails(DEFAULT_BRAND_ID):
        st.markdown(f"- {rule}")


# --- Brand assets -----------------------------------------------------------

def _brand_assets() -> None:
    section("Brand Assets", "Persistent logos and marks for Studio placement.")
    uploaded = st.file_uploader(
        "Upload Brand Asset",
        type=["png", "jpg", "jpeg", "svg"],
        key="brand_asset_upload",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        display_name = st.text_input("Display name", key="ba_name")
    with col2:
        role = st.selectbox(
            "Role",
            list(ROLE_LABELS.keys()),
            format_func=lambda r: ROLE_LABELS[r],
            key="ba_role",
        )
    with col3:
        as_default = st.checkbox("Set as Default", value=True, key="ba_default")

    if uploaded is not None and st.button("Save Brand Asset", type="primary", key="ba_save"):
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = Path(tmp.name)
        try:
            note_msg = jpg_transparency_note(tmp_path)
            if note_msg:
                st.info(note_msg)
            record = upload_brand_asset(
                tmp_path,
                brand_id=DEFAULT_BRAND_ID,
                display_name=display_name or Path(uploaded.name).stem,
                role=role,
                set_as_default=as_default,
                original_filename=uploaded.name,
            )
            record_success("Brand Asset Upload", record.asset_id, DEFAULT_BRAND_ID)
            if suffix == ".svg":
                record_success("SVG Logo Preview", record.asset_id, DEFAULT_BRAND_ID)
            st.success(f"Saved {record.display_name}")
            interrupted = st.session_state.get(nav.INTERRUPTED_FLOW)
            if isinstance(interrupted, dict) and interrupted.get("return_to") == "workspace":
                nav.goto_workspace(
                    interrupted.get("stage") or "create",
                    piece_id=interrupted.get("piece_id"),
                    version_key=interrupted.get("version_key"),
                )
            else:
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
        finally:
            tmp_path.unlink(missing_ok=True)

    assets = list_assets(DEFAULT_BRAND_ID, include_archived=True)
    if not assets:
        empty_state(
            "No brand assets yet",
            "Upload a primary logo (SVG or transparent PNG preferred) to use in Studio.",
        )
        return

    for asset in assets:
        with st.container(border=True):
            show_badges(
                [
                    Status("role", ROLE_LABELS.get(asset.role, asset.role), "neutral"),
                    Status(
                        "state",
                        "Archived" if asset.archived else ("Default" if asset.is_default_for_role else "Active"),
                        "blocked" if asset.archived else "positive",
                    ),
                ]
            )
            st.markdown(f"**{asset.display_name}**")
            path = resolve_asset_path(asset)
            if path.is_file() and path.suffix.lower() != ".svg":
                st.image(str(path), width=160)
            elif path.is_file() and path.suffix.lower() == ".svg":
                quiet("SVG stored. Preview uses rasterization when available.")
                try:
                    from studio.image_pipeline import rasterize_logo

                    preview = rasterize_logo(path)
                    st.image(preview, width=160)
                except Exception as exc:  # noqa: BLE001
                    quiet(f"SVG preview unavailable: {exc}")
            key_values(
                [
                    ("Role", ROLE_LABELS.get(asset.role, asset.role)),
                    ("Size", f"{asset.width or '—'}×{asset.height or '—'}"),
                    ("Transparency", "Yes" if asset.has_transparency else "No"),
                    ("Original file", asset.original_filename),
                ]
            )
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                new_name = st.text_input("Rename", value=asset.display_name, key=f"ba_rn_{asset.asset_id}")
                if st.button("Rename", key=f"ba_rn_btn_{asset.asset_id}"):
                    rename_asset(asset.asset_id, new_name, DEFAULT_BRAND_ID)
                    st.rerun()
            with c2:
                new_role = st.selectbox(
                    "Assign Role",
                    list(ROLE_LABELS.keys()),
                    index=list(ROLE_LABELS.keys()).index(asset.role) if asset.role in ROLE_LABELS else 0,
                    format_func=lambda r: ROLE_LABELS[r],
                    key=f"ba_ar_{asset.asset_id}",
                )
                if st.button("Assign Role", key=f"ba_ar_btn_{asset.asset_id}"):
                    assign_role(asset.asset_id, new_role, DEFAULT_BRAND_ID)
                    st.rerun()
            with c3:
                if st.button("Set as Default", key=f"ba_def_{asset.asset_id}"):
                    set_as_default(asset.asset_id, DEFAULT_BRAND_ID)
                    st.rerun()
            with c4:
                if asset.archived:
                    if st.button("Restore", key=f"ba_res_{asset.asset_id}"):
                        restore_asset(asset.asset_id, DEFAULT_BRAND_ID)
                        st.rerun()
                else:
                    if st.button("Archive", key=f"ba_arc_{asset.asset_id}"):
                        archive_asset(asset.asset_id, DEFAULT_BRAND_ID)
                        st.rerun()
            with st.expander("Edit Usage Rules", expanded=False):
                min_w = st.number_input("Minimum display width", value=int(asset.minimum_display_width), key=f"ba_min_{asset.asset_id}")
                opacity = st.slider("Default opacity", 0.1, 1.0, float(asset.default_opacity), key=f"ba_op_{asset.asset_id}")
                size_pct = st.slider("Default size %", 5.0, 60.0, float(asset.default_size_percentage), key=f"ba_sz_{asset.asset_id}")
                margin = st.number_input("Default safe margin", value=float(asset.default_safe_margin), key=f"ba_mg_{asset.asset_id}")
                if st.button("Save usage rules", key=f"ba_rules_{asset.asset_id}"):
                    edit_usage_rules(
                        asset.asset_id,
                        DEFAULT_BRAND_ID,
                        minimum_display_width=int(min_w),
                        default_opacity=float(opacity),
                        default_size_percentage=float(size_pct),
                        default_safe_margin=float(margin),
                    )
                    st.rerun()


# --- LUTs -------------------------------------------------------------------

def _luts() -> None:
    section("LUTs", "Real .cube lookup tables only — not Color Recipes.")
    uploaded = st.file_uploader("Upload LUT", type=["cube"], key="lut_upload")
    name = st.text_input("Display name", key="lut_name")
    intensity = st.slider("Default intensity", 0.0, 1.0, 1.0, key="lut_intensity")
    if uploaded is not None and st.button("Save LUT", type="primary", key="lut_save"):
        with tempfile.NamedTemporaryFile(suffix=".cube", delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = Path(tmp.name)
        try:
            record = upload_lut(
                tmp_path,
                brand_id=DEFAULT_BRAND_ID,
                display_name=name or Path(uploaded.name).stem,
                default_intensity=float(intensity),
            )
            if record.status == "Ready":
                st.success(f"LUT Ready — {record.display_name} ({record.cube_size}³)")
            else:
                st.error(f"{record.status}: {record.validation_notes}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
        finally:
            tmp_path.unlink(missing_ok=True)

    records = list_luts(DEFAULT_BRAND_ID, include_archived=True)
    if not records:
        empty_state("No LUTs yet", "Upload a valid .cube file to use in Studio.")
        return

    for record in records:
        with st.container(border=True):
            show_badges(
                [
                    Status(
                        "lut",
                        record.status,
                        "positive" if record.status == "Ready" else "blocked",
                    )
                ]
            )
            st.markdown(f"**{record.display_name}**")
            key_values(
                [
                    ("Original file", record.original_filename),
                    ("Cube size", str(record.cube_size or "—")),
                    ("Domain", f"{record.domain_min} → {record.domain_max}"),
                    ("Default intensity", str(record.default_intensity)),
                    ("Notes", record.validation_notes or "—"),
                ]
            )
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                new_name = st.text_input("Rename", value=record.display_name, key=f"lut_rn_{record.lut_id}")
                if st.button("Rename", key=f"lut_rn_btn_{record.lut_id}"):
                    rename_lut(record.lut_id, new_name, DEFAULT_BRAND_ID)
                    st.rerun()
            with c2:
                if st.button("Validate", key=f"lut_val_{record.lut_id}"):
                    validate_lut_record(record.lut_id, DEFAULT_BRAND_ID)
                    st.rerun()
            with c3:
                inten = st.slider(
                    "Set Default Intensity",
                    0.0,
                    1.0,
                    float(record.default_intensity),
                    key=f"lut_di_{record.lut_id}",
                )
                if st.button("Save intensity", key=f"lut_di_btn_{record.lut_id}"):
                    set_default_intensity(record.lut_id, inten, DEFAULT_BRAND_ID)
                    st.rerun()
            with c4:
                if record.status == "Archived":
                    if st.button("Restore", key=f"lut_res_{record.lut_id}"):
                        restore_lut(record.lut_id, DEFAULT_BRAND_ID)
                        st.rerun()
                else:
                    if st.button("Archive", key=f"lut_arc_{record.lut_id}"):
                        archive_lut(record.lut_id, DEFAULT_BRAND_ID)
                        st.rerun()

