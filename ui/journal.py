"""Creative Journal — meaningful campaign events in human language.

Reads existing durable records. Does not log every technical event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.common import DEFAULT_BRAND_ID
from studio.learning import list_approval_events
from ui.capability import parse_iso
from ui.campaign_state import CampaignState, finish_records_for_version


@dataclass(frozen=True)
class JournalEntry:
    when: datetime
    date_label: str
    text: str
    source: str  # approvals | revisions | studio | export | learning


def journal_for_campaign(
    state: CampaignState,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    limit: int = 12,
) -> list[JournalEntry]:
    if not state.exists or state.path is None:
        return []

    events: list[JournalEntry] = []
    campaign_id = state.path.name

    for version in state.versions:
        title = state.piece_title(version) or version.display_name
        if version.reviewed_at:
            stamp = parse_iso(version.reviewed_at)
            if stamp:
                label = _status_phrase(version.approval_status)
                events.append(
                    JournalEntry(
                        when=stamp,
                        date_label=_date_label(stamp),
                        text=f"{title} was {label}.",
                        source="approvals",
                    )
                )
                if version.approval_note.strip():
                    events.append(
                        JournalEntry(
                            when=stamp,
                            date_label=_date_label(stamp),
                            text=_note_sentence(version.approval_note),
                            source="approvals",
                        )
                    )
        for record in finish_records_for_version(version):
            decision = record.edit_decision or {}
            if not isinstance(decision, dict):
                continue
            summaries = (
                decision.get("major_decision_summaries")
                or decision.get("key_decisions")
                or []
            )
            created = parse_iso(record.created_at) or parse_iso(record.updated_at)
            if not created:
                continue
            for summary in list(summaries)[:2]:
                text = str(summary).strip()
                if text:
                    events.append(
                        JournalEntry(
                            when=created,
                            date_label=_date_label(created),
                            text=_ensure_sentence(text),
                            source="studio",
                        )
                    )
            logo = decision.get("logo_decision") or {}
            if isinstance(logo, dict) and logo.get("decision") == "omit":
                reason = logo.get("reason") or logo.get("rationale") or ""
                if reason:
                    events.append(
                        JournalEntry(
                            when=created,
                            date_label=_date_label(created),
                            text=_ensure_sentence(str(reason)),
                            source="studio",
                        )
                    )

    for event in list_approval_events(brand_id):
        if event.campaign_id != campaign_id:
            continue
        stamp = parse_iso(event.created_at)
        if stamp is None:
            continue
        if event.status == "approved" and event.revision_note:
            events.append(
                JournalEntry(
                    when=stamp,
                    date_label=_date_label(stamp),
                    text=_ensure_sentence(event.revision_note),
                    source="approvals",
                )
            )
        elif event.logo_decision == "omit":
            events.append(
                JournalEntry(
                    when=stamp,
                    date_label=_date_label(stamp),
                    text="A persistent logo was omitted because it weakened the composition.",
                    source="learning",
                )
            )

    # Export packages
    from ui.capability import exports_dir

    folder = exports_dir()
    if folder.is_dir():
        for path in sorted(folder.glob(f"{campaign_id}*.zip"), reverse=True)[:3]:
            stamp = datetime.fromtimestamp(path.stat().st_mtime)
            events.append(
                JournalEntry(
                    when=stamp,
                    date_label=_date_label(stamp),
                    text="The publishing package was downloaded.",
                    source="export",
                )
            )

    events.sort(key=lambda e: e.when, reverse=True)
    # Deduplicate near-identical consecutive texts
    deduped: list[JournalEntry] = []
    seen: set[str] = set()
    for entry in events:
        key = entry.text.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
        if len(deduped) >= limit:
            break
    return deduped


def recent_learning_summary(
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    limit: int = 3,
) -> list[str]:
    """Short lines suitable for a quiet Today footnote."""
    from studio.learning import list_creative_findings

    findings = list_creative_findings(brand_id, active_only=True)
    lines: list[str] = []
    for finding in findings:
        text = (finding.finding or finding.statement or "").strip()
        if not text:
            continue
        if finding.status != "promoted" and finding.evidence_count < 2:
            continue
        lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def _status_phrase(status: str) -> str:
    return {
        "approved": "approved",
        "needs_revision": "marked for revision",
        "rejected": "rejected",
        "awaiting_review": "sent for review",
    }.get(status, status.replace("_", " "))


def _note_sentence(note: str) -> str:
    text = note.strip()
    if not text:
        return text
    if text[0].islower():
        text = text[0].upper() + text[1:]
    return _ensure_sentence(text)


def _ensure_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] not in ".!?":
        text += "."
    return text


def _date_label(when: datetime) -> str:
    return when.strftime("%B %-d")
