"""Self-contained Pinterest Pin Studio, embedded as an independent BettyOS tool."""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


def render() -> None:
    st.title("Pin Studio")
    st.caption("Oh Betty Jaletti · Create product pins from original website photography")
    template = Path(__file__).resolve().parents[1] / "assets" / "pin_studio.html"
    if not template.is_file():
        st.error("The Pin Studio template is missing from ui/assets.")
        return
    components.html(template.read_text(encoding="utf-8"), height=1130, scrolling=True)
