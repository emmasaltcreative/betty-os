"""Complete unfinished publishing copy excluded from a Publishing Package.

Generates one Brand Guide-aligned Pinterest description per excluded record,
writes a clean metadata document (no production notes), and revalidates the
package. Never creates orphaned metadata entries in the ZIP — pairing rules in
export_service still apply after approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common import DEFAULT_BRAND_ID
from ui.campaign_state import CampaignState, RenderVersion
from ui.export_service import (
    ExportExclusion,
    ExportPlan,
    METADATA_TEMPLATES,
    PUBLISHING_MODE,
    actionable_incomplete_exclusions,
    build_plan,
)
from ui.publishing_validation import validate_pinterest_metadata_text


@dataclass
class CopyCompletionDraft:
    exclusion: ExportExclusion
    version: RenderVersion | None
    source_path: Path | None
    title: str
    cta: str
    proposed_description: str
    platform: str = "Pinterest"
    content_piece_id: str | None = None
    status: str = "proposed"  # proposed | approved | needs_revision | edited
    edited_description: str = ""
    message: str = ""

    @property
    def description(self) -> str:
        return (self.edited_description or self.proposed_description).strip()


@dataclass
class CopyCompletionSession:
    drafts: list[CopyCompletionDraft] = field(default_factory=list)
    revalidated_plan: ExportPlan | None = None

    @property
    def count(self) -> int:
        return len(self.drafts)


def resolve_version_for_exclusion(
    state: CampaignState, exclusion: ExportExclusion
) -> RenderVersion | None:
    if exclusion.version_key:
        for version in state.versions:
            if version.key == exclusion.version_key:
                return version
    if exclusion.content_piece_id:
        for version in state.versions:
            if (
                version.piece_id == exclusion.content_piece_id
                and version.template_id in METADATA_TEMPLATES
            ):
                return version
    if exclusion.source_path:
        path = Path(exclusion.source_path)
        for version in state.versions:
            if version.primary_path and version.primary_path.resolve() == path.resolve():
                return version
            if path in version.support_files or path in version.media_files:
                return version
    return None


def draft_best_pinterest_description(
    *,
    title: str,
    campaign_goal: str,
    piece_objective: str = "",
    brand_id: str = DEFAULT_BRAND_ID,
) -> str:
    """One best description. Prefer Brand Guide voice; never invent product claims."""
    subject = (piece_objective or title or "the reading hour").strip().rstrip("*").strip()
    goal = (campaign_goal or "").strip()
    try:
        from src.brand import load_brand_brain

        brain = load_brand_brain(brand_id)
    except Exception:  # noqa: BLE001
        brain = ""

    # Optional LLM path — fall back to a quiet deterministic draft for offline/tests.
    try:
        from services.llm import GenerationError, complete_json

        prompt = (
            "Write one Pinterest pin description for a small independent brand.\n"
            "Return ONLY JSON: {\"description\": \"...\"}\n"
            "Rules: invite without pressure; no scarcity; no generic lifestyle filler; "
            "no production notes, asset paths, or shot instructions; max 400 characters; "
            "do not use em dashes by default (prefer periods, commas, or colons).\n"
            f"Pin title: {subject}\n"
            f"Campaign goal: {goal}\n"
            f"Brand Guide:\n{brain[:3500]}\n"
        )
        payload = complete_json(prompt)
        text = str((payload or {}).get("description") or "").strip()
        if text and len(text) >= 24:
            from services.em_dash import rewrite_em_dashes

            return rewrite_em_dashes(text[:500])
    except Exception:  # noqa: BLE001 — include GenerationError / import failures
        pass

    if "waitlist" in goal.lower():
        raw = (
            f"{subject}. A quiet moment worth keeping. "
            f"Join the waitlist when you are ready."
        )
    elif subject:
        raw = f"{subject}. Soft light, an unhurried page, and room to linger."
    else:
        raw = "A quiet reading hour. Soft light, an open page, and room to linger."
    from services.em_dash import rewrite_em_dashes

    return rewrite_em_dashes(raw)


def build_clean_pinterest_metadata(*, title: str, description: str, cta: str) -> str:
    title_text = (title or "Pinterest pin").strip()
    desc = (description or "").strip()
    cta_text = (cta or "Join the waitlist").strip()
    return (
        "# Pinterest Pin Description\n\n"
        f"**Title:** {title_text}\n\n"
        f"**Description:**\n{desc}\n\n"
        f"**CTA:** {cta_text}\n"
    )


def write_clean_pinterest_metadata(
    path: Path, *, title: str, description: str, cta: str
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_clean_pinterest_metadata(title=title, description=description, cta=cta),
        encoding="utf-8",
    )
    return path


def open_completion_session(
    state: CampaignState, plan: ExportPlan | None = None
) -> CopyCompletionSession:
    plan = plan or build_plan(state, mode=PUBLISHING_MODE)
    drafts: list[CopyCompletionDraft] = []
    for exclusion in actionable_incomplete_exclusions(plan):
        version = resolve_version_for_exclusion(state, exclusion)
        source = Path(exclusion.source_path) if exclusion.source_path else None
        if source is None and version is not None:
            source = version.primary_path
            if source is None or not source.is_file():
                docs = [p for p in version.all_files(include_metadata=False) if p.is_file()]
                source = docs[0] if docs else None
        title = ""
        cta = "Join the waitlist"
        if source and source.is_file():
            from services.copy_documents import CopyDocument

            doc = CopyDocument.from_text(source.read_text(encoding="utf-8"))
            title = (doc.read("pinterest_title") or "").strip() or (
                state.piece_title(version) if version else exclusion.label
            )
            cta = (doc.read("pinterest_cta") or "").strip() or cta
        else:
            title = (state.piece_title(version) if version else "") or exclusion.label

        proposed = draft_best_pinterest_description(
            title=title,
            campaign_goal=state.goal,
            piece_objective=state.piece_title(version) if version else title,
        )
        drafts.append(
            CopyCompletionDraft(
                exclusion=exclusion,
                version=version,
                source_path=source,
                title=title,
                cta=cta,
                proposed_description=proposed,
                content_piece_id=exclusion.content_piece_id,
            )
        )
    return CopyCompletionSession(drafts=drafts)


def approve_draft(draft: CopyCompletionDraft, *, text: str | None = None) -> CopyCompletionDraft:
    description = (text if text is not None else draft.description).strip()
    if not draft.source_path:
        draft.status = "needs_revision"
        draft.message = "Source metadata file is missing."
        return draft
    write_clean_pinterest_metadata(
        draft.source_path,
        title=draft.title,
        description=description,
        cta=draft.cta,
    )
    check = validate_pinterest_metadata_text(draft.source_path.read_text(encoding="utf-8"))
    if not check.ok:
        draft.status = "needs_revision"
        draft.message = check.blockers[0].message if check.blockers else "Still incomplete"
        return draft
    draft.proposed_description = description
    draft.edited_description = description
    draft.status = "approved"
    draft.message = "Description approved and saved."
    return draft


def mark_needs_revision(draft: CopyCompletionDraft, note: str = "") -> CopyCompletionDraft:
    draft.status = "needs_revision"
    draft.message = note or "Marked as needing revision. Nothing was published."
    return draft


def edit_draft(draft: CopyCompletionDraft, text: str) -> CopyCompletionDraft:
    draft.edited_description = text.strip()
    draft.status = "edited"
    draft.message = "Edited locally. Approve to save."
    return draft


def revalidate_after_completion(state: CampaignState) -> ExportPlan:
    """Rebuild the publishing plan after copy edits. Pairing rules still apply."""
    return build_plan(state, mode=PUBLISHING_MODE)


def session_to_dict(session: CopyCompletionSession) -> dict[str, Any]:
    return {
        "drafts": [
            {
                "version_key": d.exclusion.version_key,
                "content_piece_id": d.content_piece_id,
                "source_path": str(d.source_path) if d.source_path else None,
                "title": d.title,
                "cta": d.cta,
                "proposed_description": d.proposed_description,
                "edited_description": d.edited_description,
                "status": d.status,
                "message": d.message,
                "label": d.exclusion.label,
                "missing_fields": list(d.exclusion.missing_fields),
            }
            for d in session.drafts
        ]
    }


MATCHING_PIN_TEMPLATES = (
    "editorial_static_pin",
    "text_led_editorial_pin",
    "pinterest_collage_pin",
    "product_feature_pin",
)


def orphaned_metadata_exclusions(plan: ExportPlan) -> list[ExportExclusion]:
    return [e for e in plan.excluded if e.category == "orphaned"]


def matching_pin_template_for_piece(state: CampaignState, piece_id: str | None) -> str | None:
    """Return a supported static pin template when a matching visual can be rendered."""
    if not piece_id:
        return None
    piece = next((p for p in state.pieces if p.record.piece_id == piece_id), None)
    if piece is None:
        return None
    sources = list(piece.record.source_assets or [])
    if not sources:
        return None
    from renderers.static import STATIC_READY
    from src.templates.registry import get_template
    from ui.capability import renderability

    # Prefer editorial static pin for 2:3 Pinterest stills.
    preferred = ["editorial_static_pin", "text_led_editorial_pin", "pinterest_collage_pin"]
    for template_id in preferred:
        if template_id not in STATIC_READY and template_id not in MATCHING_PIN_TEMPLATES:
            continue
        template = get_template(template_id)
        if template is None:
            continue
        check = renderability(
            template_id,
            template.renderer_status,
            template.renderer_module or "static",
        )
        if check.can_render:
            return template_id
    return None


def archive_incomplete_record(state: CampaignState, exclusion: ExportExclusion) -> dict[str, Any]:
    """Mark an orphaned metadata record archived so it stops competing with readiness."""
    version = resolve_version_for_exclusion(state, exclusion)
    folder = None
    if version is not None:
        folder = version.folder
    elif exclusion.source_path:
        folder = Path(exclusion.source_path).parent
    if folder is None:
        return {"ok": False, "error": "Could not locate the metadata record on disk."}
    marker = folder / ".archived_incomplete_record"
    marker.write_text(
        "archived_reason: no_matching_final_visual_asset\n"
        f"content_piece_id: {exclusion.content_piece_id or ''}\n",
        encoding="utf-8",
    )
    return {"ok": True, "path": str(marker), "folder": str(folder)}


def is_archived_incomplete_record(version: RenderVersion) -> bool:
    return (version.folder / ".archived_incomplete_record").is_file()
