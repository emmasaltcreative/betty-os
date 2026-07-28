"""Actions the interface can take, wrapped so every outcome is reportable.

Each function returns a `WorkflowResult` so the UI can always say what happened,
whether it succeeded, and what to do next. Backend modules are imported lazily
to keep Streamlit out of the CLI import path.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from src.brand import load_brand_brain
from src.common import (
    OUTPUTS_DIR,
    ROOT,
    BettyOSError,
    find_latest_content_package,
    new_campaign_dir,
    timestamp_stamp,
)
from src.package_parse import extract_campaign_goal
from src.production import load_production_context_for_review


@dataclass
class WorkflowResult:
    ok: bool
    message: str
    path: Path | None = None
    detail: str | None = None
    data: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _api_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise BettyOSError(
            "No API key configured.",
            hint="Add ANTHROPIC_API_KEY to the .env file in the project folder.",
        )
    return key


def _run(label: str, fn: Callable[[], Any]) -> WorkflowResult:
    try:
        result = fn()
        if isinstance(result, WorkflowResult):
            return result
        if isinstance(result, Path):
            return WorkflowResult(True, f"{label} complete.", path=result)
        if isinstance(result, tuple) and result and isinstance(result[0], Path):
            return WorkflowResult(
                True,
                f"{label} complete.",
                path=result[0],
                data={"paths": [str(p) for p in result if isinstance(p, Path)]},
            )
        if isinstance(result, dict):
            return WorkflowResult(True, f"{label} complete.", data=result)
        return WorkflowResult(True, f"{label} complete.", data={"result": result})
    except BettyOSError as exc:
        return WorkflowResult(False, exc.message, detail=exc.hint)
    except SystemExit as exc:
        code = getattr(exc, "code", 1)
        if code in (0, None):
            return WorkflowResult(True, f"{label} complete.")
        return WorkflowResult(
            False,
            f"{label} stopped before finishing.",
            detail="The step exited early.",
        )
    except Exception as exc:  # noqa: BLE001 — the UI must surface every failure
        return WorkflowResult(
            False,
            f"{label} failed: {exc}",
            detail=traceback.format_exc(limit=8),
        )


# --- Campaigns --------------------------------------------------------------

def create_campaign_folder() -> WorkflowResult:
    """Create the campaign workspace so a campaign exists before its first render."""
    return _run("Campaign", lambda: new_campaign_dir())


def archive_campaign(campaign_dir: Path) -> WorkflowResult:
    """Hide a campaign from the active list. Files are left untouched."""
    from ui.campaign_state import archive_marker

    def _inner() -> Path:
        marker = archive_marker(campaign_dir)
        marker.write_text(f"archived_at: {_now()}\n", encoding="utf-8")
        return marker

    result = _run("Archive", _inner)
    if result.ok:
        result.message = "Campaign archived. Nothing was deleted."
    return result


def restore_campaign(campaign_dir: Path) -> WorkflowResult:
    from ui.campaign_state import archive_marker

    def _inner() -> Path:
        archive_marker(campaign_dir).unlink(missing_ok=True)
        return campaign_dir

    result = _run("Restore", _inner)
    if result.ok:
        result.message = "Campaign restored to the active list."
    return result


def run_plan_campaign(
    *,
    campaign_name: str,
    campaign_goal: str,
    time_available: str,
    platforms: list[str],
    notes: str | None,
    products: list[str] | None = None,
    locations: list[str] | None = None,
) -> WorkflowResult:
    from main import ProductionSession, generate_plan, save_plan, save_session

    def _inner() -> Path:
        stamp = timestamp_stamp()
        note_parts = []
        if campaign_name.strip():
            note_parts.append(f"Campaign: {campaign_name.strip()}")
        if campaign_goal.strip():
            note_parts.append(f"Goal: {campaign_goal.strip()}")
        if notes and notes.strip():
            note_parts.append(notes.strip())

        session = ProductionSession(
            brand="Oh Betty Jaletti",
            time_available=time_available.strip() or "2 hours",
            creating_for=platforms or ["Instagram"],
            products=products or ["First Edition: The Reading Hour"],
            locations=locations or ["Home studio"],
            notes="\n".join(note_parts) if note_parts else None,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        save_session(session, stamp)
        plan = generate_plan(session, _api_key())
        return save_plan(plan, stamp)

    return _run("Production plan", _inner)


def run_ingest_folder(folder: str | Path) -> WorkflowResult:
    from main import ingest_folder

    path = Path(folder).expanduser()
    if not path.exists() or not path.is_dir():
        return WorkflowResult(
            False,
            "That media folder does not exist.",
            detail=str(path),
        )

    def _inner() -> str:
        ingest_folder(path, force=False)
        return str(path)

    result = _run("Media indexing", _inner)
    if result.ok:
        result.message = "Media indexed."
        result.path = path
    return result


def run_repurpose_package(
    *,
    campaign_goal: str,
    platforms: list[str],
    content_count: int = 5,
    notes: str | None = None,
) -> WorkflowResult:
    from main import (
        RepurposeBrief,
        build_repurpose_prompt,
        generate_content_package,
        load_assets,
        load_latest_session,
        save_content_package,
    )

    def _inner() -> Path:
        assets = load_assets()
        if not assets:
            raise BettyOSError(
                "No media has been indexed yet.",
                hint="Add a media folder when you create the campaign.",
            )
        brief = RepurposeBrief(
            campaign_goal=campaign_goal.strip()
            or "Grow a qualified waitlist for First Edition: The Reading Hour",
            platforms=platforms or ["Instagram", "Pinterest"],
            content_count=max(1, int(content_count)),
            notes=notes.strip() if notes else None,
        )
        prompt = build_repurpose_prompt(assets, brief, load_latest_session())
        return save_content_package(generate_content_package(prompt, _api_key()))

    return _run("Campaign content", _inner)


# --- Templates and rendering ------------------------------------------------

def save_piece_template_override(
    package_path: Path,
    *,
    piece_id: str,
    template_id: str,
) -> WorkflowResult:
    from src.templates.assignments import set_piece_template

    def _inner() -> Path:
        set_piece_template(
            package_path,
            piece_id=piece_id,
            template_id=template_id,
            override=True,
        )
        return package_path.with_name(package_path.stem + ".assignments.json")

    result = _run("Template choice", _inner)
    if result.ok:
        result.message = "Template saved."
    return result


def copy_fields_for_piece(record: Any) -> dict[str, str]:
    """Copy the renderers actually read, taken from the content piece."""
    body = str(getattr(record, "body_markdown", "") or "")
    title = str(getattr(record, "title", "") or "")
    return {
        "caption": body[:500],
        "hook_text": title,
        "headline": title,
        "title": title,
        "cta_text": "Join the waitlist",
    }


def render_piece(
    *,
    template_id: str,
    content_piece_id: str,
    source_assets: list[str],
    campaign_dir: Path,
    copy_fields: dict[str, str] | None = None,
    title: str = "",
    duration_seconds: float | None = None,
    cta_appear_at_seconds: float | None = None,
) -> WorkflowResult:
    from renderers.dispatch import render_template

    def _inner() -> dict[str, Any]:
        return render_template(
            template_id=template_id,
            content_piece_id=content_piece_id,
            source_assets=source_assets,
            campaign_dir=campaign_dir,
            copy_fields=copy_fields,
            title=title,
            duration_seconds=duration_seconds,
            cta_appear_at_seconds=cta_appear_at_seconds,
        )

    result = _run("Render", _inner)
    if result.ok:
        version = (result.data or {}).get("version")
        result.message = f"Render complete — version {version}." if version else "Render complete."
    return result


def render_ready_pieces(campaign_dir: Path, pieces: list[Any]) -> WorkflowResult:
    """Render every piece that is ready, reporting each outcome separately."""
    rendered: list[str] = []
    failed: list[str] = []
    detail_lines: list[str] = []

    for piece in pieces:
        outcome = render_piece(
            template_id=piece.template_id,
            content_piece_id=piece.record.piece_id,
            source_assets=piece.record.source_assets,
            campaign_dir=campaign_dir,
            copy_fields=copy_fields_for_piece(piece.record),
            title=piece.record.title,
        )
        if outcome.ok:
            rendered.append(piece.record.title)
        else:
            failed.append(piece.record.title)
            detail_lines.append(f"{piece.record.title}: {outcome.message}")

    if not rendered and not failed:
        return WorkflowResult(False, "Nothing was ready to render.")
    if failed and not rendered:
        return WorkflowResult(
            False,
            f"None of the {len(failed)} renders succeeded.",
            detail="\n".join(detail_lines),
            data={"rendered": rendered, "failed": failed},
        )
    message = f"Rendered {len(rendered)} of {len(rendered) + len(failed)} pieces."
    return WorkflowResult(
        True,
        message,
        detail="\n".join(detail_lines) or None,
        data={"rendered": rendered, "failed": failed},
    )


# --- Creative review -------------------------------------------------------

def run_creative_review(
    *,
    package_path: Path | None = None,
    campaign_dir: Path | None = None,
) -> WorkflowResult:
    from main import build_render_review_context
    from review.review_engine import run_creative_review as run_review_core
    from src.common import find_latest_render_dirs
    from ui.data_access import list_render_dirs_for_campaign

    def _inner() -> Path:
        pkg_path = (
            package_path
            if package_path and package_path.is_file()
            else find_latest_content_package()
        )
        package_text = pkg_path.read_text(encoding="utf-8")
        render_dirs = (
            list_render_dirs_for_campaign(campaign_dir)
            if campaign_dir is not None
            else find_latest_render_dirs()
        )
        render_context, render_names, image_blocks = build_render_review_context(render_dirs)
        review_path, _scores_path, _result = run_review_core(
            brand_brain=load_brand_brain(),
            production_brain=load_production_context_for_review(),
            content_package=package_text,
            campaign_goal=extract_campaign_goal(package_text) or "Not specified",
            render_context=render_context,
            api_key=_api_key(),
            outputs_dir=OUTPUTS_DIR,
            package_name=pkg_path.name,
            render_names=render_names,
            image_blocks=image_blocks or None,
        )
        return review_path

    result = _run("Creative Review", _inner)
    if result.ok:
        result.message = "Creative Review complete."
    return result


def persist_recommendation_status(
    recommendation_id: str,
    status: str,
    *,
    full_instruction: str | None = None,
) -> WorkflowResult:
    from review.recommendations import update_recommendation_status
    from review.scoring import ensure_scores_recommendations
    from ui.data_access import load_latest_scores, save_latest_scores

    def _inner() -> Path:
        scores = load_latest_scores()
        if not scores:
            raise BettyOSError("There is no review to update yet.")
        scores = ensure_scores_recommendations(scores)
        scores["recommendations"] = update_recommendation_status(
            list(scores.get("recommendations") or []),
            recommendation_id,
            status,
            full_instruction=full_instruction,
        )
        return save_latest_scores(scores)

    return _run("Recommendation", _inner)


def dismiss_recommendation(recommendation_id: str) -> WorkflowResult:
    result = persist_recommendation_status(recommendation_id, "dismissed")
    if result.ok:
        result.message = "Recommendation dismissed. Nothing was changed."
    return result


# --- AI-assisted revisions --------------------------------------------------

def classify_recommendations(
    campaign_dir: Path,
    recommendations: list[dict[str, Any]],
    *,
    force: bool = False,
) -> WorkflowResult:
    """Read every recommendation in context and decide what BettyOS can do about it."""
    from services.llm import api_key_present
    from services.revision_classifier import ensure_classifications

    def _inner() -> dict[str, Any]:
        results, fresh = ensure_classifications(
            campaign_dir=campaign_dir,
            recommendations=recommendations,
            use_model=api_key_present(),
            force=force,
        )
        return {"classifications": results, "fresh": fresh}

    result = _run("Capability check", _inner)
    if result.ok:
        fresh = int((result.data or {}).get("fresh") or 0)
        result.message = (
            f"Checked {fresh} recommendation{'s' if fresh != 1 else ''}."
            if fresh
            else "Every recommendation was already checked."
        )
    return result


def _revision_action(label: str, fn: Callable[[], Any], success: str) -> WorkflowResult:
    """Run one revision action. `_run` returns the saved request as `data`."""
    result = _run(label, fn)
    if result.ok:
        result.message = success
        result.data = {"request": result.data or {}}
    return result


def start_revision(
    campaign_dir: Path,
    *,
    recommendation: dict[str, Any],
    classification: Any = None,
    instruction: str = "",
) -> WorkflowResult:
    from services.revision_workflow import open_request

    return _revision_action(
        "Revision",
        lambda: open_request(
            campaign_dir,
            recommendation=recommendation,
            classification=classification,
            instruction=instruction,
        ),
        "Revision started. Nothing has been changed yet.",
    )


def save_revision_instruction(
    campaign_dir: Path, request_id: str, instruction: str
) -> WorkflowResult:
    from services.revision_workflow import set_instruction

    return _revision_action(
        "Instruction",
        lambda: set_instruction(campaign_dir, request_id, instruction),
        "Instruction saved. The original recommendation is unchanged.",
    )


def generate_revision_options(
    campaign_dir: Path,
    request_id: str,
    *,
    count: int = 3,
    similar_to_option_id: str | None = None,
    replace: bool = False,
) -> WorkflowResult:
    from services.revision_workflow import generate

    def _inner() -> dict[str, Any]:
        return generate(
            campaign_dir,
            request_id,
            count=count,
            similar_to_option_id=similar_to_option_id,
            replace=replace,
        )

    result = _run("Suggestions", _inner)
    if not result.ok:
        return result
    request = result.data or {}
    options = request.get("generated_options") or []
    result.data = {"request": request}
    result.message = (
        f"{len(options)} option{'s' if len(options) != 1 else ''} ready. "
        "Nothing is applied until you approve one."
    )
    return result


def select_revision_option(
    campaign_dir: Path, request_id: str, option_id: str
) -> WorkflowResult:
    from services.revision_workflow import select

    return _revision_action(
        "Selection",
        lambda: select(campaign_dir, request_id, option_id),
        "Option selected. Review the comparison, then apply it.",
    )


def edit_revision_selection(
    campaign_dir: Path,
    request_id: str,
    text: str,
    *,
    option_id: str | None = None,
) -> WorkflowResult:
    from services.revision_workflow import edit_selection

    return _revision_action(
        "Edit",
        lambda: edit_selection(campaign_dir, request_id, text, option_id=option_id),
        "Edited wording saved and checked against the Brand Guide.",
    )


def cancel_revision_selection(campaign_dir: Path, request_id: str) -> WorkflowResult:
    from services.revision_workflow import cancel_selection

    return _revision_action(
        "Selection",
        lambda: cancel_selection(campaign_dir, request_id),
        "Selection cleared. The options are still here.",
    )


def defer_revision(campaign_dir: Path, request_id: str) -> WorkflowResult:
    from services.revision_workflow import defer

    return _revision_action(
        "Revision",
        lambda: defer(campaign_dir, request_id),
        "Saved for later. It is waiting on the Revisions page.",
    )


def resume_revision(campaign_dir: Path, request_id: str) -> WorkflowResult:
    from services.revision_workflow import resume

    return _revision_action(
        "Revision", lambda: resume(campaign_dir, request_id), "Reopened."
    )


def dismiss_revision(campaign_dir: Path, request_id: str) -> WorkflowResult:
    from services.revision_workflow import dismiss

    return _revision_action(
        "Revision",
        lambda: dismiss(campaign_dir, request_id),
        "Revision dismissed. Nothing was changed.",
    )


def set_revision_change(
    campaign_dir: Path, request_id: str, change: dict[str, Any]
) -> WorkflowResult:
    from services.revision_workflow import set_change

    return _revision_action(
        "Setting change",
        lambda: set_change(campaign_dir, request_id, change),
        "Setting change saved. Review it, then apply it.",
    )


def attach_revision_asset(
    campaign_dir: Path, request_id: str, *, filename: str, data: bytes
) -> WorkflowResult:
    from services.revision_workflow import attach_asset

    return _revision_action(
        "Source asset",
        lambda: attach_asset(campaign_dir, request_id, filename=filename, data=data),
        f"{Path(filename).name} added to this campaign's source assets.",
    )


def retry_revision(campaign_dir: Path, request_id: str) -> WorkflowResult:
    from services.revision_workflow import retry

    return _revision_action(
        "Revision",
        lambda: retry(campaign_dir, request_id),
        "Ready to try again.",
    )


def apply_revision_request(campaign_dir: Path, request_id: str) -> WorkflowResult:
    """Build a new version from an approved revision. The original is untouched."""
    from services.revision_apply import apply_revision
    from services.revision_workflow import approve_to_apply

    def _inner() -> dict[str, Any]:
        approve_to_apply(campaign_dir, request_id)
        return apply_revision(campaign_dir, request_id)

    result = _run("Revision", _inner)
    if not result.ok:
        return result
    outcome = result.data or {}
    if not outcome.get("ok"):
        return WorkflowResult(
            False,
            str(outcome.get("failure_reason") or "The revision could not be applied."),
            detail="Nothing was changed. The reason is saved with the revision.",
            data=outcome,
        )
    if outcome.get("already_applied"):
        result.message = f"Already applied as version {outcome.get('version')}."
        return result
    result.message = (
        f"{outcome.get('asset_name')} version {outcome.get('version_number')} created from "
        f"version {outcome.get('parent_version')}. It is awaiting review under Approvals."
    )
    return result


def revision_preview(campaign_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
    """Before and after for one revision. Safe to call on every page render."""
    from services.revision_apply import preview

    return preview(campaign_dir, request)


# --- Approvals -------------------------------------------------------------

def _item_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov"}:
        return "video"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "image"
    if "caption" in path.name.lower():
        return "caption"
    if suffix in {".md", ".txt"}:
        return "copy"
    return "file"


def save_version_decision(
    campaign_dir: Path,
    *,
    version: Any,
    status: str,
    note: str = "",
) -> WorkflowResult:
    """Record one decision for a whole render version.

    Approvals are stored per file so the CLI approval pass keeps working, but the
    decision is made once. Existing records outside this version are preserved —
    the whole item list is rewritten in a single verified write.
    """
    from src.templates.approvals_store import load_campaign_approvals, write_campaign_approvals
    from src.templates.models import APPROVAL_STATUSES
    from ui.campaign_state import approval_scope

    if status not in APPROVAL_STATUSES:
        return WorkflowResult(False, f"`{status}` is not a valid decision.")

    def _inner() -> Path:
        data = load_campaign_approvals(campaign_dir)
        items = [dict(item) for item in (data.get("items") or []) if isinstance(item, dict)]
        stamp = _now()
        clean_note = note.strip()
        asset_id = version.piece_id or version.folder.name

        touched_paths: set[str] = set()
        for index, item in enumerate(items):
            template_id, piece_id = approval_scope(str(item.get("file_path") or ""))
            raw_version = str(item.get("render_version_id") or "v1").lstrip("vV")
            try:
                item_version = int(raw_version)
            except ValueError:
                item_version = 1
            if (
                template_id == version.template_id
                and piece_id == version.piece_id
                and item_version == version.version
            ):
                item["status"] = status
                item["note"] = clean_note
                item["reviewed_at"] = stamp if status != "awaiting_review" else None
                item["updated_at"] = stamp
                items[index] = item
                touched_paths.add(str(item.get("file_path") or ""))

        for file in version.all_files(include_metadata=False):
            try:
                relative = file.resolve().relative_to(campaign_dir.resolve()).as_posix()
            except ValueError:
                continue
            if relative in touched_paths:
                continue
            items.append(
                {
                    "campaign_id": campaign_dir.name,
                    "asset_id": asset_id,
                    "template_id": version.template_id,
                    "render_version_id": f"v{version.version}",
                    "status": status,
                    "note": clean_note,
                    "reviewed_at": stamp if status != "awaiting_review" else None,
                    "updated_at": stamp,
                    "file_path": relative,
                    "item_name": file.name,
                    "item_type": _item_type_for(file),
                }
            )

        path = write_campaign_approvals(campaign_dir, {"items": items})
        _mirror_version_status(version, status)
        _mirror_finish_status(version, status)
        _write_approval_summary(campaign_dir, items)
        return path

    result = _run("Decision", _inner)
    if result.ok:
        result.message = "Decision saved."
    return result


def _mirror_version_status(version: Any, status: str) -> None:
    """Keep `versions.json` in step where a render folder tracks versions."""
    from review.versioning import VERSION_MANIFEST, set_version_review_status

    if not (version.folder / VERSION_MANIFEST).is_file():
        return
    try:
        set_version_review_status(version.folder, version.version, status)
    except OSError:
        pass


def _mirror_finish_status(version: Any, status: str) -> None:
    """Carry the decision onto the Studio finished versions it covers.

    Approvals decides once per render version. A finished version that Studio
    sent to Review is part of that decision, so it must not be left reading
    "awaiting review" after a person has signed the work off. Drafts nobody
    submitted are untouched, and the finished media itself is never rewritten —
    only the status field in its metadata.
    """
    from studio.models import APPROVAL_STATUSES as FINISH_APPROVAL_STATUSES
    from studio.versions import update_finish_status
    from ui.campaign_state import finish_records_for_version

    if status not in FINISH_APPROVAL_STATUSES:
        return
    for record in finish_records_for_version(version):
        if record.status != "ready_for_review":
            continue
        try:
            update_finish_status(version.folder, record.finish_version_id, approval_status=status)
        except (KeyError, OSError, RuntimeError):
            continue


def _write_approval_summary(campaign_dir: Path, items: list[dict[str, Any]]) -> None:
    """Refresh the human-readable summary the CLI also produces."""
    from main import write_approval_summary

    try:
        write_approval_summary(campaign_dir, items)
    except Exception:  # noqa: BLE001 — the summary is a convenience, not the record
        pass


# --- Template definitions (advanced) ---------------------------------------

def register_planned_template(payload: dict[str, Any]) -> WorkflowResult:
    from src.templates.registry import upsert_template

    def _inner() -> dict[str, Any]:
        record = {
            **payload,
            "renderer_status": "planned",
            "version": payload.get("version") or "1.0.0",
        }
        return upsert_template(record).model_dump()

    result = _run("Template definition", _inner)
    if result.ok:
        result.message = (
            "Template definition saved as Planned. It cannot render until a "
            "renderer is written for it."
        )
    return result
