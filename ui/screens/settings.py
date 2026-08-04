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
    _locations()
    with st.expander("What BettyOS Can Do", expanded=False):
        quiet("Honest capability status. Technical evidence stays under Diagnostics.")
        _capabilities()
    with st.expander("Diagnostics", expanded=False):
        _advanced(api_ready, ffmpeg_ready)


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
