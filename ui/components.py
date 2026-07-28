"""Shared visual language for BettyOS.

One theme, one card, one button treatment, one badge, and one set of empty /
loading / error / blocked states. Pages compose these rather than styling
themselves, so the same state always looks the same.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import streamlit as st

from ui.status import Status

THEME = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Source+Sans+3:wght@400;500;600&display=swap');

:root {
  --cream: #faf7f1;
  --cream-deep: #f4efe5;
  --surface: #ffffff;
  --ink: #23211e;
  --muted: #6f6a61;
  --line: #e6dfd2;
  --jade: #2f6f5e;
  --jade-deep: #245a4c;
  --jade-soft: #e8f1ed;
  --radius: 10px;
}

html, body, [data-testid="stAppViewContainer"] {
  background: var(--cream);
  color: var(--ink);
  font-family: "Source Sans 3", -apple-system, "Segoe UI", sans-serif;
}

[data-testid="stAppViewContainer"] .block-container {
  padding-top: 2.4rem;
  padding-bottom: 4rem;
  max-width: 1180px;
}

h1, h2, h3, h4, .betty-serif {
  font-family: "Source Serif 4", Georgia, serif !important;
  color: var(--ink) !important;
  letter-spacing: -0.005em;
  font-weight: 600 !important;
}

/* Page title */
.betty-title {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.85rem;
  line-height: 1.2;
  margin: 0 0 0.2rem;
  font-weight: 600;
}
.betty-subtitle {
  color: var(--muted);
  font-size: 0.95rem;
  margin: 0 0 1.4rem;
  max-width: 62ch;
}

/* Section heading */
.betty-section {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.15rem;
  font-weight: 600;
  margin: 0.4rem 0 0.15rem;
}
.betty-section-note {
  color: var(--muted);
  font-size: 0.875rem;
  margin: 0 0 0.7rem;
  max-width: 68ch;
}

/* Sidebar */
[data-testid="stSidebar"] {
  background: var(--cream-deep);
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
.betty-brand {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.3rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin: 0;
}
.betty-brand-note {
  color: var(--muted);
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin: 0 0 1rem;
}

/* Sidebar navigation radio reads as a nav list */
[data-testid="stSidebar"] [role="radiogroup"] { gap: 0.05rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  padding: 0.34rem 0.5rem;
  border-radius: 8px;
  width: 100%;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(47,111,94,0.07); }
[data-testid="stSidebar"] [role="radiogroup"] label p {
  font-size: 0.95rem !important;
  font-weight: 500;
}

/* Cards — native bordered containers */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--surface);
  border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important;
}

/* Buttons */
.stButton > button, .stDownloadButton > button {
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.92rem;
  padding: 0.42rem 1rem;
  transition: background 120ms ease, border-color 120ms ease;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: var(--jade);
  border: 1px solid var(--jade);
  color: #fff;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
  background: var(--jade-deep);
  border-color: var(--jade-deep);
}
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--ink);
}
.stButton > button[kind="secondary"]:hover {
  border-color: var(--jade);
  color: var(--jade);
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
  background: var(--cream-deep) !important;
  border-color: var(--line) !important;
  color: #a49d92 !important;
  cursor: not-allowed;
}

/* Badges */
.betty-badge {
  display: inline-block;
  border-radius: 999px;
  padding: 0.13rem 0.6rem;
  font-size: 0.76rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
  border: 1px solid transparent;
}
.betty-badge.neutral   { background: #f1ece2; color: #6f6a61; border-color: #e6dfd2; }
.betty-badge.active    { background: #e7eff3; color: #2b5a6b; border-color: #d3e3ea; }
.betty-badge.positive  { background: #e8f1ed; color: #235c4c; border-color: #cfe4db; }
.betty-badge.attention { background: #fbf1de; color: #8a5f1e; border-color: #f0ddba; }
.betty-badge.blocked   { background: #f9e9e5; color: #8d3b2f; border-color: #eed3cc; }
.betty-badge-row { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }

/* Progress rail */
.betty-rail {
  display: flex;
  align-items: stretch;
  gap: 0;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: var(--radius);
  padding: 0.55rem 0.3rem;
  margin-bottom: 1.3rem;
  overflow-x: auto;
}
.betty-rail-step {
  flex: 1 1 0;
  min-width: 80px;
  text-align: center;
  padding: 0.1rem 0.4rem;
  border-left: 1px solid var(--line);
}
.betty-rail-step:first-child { border-left: none; }
.betty-rail-dot {
  width: 9px; height: 9px;
  border-radius: 50%;
  margin: 0 auto 0.32rem;
  background: #ded6c8;
}
.betty-rail-label {
  font-size: 0.8rem;
  color: var(--muted);
  font-weight: 500;
}
.betty-rail-state {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #a49d92;
  margin-top: 0.1rem;
}
.betty-rail-step.complete .betty-rail-dot { background: var(--jade); }
.betty-rail-step.complete .betty-rail-label { color: var(--jade); }
.betty-rail-step.current .betty-rail-dot {
  background: var(--surface);
  border: 3px solid var(--jade);
  width: 11px; height: 11px;
}
.betty-rail-step.current .betty-rail-label { color: var(--ink); font-weight: 600; }
.betty-rail-step.current .betty-rail-state { color: var(--jade); }
.betty-rail-step.blocked .betty-rail-dot { background: #c0563f; }
.betty-rail-step.blocked .betty-rail-label { color: #8d3b2f; font-weight: 600; }
.betty-rail-step.blocked .betty-rail-state { color: #8d3b2f; }

/* Stat strip */
.betty-stats {
  display: flex;
  flex-wrap: wrap;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 1.2rem;
}
.betty-stat {
  flex: 1 1 130px;
  padding: 0.75rem 1rem;
  border-left: 1px solid var(--line);
}
.betty-stat:first-child { border-left: none; }
.betty-stat-label {
  font-size: 0.76rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 0.2rem;
}
.betty-stat-value {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.5rem;
  font-weight: 600;
  line-height: 1.1;
}
.betty-stat.attention .betty-stat-value { color: #8a5f1e; }
.betty-stat.positive .betty-stat-value { color: var(--jade); }
.betty-stat.blocked .betty-stat-value { color: #8d3b2f; }

/* Empty / blocked panels */
.betty-panel {
  border: 1px dashed var(--line);
  background: var(--surface);
  border-radius: var(--radius);
  padding: 1.6rem 1.5rem;
  text-align: center;
}
.betty-panel.blocked {
  border-style: solid;
  border-color: #eed3cc;
  background: #fdf6f4;
  text-align: left;
}
.betty-panel-title {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 0.3rem;
}
.betty-panel-body { color: var(--muted); font-size: 0.92rem; margin: 0 auto; max-width: 52ch; }
.betty-panel.blocked .betty-panel-body { margin: 0; }

/* Key/value rows — the key holds its column, the value wraps inside it */
.betty-kv { display: flex; gap: 0.6rem; padding: 0.24rem 0; font-size: 0.92rem; }
.betty-kv-key {
  color: var(--muted);
  flex: 0 1 124px;
  min-width: 84px;
}
.betty-kv-value { color: var(--ink); min-width: 0; overflow-wrap: anywhere; }

/* Titled list item: one line of name, one quiet line of detail */
.betty-item { padding: 0.32rem 0; }
.betty-item + .betty-item { border-top: 1px solid var(--line); }
.betty-item-name { font-size: 0.92rem; color: var(--ink); overflow-wrap: anywhere; }
.betty-item-meta { font-size: 0.84rem; color: var(--muted); margin-top: 0.05rem; }

/* Inline notes */
.betty-note { color: var(--muted); font-size: 0.86rem; margin: 0.2rem 0 0; }
.betty-quiet { color: var(--muted); font-size: 0.92rem; }
.betty-caption-body {
  background: var(--cream-deep);
  border-radius: 8px;
  padding: 0.7rem 0.9rem;
  font-size: 0.9rem;
  white-space: pre-wrap;
  color: var(--ink);
  border: 1px solid var(--line);
}

/* Before and after, side by side */
.betty-compare { display: flex; flex-wrap: wrap; gap: 0.6rem; margin: 0.3rem 0 0.2rem; }
.betty-compare-side { flex: 1 1 260px; min-width: 0; }
.betty-compare-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--muted);
  margin-bottom: 0.22rem;
}
.betty-compare-value {
  border-radius: 8px;
  padding: 0.62rem 0.8rem;
  font-size: 0.92rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border: 1px solid var(--line);
  background: var(--cream-deep);
  color: var(--muted);
}
.betty-compare-side.after .betty-compare-value {
  background: var(--jade-soft);
  border-color: #cfe4db;
  color: var(--ink);
  font-weight: 500;
}

/* One generated option */
.betty-option {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.62rem 0.8rem;
  background: var(--surface);
}
.betty-option.chosen { border-color: var(--jade); background: var(--jade-soft); }
.betty-option.rejected { border-color: #eed3cc; background: #fdf6f4; }
.betty-option-name {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--muted);
  margin-bottom: 0.2rem;
}
.betty-option-text {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.02rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.betty-option-why { color: var(--muted); font-size: 0.85rem; margin-top: 0.28rem; }

/* A requirement a person has to satisfy */
.betty-required {
  border: 1px solid #f0ddba;
  background: #fdf8ee;
  border-radius: var(--radius);
  padding: 0.85rem 1rem;
}
.betty-required-title {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 1.02rem;
  font-weight: 600;
  margin-bottom: 0.35rem;
}
.betty-required ul { margin: 0.2rem 0 0; padding-left: 1.15rem; font-size: 0.9rem; }
.betty-required li { margin-bottom: 0.12rem; }
.betty-required-unlocks { color: var(--muted); font-size: 0.86rem; margin: 0.55rem 0 0; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap: 0.15rem; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] {
  font-weight: 600;
  font-size: 0.93rem;
  color: var(--muted);
  padding: 0.5rem 0.85rem;
}
.stTabs [aria-selected="true"] { color: var(--jade) !important; }

/* Expanders */
[data-testid="stExpander"] details {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
[data-testid="stExpander"] summary { font-weight: 600; font-size: 0.93rem; }

/* Trim Streamlit chrome */
[data-testid="stHeader"] { background: transparent; }
footer, #MainMenu { visibility: hidden; }
hr { border-color: var(--line); margin: 1.5rem 0; }
</style>
"""


def inject_theme() -> None:
    st.markdown(THEME, unsafe_allow_html=True)


def _esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


# --- Headings ---------------------------------------------------------------

def page_header(
    title: str,
    subtitle: str | None = None,
    *,
    badges: Iterable[Status] = (),
) -> None:
    badge_html = badge_row(badges, inline=True) if badges else ""
    st.markdown(
        f'<div class="betty-title">{_esc(title)}</div>'
        + (f'<div class="betty-badge-row" style="margin:0.35rem 0 0.6rem;">{badge_html}</div>'
           if badge_html else "")
        + (f'<p class="betty-subtitle">{_esc(subtitle)}</p>' if subtitle else ""),
        unsafe_allow_html=True,
    )


def section(title: str, note: str | None = None) -> None:
    st.markdown(
        f'<div class="betty-section">{_esc(title)}</div>'
        + (f'<p class="betty-section-note">{_esc(note)}</p>' if note else ""),
        unsafe_allow_html=True,
    )


def note(text: str) -> None:
    st.markdown(f'<p class="betty-note">{_esc(text)}</p>', unsafe_allow_html=True)


def quiet(text: str) -> None:
    st.markdown(f'<p class="betty-quiet">{_esc(text)}</p>', unsafe_allow_html=True)


# --- Badges ----------------------------------------------------------------

def badge_html(status: Status) -> str:
    return f'<span class="betty-badge {status.tone}">{_esc(status.label)}</span>'


def badge_row(statuses: Iterable[Status], *, inline: bool = False) -> str:
    html_parts = "".join(badge_html(s) for s in statuses if s is not None)
    if inline:
        return html_parts
    return f'<div class="betty-badge-row">{html_parts}</div>'


def show_badges(statuses: Iterable[Status]) -> None:
    statuses = [s for s in statuses if s is not None]
    if not statuses:
        return
    st.markdown(badge_row(statuses), unsafe_allow_html=True)


# --- Progress rail ---------------------------------------------------------

_RAIL_STATE_WORD = {
    "complete": "Done",
    "current": "You are here",
    "blocked": "Blocked",
    "upcoming": "",
}


def progress_rail(steps: list) -> None:
    """Workflow position: Brief → Content → Create → Review → Revise → Approve → Export."""
    if not steps:
        return
    cells = "".join(
        f'<div class="betty-rail-step {step.state}">'
        f'<div class="betty-rail-dot"></div>'
        f'<div class="betty-rail-label">{_esc(step.label)}</div>'
        f'<div class="betty-rail-state">{_RAIL_STATE_WORD.get(step.state, "")}</div>'
        "</div>"
        for step in steps
    )
    st.markdown(f'<div class="betty-rail">{cells}</div>', unsafe_allow_html=True)


# --- Stat strip ------------------------------------------------------------

@dataclass
class Stat:
    label: str
    value: object
    tone: str = "neutral"


def stat_strip(stats: Iterable[Stat]) -> None:
    cells = "".join(
        f'<div class="betty-stat {stat.tone}">'
        f'<div class="betty-stat-label">{_esc(stat.label)}</div>'
        f'<div class="betty-stat-value">{_esc(stat.value)}</div>'
        "</div>"
        for stat in stats
    )
    st.markdown(f'<div class="betty-stats">{cells}</div>', unsafe_allow_html=True)


# --- States ----------------------------------------------------------------

def empty_state(title: str, body: str | None = None) -> None:
    st.markdown(
        '<div class="betty-panel">'
        f'<div class="betty-panel-title">{_esc(title)}</div>'
        + (f'<p class="betty-panel-body">{_esc(body)}</p>' if body else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def blocked_state(title: str, body: str | None = None) -> None:
    st.markdown(
        '<div class="betty-panel blocked">'
        f'<div class="betty-panel-title">{_esc(title)}</div>'
        + (f'<p class="betty-panel-body">{_esc(body)}</p>' if body else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def blocked_list(title: str, reasons: list[str]) -> None:
    items = "".join(f"<li>{_esc(reason)}</li>" for reason in reasons)
    st.markdown(
        '<div class="betty-panel blocked">'
        f'<div class="betty-panel-title">{_esc(title)}</div>'
        f'<ul class="betty-panel-body" style="margin:0.4rem 0 0;padding-left:1.1rem;">{items}</ul>'
        "</div>",
        unsafe_allow_html=True,
    )


def key_values(rows: Iterable[tuple[str, object]]) -> None:
    body = "".join(
        f'<div class="betty-kv"><div class="betty-kv-key">{_esc(key)}</div>'
        f'<div class="betty-kv-value">{_esc(value)}</div></div>'
        for key, value in rows
        if value not in (None, "")
    )
    if body:
        st.markdown(body, unsafe_allow_html=True)


def item_list(rows: Iterable[tuple[str, str]]) -> None:
    """Name-and-detail rows. Survives narrow columns better than key/value."""
    body = "".join(
        f'<div class="betty-item"><div class="betty-item-name">{_esc(name)}</div>'
        + (f'<div class="betty-item-meta">{_esc(meta)}</div>' if meta else "")
        + "</div>"
        for name, meta in rows
    )
    if body:
        st.markdown(body, unsafe_allow_html=True)


def caption_body(text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        quiet("No caption written yet.")
        return
    st.markdown(f'<div class="betty-caption-body">{_esc(cleaned)}</div>', unsafe_allow_html=True)


def comparison(
    before: object,
    after: object,
    *,
    before_label: str = "Now",
    after_label: str = "After this revision",
) -> None:
    """The change, stated plainly, before anything is applied."""
    st.markdown(
        '<div class="betty-compare">'
        f'<div class="betty-compare-side"><div class="betty-compare-label">'
        f'{_esc(before_label)}</div>'
        f'<div class="betty-compare-value">{_esc(before) or "—"}</div></div>'
        f'<div class="betty-compare-side after"><div class="betty-compare-label">'
        f'{_esc(after_label)}</div>'
        f'<div class="betty-compare-value">{_esc(after) or "—"}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )


def option_card(
    name: str,
    text: str,
    *,
    why: str = "",
    tone: str = "",
) -> None:
    """One generated option. `tone` is "chosen", "rejected", or empty."""
    st.markdown(
        f'<div class="betty-option {_esc(tone)}">'
        f'<div class="betty-option-name">{_esc(name)}</div>'
        f'<div class="betty-option-text">{_esc(text)}</div>'
        + (f'<div class="betty-option-why">{_esc(why)}</div>' if why else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def requirement_panel(
    headline: str,
    specifics: Iterable[str],
    *,
    unlocks: str = "",
) -> None:
    """What is missing, and what becomes possible once it exists."""
    items = "".join(f"<li>{_esc(item)}</li>" for item in specifics if str(item).strip())
    st.markdown(
        '<div class="betty-required">'
        f'<div class="betty-required-title">{_esc(headline)}</div>'
        + (f"<ul>{items}</ul>" if items else "")
        + (f'<p class="betty-required-unlocks">{_esc(unlocks)}</p>' if unlocks else "")
        + "</div>",
        unsafe_allow_html=True,
    )


# --- Action feedback -------------------------------------------------------

def now_label() -> str:
    return datetime.now().strftime("%-d %b %Y, %H:%M:%S")


def report(result, *, success_prefix: str | None = None) -> None:
    """Consistent outcome reporting for any WorkflowResult-shaped object."""
    if getattr(result, "ok", False):
        message = success_prefix or getattr(result, "message", "Complete.")
        st.success(f"{message}  ·  {now_label()}")
    else:
        st.error(getattr(result, "message", "That did not work."))
        detail = getattr(result, "detail", None)
        if detail:
            with st.expander("What went wrong", expanded=False):
                st.caption(str(detail).strip().splitlines()[-1] if detail else "")


FLASH_KEY = "betty_flash"


def flash(result, *, success_prefix: str | None = None) -> None:
    """Hold an outcome until after the redraw.

    An action that changes saved state has to redraw the page to show it, and a
    message written before that redraw is thrown away with the old page. This
    parks the message so the next draw can report what happened.
    """
    st.session_state.setdefault(FLASH_KEY, []).append(
        {
            "ok": bool(getattr(result, "ok", False)),
            "message": success_prefix
            if success_prefix and getattr(result, "ok", False)
            else str(getattr(result, "message", "") or ""),
            "detail": str(getattr(result, "detail", "") or ""),
            "at": now_label(),
        }
    )


def show_flashes() -> None:
    """Report anything an earlier action left behind, then forget it."""
    for entry in st.session_state.pop(FLASH_KEY, []):
        if entry["ok"]:
            st.success(f"{entry['message'] or 'Complete.'}  ·  {entry['at']}")
            continue
        st.error(entry["message"] or "That did not work.")
        if entry["detail"]:
            with st.expander("What went wrong", expanded=False):
                st.caption(entry["detail"].strip().splitlines()[-1])


def saved_note(what: str, when: str | None = None) -> None:
    st.markdown(
        f'<p class="betty-note">{badge_html(Status("saved", "Saved", "positive"))} '
        f'{_esc(what)} · {_esc(when or now_label())}</p>',
        unsafe_allow_html=True,
    )


# --- Media previews --------------------------------------------------------

def media_preview(version, *, key_prefix: str = "") -> None:
    """Preview a render version: video, image set, or copy draft."""
    primary = version.primary_path
    if primary is None or not primary.is_file():
        empty_state("Preview unavailable", "The files for this version are no longer on disk.")
        return

    suffix = primary.suffix.lower()
    if suffix in {".mp4", ".mov"}:
        st.video(str(primary))
        return
    if suffix in {".png", ".jpg", ".jpeg"}:
        images = [
            p for p in version.media_files if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ]
        if len(images) > 1:
            for row_start in range(0, len(images), 3):
                columns = st.columns(3)
                for column, image in zip(columns, images[row_start : row_start + 3]):
                    with column:
                        st.image(str(image), use_container_width=True)
        else:
            st.image(str(primary), use_container_width=True)
        return
    if suffix in {".md", ".txt"}:
        try:
            caption_body(primary.read_text(encoding="utf-8"))
        except OSError:
            quiet("This draft could not be read.")
        return
    quiet(f"No preview available for {primary.suffix.lstrip('.').upper()} files.")


def file_summary(version, *, include_metadata: bool = False) -> str:
    files = version.all_files(include_metadata=include_metadata)
    if not files:
        return "No files"
    kinds: dict[str, int] = {}
    for file in files:
        kinds[file.suffix.lstrip(".").upper()] = kinds.get(file.suffix.lstrip(".").upper(), 0) + 1
    parts = [f"{count} {kind}" for kind, count in sorted(kinds.items())]
    return ", ".join(parts)


def download_file(path: Path, *, label: str, key: str, mime: str = "application/zip") -> None:
    try:
        payload = path.read_bytes()
    except OSError:
        st.error("That file could not be read from disk.")
        return
    st.download_button(
        label,
        data=payload,
        file_name=path.name,
        mime=mime,
        key=key,
        type="primary",
        use_container_width=True,
    )
