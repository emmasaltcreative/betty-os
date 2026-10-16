"""Settings — real settings, plus an honest account of what works."""

from __future__ import annotations

import streamlit as st

from src.common import ASSETS_MEDIA_DIR, LIBRARY_DIR, OUTPUTS_DIR, ROOT
from ui.capability import capability_report, exports_dir
from ui.components import (
    Stat,
    blocked_state,
    key_values,
    note,
    page_header,
    quiet,
    section,
    show_badges,
    stat_strip,
)
from ui.data_access import (
    api_key_configured,
    brand_display_name,
    brand_guide_loaded,
    count_indexed_assets,
    ffmpeg_available,
    friendly_path,
)
from ui.status import Status

APP_VERSION = "0.10 — Studio finishing"

TIER_TITLES = {
    "working": "Working",
    "partial": "Partial",
    "unavailable": "Not Available",
}
TIER_TONES = {"working": "positive", "partial": "attention", "unavailable": "blocked"}


def render() -> None:
    page_header("Settings", "Application configuration for this copy of BettyOS.")

    api_ready = api_key_configured()
    ffmpeg_ready = ffmpeg_available()

    _configuration(api_ready, ffmpeg_ready)
    _active_brand_mark()
    _locations()
    _strategy_planning()
    with st.expander("What BettyOS Can Do", expanded=False):
        quiet("Honest capability status. Technical evidence stays under Diagnostics.")
        _capabilities()
    with st.expander("Diagnostics", expanded=False):
        _advanced(api_ready, ffmpeg_ready)


def _active_brand_mark() -> None:
    from src.common import DEFAULT_BRAND_ID
    from services.active_logo import (
        clear_active_brand_mark,
        evaluate_logo_suitability,
        rasterize_logo_png,
        resolve_active_logo,
        set_active_brand_mark,
    )
    from studio.brand_assets import (
        ROLE_LABELS,
        list_assets,
        resolve_asset_path,
        upload_brand_asset,
    )

    section(
        "Active Brand Mark",
        "Used for new creative, revisions, and campaign documents.",
    )
    mark = resolve_active_logo(DEFAULT_BRAND_ID, bootstrap=True)
    with st.container(border=True):
        if mark is None:
            quiet("No suitable brand mark is active.")
            quiet("Upload a transparent SVG or PNG logo below.")
        else:
            preview = rasterize_logo_png(mark, max_edge=240)
            if preview is not None and preview.is_file():
                st.image(str(preview), width=160)
            elif mark.file_type != "svg":
                st.image(str(mark.absolute_path), width=160)
            else:
                quiet(f"{mark.display_name} (SVG)")
            key_values(
                [
                    ("Display name", mark.display_name),
                    ("Asset ID", mark.asset_id),
                    ("Role", ROLE_LABELS.get(mark.role, mark.role)),
                    (
                        "Suitability",
                        "Passed" if mark.suitable else "Unsuitable",
                    ),
                    ("Selected", mark.selected_at[:19].replace("T", " ") if mark.selected_at else "—"),
                ]
            )
            if mark.validation.reasons:
                for reason in mark.validation.reasons[:2]:
                    quiet(reason)

        c1, c2, c3 = st.columns(3)
        with c1:
            validate = st.button("Validate again", key="set_logo_validate")
        with c2:
            remove = st.button("Remove", key="set_logo_remove")
        with c3:
            pass

        if validate and mark is not None:
            result = evaluate_logo_suitability(mark.absolute_path)
            if result.suitable:
                st.success("; ".join(result.reasons) or "Logo passed suitability.")
            else:
                st.error("; ".join(result.reasons) or "Logo failed suitability.")

        if remove and mark is not None:
            clear_active_brand_mark(DEFAULT_BRAND_ID)
            st.session_state["betty_flash"] = (
                "Active brand mark cleared. New work will not invent a placeholder logo."
            )
            st.rerun()

        st.write("")
        quiet("Replace")
        uploaded = st.file_uploader(
            "Upload a new brand mark",
            type=["png", "jpg", "jpeg", "svg"],
            key="set_active_logo_upload",
        )
        assets = [a for a in list_assets(DEFAULT_BRAND_ID) if not a.archived]
        choices = {f"{a.display_name} ({a.asset_id})": a.asset_id for a in assets}
        selected_label = st.selectbox(
            "Or choose an existing library mark",
            options=[""] + list(choices.keys()),
            key="set_active_logo_pick",
        )
        if st.button("Activate selected mark", type="primary", key="set_logo_activate"):
            import tempfile
            from pathlib import Path

            try:
                if uploaded is not None:
                    suffix = Path(uploaded.name).suffix.lower() or ".png"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(uploaded.getvalue())
                        tmp_path = Path(tmp.name)
                    try:
                        record = upload_brand_asset(
                            tmp_path,
                            brand_id=DEFAULT_BRAND_ID,
                            display_name=Path(uploaded.name).stem,
                            role="emblem",
                            set_as_default=True,
                            original_filename=uploaded.name,
                        )
                        set_active_brand_mark(record.asset_id, brand_id=DEFAULT_BRAND_ID)
                        st.session_state["betty_flash"] = (
                            f"Active brand mark set to {record.display_name}."
                        )
                    finally:
                        tmp_path.unlink(missing_ok=True)
                elif selected_label and selected_label in choices:
                    set_active_brand_mark(choices[selected_label], brand_id=DEFAULT_BRAND_ID)
                    st.session_state["betty_flash"] = "Active brand mark updated."
                else:
                    note("Choose a file or an existing mark first.")
                    return
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(
                    f"{exc} The previous valid logo remains active."
                    if mark is not None
                    else str(exc)
                )


def _strategy_planning() -> None:
    section("Campaign planning defaults", "Advanced. Most campaigns do not need changes here.")
    from src.campaign_intelligence.rules import (
        load_strategy_rules,
        save_strategy_overrides,
    )

    rules = load_strategy_rules()
    with st.expander("Strategy and lead-time rules", expanded=False):
        note(
            "These are planning assumptions stored in production/strategy_rules.json. "
            "They are not performance forecasts."
        )
        film = st.number_input(
            "Default filming availability (minutes)",
            min_value=15,
            max_value=480,
            value=int(rules.get("filming_availability_default_minutes") or 60),
            key="set_film_default",
        )
        approval = st.number_input(
            "Average approval turnaround (days)",
            min_value=0,
            max_value=21,
            value=int(rules.get("average_approval_turnaround_days") or 2),
            key="set_approval",
        )
        editing = st.number_input(
            "Standard editing buffer (minutes)",
            min_value=0,
            max_value=240,
            value=int(rules.get("standard_editing_buffer_minutes") or 25),
            key="set_edit_buffer",
        )
        reshoot = st.number_input(
            "Reshoot buffer (days)",
            min_value=0,
            max_value=21,
            value=int(rules.get("reshoot_buffer_days") or 3),
            key="set_reshoot",
        )
        shipping = st.number_input(
            "Shipping cutoff margin (days)",
            min_value=0,
            max_value=30,
            value=int(rules.get("shipping_cutoff_margin_days") or 7),
            key="set_ship_margin",
        )
        capacity = st.number_input(
            "Production sessions per week",
            min_value=1,
            max_value=14,
            value=int(rules.get("production_capacity_sessions_per_week") or 2),
            key="set_capacity",
        )
        quiet("Brand holiday include/exclude lists live in brands/<id>/calendar_rules.json.")
        if st.button("Save planning defaults", key="set_save_strategy"):
            save_strategy_overrides(
                {
                    "filming_availability_default_minutes": int(film),
                    "average_approval_turnaround_days": int(approval),
                    "standard_editing_buffer_minutes": int(editing),
                    "reshoot_buffer_days": int(reshoot),
                    "shipping_cutoff_margin_days": int(shipping),
                    "production_capacity_sessions_per_week": int(capacity),
                }
            )
            st.session_state["betty_flash"] = "Planning defaults saved."
            st.rerun()


def _configuration(api_ready: bool, ffmpeg_ready: bool) -> None:
    section("Configuration")
    with st.container(border=True):
        key_values(
            [
                ("Active brand", brand_display_name()),
                ("Brand guide", "Loaded" if brand_guide_loaded() else "Not found"),
                ("Writing and review", "Connected" if api_ready else "Not configured"),
                ("Video rendering", "Ready" if ffmpeg_ready else "Not available"),
                ("Indexed media", f"{count_indexed_assets()} files"),
                ("App version", APP_VERSION),
                ("Theme", "Cream and jade (fixed for now)"),
            ]
        )

    if not api_ready:
        blocked_state(
            "Writing and review are unavailable",
            "Add ANTHROPIC_API_KEY to the .env file in the project folder, then restart the app. "
            "Planning, content generation, and Creative Review all need it.",
        )
    if not ffmpeg_ready:
        blocked_state(
            "Video rendering is unavailable",
            "FFmpeg is not installed or not on your PATH. Install it with `brew install ffmpeg`. "
            "Image, carousel, and copy templates still work without it.",
        )


def _locations() -> None:
    section("File locations")
    with st.container(border=True):
        key_values(
            [
                ("Project", friendly_path(ROOT)),
                ("Campaign outputs", friendly_path(OUTPUTS_DIR)),
                ("Source media", friendly_path(ASSETS_MEDIA_DIR)),
                ("Media index", friendly_path(LIBRARY_DIR)),
                ("Export packages", friendly_path(exports_dir())),
            ]
        )
    note("These locations are set by the project layout and cannot be changed here.")


def _capabilities() -> None:
    section(
        "Capability Status",
        "What works today, what only partly works, and what is not built yet.",
    )
    report = capability_report()
    stat_strip(
        [
            Stat("Working", len(report.get("working", [])), "positive"),
            Stat("Partial", len(report.get("partial", [])), "attention"),
            Stat("Not available", len(report.get("unavailable", [])), "blocked"),
        ]
    )

    for tier in ("working", "partial", "unavailable"):
        rows = report.get(tier) or []
        if not rows:
            continue
        with st.expander(
            f"{TIER_TITLES[tier]} ({len(rows)})",
            expanded=tier != "working",
        ):
            for capability in rows:
                with st.container(border=True):
                    show_badges([Status(tier, TIER_TITLES[tier], TIER_TONES[tier])])
                    st.markdown(
                        f'<div class="betty-section" style="font-size:1rem;">'
                        f"{capability.name}</div>",
                        unsafe_allow_html=True,
                    )
                    if capability.summary:
                        quiet(capability.summary)
                    key_values(
                        [
                            ("What works", capability.works),
                            ("What does not", capability.does_not_work),
                            ("Why", capability.reason),
                            ("To make it work", capability.next_step),
                            ("Evidence", capability.evidence),
                        ]
                    )


def _advanced(api_ready: bool, ffmpeg_ready: bool) -> None:
    with st.expander("Advanced (technical detail)", expanded=False):
        note(
            "This section is for troubleshooting. Nothing here needs changing for normal use."
        )
        key_values(
            [
                ("Project root", str(ROOT)),
                ("Outputs directory", str(OUTPUTS_DIR)),
                ("Media directory", str(ASSETS_MEDIA_DIR)),
                ("Media index", str(LIBRARY_DIR / "assets.json")),
                ("Exports directory", str(exports_dir())),
                ("Environment file", str(ROOT / ".env")),
                ("ANTHROPIC_API_KEY", "Present" if api_ready else "Missing"),
                ("ffmpeg on PATH", "Yes" if ffmpeg_ready else "No"),
                ("Template registry", str(ROOT / "templates" / "template_registry.json")),
            ]
        )
        quiet(
            "Campaign data stays on disk as JSON and Markdown under the outputs directory. "
            "The command line tools read and write the same files as this interface."
        )
        from src.platforms import unknown_platform_diagnostics

        unknown = unknown_platform_diagnostics()
        if unknown:
            quiet("Unknown legacy platform labels (excluded from planning widgets):")
            for entry in unknown[-12:]:
                quiet(f"{entry.get('value')} · source {entry.get('source')}")

        quiet("Internal QA / smoke validations")
        from ui.campaign_state import list_campaigns
        from src.asset_visibility import list_internal_asset_folders, read_asset_meta
        from pathlib import Path

        campaigns = list_campaigns()
        shown = 0
        for summary in campaigns[:8]:
            internals = list_internal_asset_folders(summary.path)
            if not internals:
                continue
            quiet(f"{summary.name}:")
            for info in internals[:6]:
                folder = Path(info.folder_path) if info.folder_path else summary.path / info.folder_name
                meta = read_asset_meta(folder) or {}
                note_bits = info.reason
                if meta.get("logo_asset_id"):
                    note_bits = (
                        f"Logo validation · {meta.get('logo_display_name') or meta.get('logo_asset_id')}"
                    )
                quiet(f"· {info.folder_name} ({info.purpose}) — {note_bits}")
                shown += 1
        if not shown:
            quiet("No internal QA assets recorded for recent campaigns.")
