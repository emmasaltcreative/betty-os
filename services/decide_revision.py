"""Decide revision orchestration — classify, plan, execute, brand-check.

Persists job state on disk so Streamlit reruns do not leave the UI stuck on
“I’m addressing your feedback…” forever.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.auto_edit import load_brand_guide, parse_revision_request

RevisionCategory = Literal[
    "copy",
    "caption",
    "visual_selection",
    "sequencing",
    "pacing",
    "crop",
    "typography",
    "color",
    "audio",
    "logo",
    "creative_direction",
    "unsupported",
]

JobStatus = Literal[
    "interpreting",
    "awaiting_plan_confirmation",
    "rewriting_copy",
    "rebuilding",
    "finishing",
    "brand_check",
    "ready",
    "failed",
    "cancelled",
]

PHASE_LABELS = {
    "interpreting": "Interpreting your feedback",
    "awaiting_plan_confirmation": "Reviewing the revision plan",
    "rewriting_copy": "Rewriting the copy",
    "rebuilding": "Rebuilding the reel",
    "finishing": "Applying the finish",
    "brand_check": "Running the Brand Check",
    "ready": "Preparing the revision",
    "failed": "Revision stopped",
    "cancelled": "Revision cancelled",
}


@dataclass
class RevisionPlan:
    category: RevisionCategory
    summary_lines: list[str]
    field_key: str = "overlay_hook"
    field_label: str = "Opening on-screen hook"
    original_copy: str = ""
    proposed_copy: str = ""
    why_changed: str = ""
    preserve_footage: bool = True
    preserve_pacing: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RevisionPlan:
        data = data or {}
        return cls(
            category=str(data.get("category") or "copy"),  # type: ignore[arg-type]
            summary_lines=list(data.get("summary_lines") or []),
            field_key=str(data.get("field_key") or "overlay_hook"),
            field_label=str(data.get("field_label") or "Opening on-screen hook"),
            original_copy=str(data.get("original_copy") or ""),
            proposed_copy=str(data.get("proposed_copy") or ""),
            why_changed=str(data.get("why_changed") or ""),
            preserve_footage=bool(data.get("preserve_footage", True)),
            preserve_pacing=bool(data.get("preserve_pacing", True)),
        )


@dataclass
class RevisionJob:
    job_id: str
    campaign_id: str
    version_key: str
    finish_version_id: str | None
    feedback: str
    status: JobStatus
    phase_label: str
    plan: RevisionPlan | None = None
    error: str = ""
    new_finish_version_id: str | None = None
    new_render_path: str | None = None
    new_render_version: int | None = None
    new_version_key: str | None = None
    brand_check: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    what_changed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "campaign_id": self.campaign_id,
            "version_key": self.version_key,
            "finish_version_id": self.finish_version_id,
            "feedback": self.feedback,
            "status": self.status,
            "phase_label": self.phase_label,
            "plan": self.plan.as_dict() if self.plan else None,
            "error": self.error,
            "new_finish_version_id": self.new_finish_version_id,
            "new_render_path": self.new_render_path,
            "new_render_version": self.new_render_version,
            "new_version_key": self.new_version_key,
            "brand_check": self.brand_check,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "what_changed": list(self.what_changed),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RevisionJob:
        return cls(
            job_id=str(data.get("job_id") or ""),
            campaign_id=str(data.get("campaign_id") or ""),
            version_key=str(data.get("version_key") or ""),
            finish_version_id=data.get("finish_version_id"),
            feedback=str(data.get("feedback") or ""),
            status=str(data.get("status") or "failed"),  # type: ignore[arg-type]
            phase_label=str(data.get("phase_label") or ""),
            plan=RevisionPlan.from_dict(data.get("plan")) if data.get("plan") else None,
            error=str(data.get("error") or ""),
            new_finish_version_id=data.get("new_finish_version_id"),
            new_render_path=data.get("new_render_path"),
            new_render_version=data.get("new_render_version"),
            new_version_key=data.get("new_version_key"),
            brand_check=dict(data.get("brand_check") or {}),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            what_changed=list(data.get("what_changed") or []),
        )

    @property
    def is_active(self) -> bool:
        return self.status not in {"ready", "failed", "cancelled", "awaiting_plan_confirmation"}

    @property
    def awaiting_confirmation(self) -> bool:
        return self.status == "awaiting_plan_confirmation"


def jobs_dir(campaign_dir: Path) -> Path:
    path = Path(campaign_dir) / "revision_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_path(campaign_dir: Path, job_id: str) -> Path:
    return jobs_dir(campaign_dir) / f"{job_id}.json"


def save_job(campaign_dir: Path, job: RevisionJob) -> Path:
    job.updated_at = datetime.now(timezone.utc).isoformat()
    return atomic_write_json(job_path(campaign_dir, job.job_id), job.as_dict())


def load_job(campaign_dir: Path, job_id: str) -> RevisionJob | None:
    data = load_json(job_path(campaign_dir, job_id), default=None)
    if not data:
        return None
    return RevisionJob.from_dict(data)


def active_job_for_version(campaign_dir: Path, version_key: str) -> RevisionJob | None:
    folder = jobs_dir(campaign_dir)
    newest: RevisionJob | None = None
    for path in sorted(folder.glob("*.json"), reverse=True):
        data = load_json(path, default=None) or {}
        if data.get("version_key") != version_key:
            continue
        job = RevisionJob.from_dict(data)
        if job.status in {"ready", "failed", "cancelled"}:
            if newest is None:
                newest = job
            continue
        return job
    return newest


def classify_revision_feedback(feedback: str) -> RevisionCategory:
    """Map natural language to a revision category. Extends Studio parse intents."""
    text = (feedback or "").strip().lower()
    structured = parse_revision_request(feedback)
    intents = set(structured.get("intents") or [])

    if any(
        w in text
        for w in (
            "verbiage",
            "wording",
            "words",
            "language",
            "phrase",
            "hook",
            "copy",
            "text",
            "caption",
            "title",
            "headline",
            "cta",
        )
    ) or "adjust_copy_rerender" in intents:
        if "caption" in text or "description" in text or "metadata" in text:
            return "caption"
        return "copy"
    if "logo" in text:
        return "logo"
    if any(w in text for w in ("warm", "cool", "color", "grade", "grain", "contrast", "dark", "bright")):
        return "color"
    if any(w in text for w in ("pace", "rushed", "fast", "slow", "timing")):
        return "pacing"
    if any(w in text for w in ("crop", "format", "aspect", "framing")):
        return "crop"
    if any(w in text for w in ("footage", "clip", "shot", "visual", "image")):
        return "visual_selection"
    if "audio" in text or "sound" in text or "music" in text:
        return "audio"
    if "type" in text or "font" in text:
        return "typography"
    if "sequence" in text or "order" in text:
        return "sequencing"
    if "on brand" in text or "brand" in text or "everything" in text:
        return "creative_direction"
    if intents:
        if any(i.endswith("_rerender") for i in intents):
            return "copy"
        return "color"
    return "unsupported"


def _overlay_from_settings(render_folder: Path) -> dict[str, Any]:
    settings = load_json(render_folder / "render_settings.json", default={}) or {}
    production = settings.get("production") or {}
    template = production.get("template") or {}
    hook = template.get("hook") or {}
    supporting = template.get("supporting") or {}
    cta = template.get("cta") or {}
    lines = hook.get("lines") if isinstance(hook, dict) else None
    support_lines = supporting.get("lines") if isinstance(supporting, dict) else None
    return {
        "hook": list(lines or []),
        "supporting": list(support_lines or []),
        "cta": (cta.get("text") if isinstance(cta, dict) else "") or "",
        "footer": list(((template.get("footer") or {}).get("lines") or [])),
    }


def _original_hook(render_folder: Path) -> str:
    overlay = _overlay_from_settings(render_folder)
    hook = overlay.get("hook") or []
    if isinstance(hook, list) and hook:
        return str(hook[0])
    return str(hook or "")


def propose_copy_revision(
    *,
    feedback: str,
    original: str,
    campaign_goal: str = "",
    brand_id: str = DEFAULT_BRAND_ID,
) -> tuple[str, str]:
    """Return (proposed_copy, why). Prefer Brand Guide voice; works offline."""
    brand_text, loaded, _ = load_brand_guide(brand_id)
    if not loaded:
        raise RuntimeError("Brand Guide could not be loaded; revision requires brand authority.")

    # Deterministic, brand-aligned rewrite for recognition-first campaigns.
    # Prefer quieter recognition language over generic aspiration.
    goal = (campaign_goal or "").lower()
    if "waitlist" in goal or "reading" in goal:
        proposed = "The reading hour was already yours."
        why = (
            "The revision keeps the recognition-based idea while making the language "
            "quieter and more specific to the campaign."
        )
    else:
        # Soften / shorten original without inventing claims.
        proposed = re.sub(r"\s+", " ", (original or "").strip())
        proposed = proposed.replace("You've been", "You have been")
        if len(proposed) > 60:
            proposed = proposed.split(".")[0].strip() + "."
        if proposed.lower() == (original or "").strip().lower():
            proposed = "This already feels like yours."
        why = "The revision simplifies the line toward recognition and restraint."

    # Optional LLM enrichment when available — never required for the pipeline.
    try:
        from services.llm import complete_json
        from services.em_dash import rewrite_em_dashes

        payload = complete_json(
            system=(
                "Rewrite one on-screen hook for Oh Betty Jaletti. Return JSON with keys "
                "proposed and why. Recognition over aspiration. No em dashes. No scarcity."
            ),
            user=(
                f"Feedback: {feedback}\nOriginal: {original}\nGoal: {campaign_goal}\n"
                f"Brand excerpts:\n{brand_text[:2500]}"
            ),
        )
        if isinstance(payload, dict) and payload.get("proposed"):
            proposed = rewrite_em_dashes(str(payload["proposed"]).strip().strip('"'))
            why = str(payload.get("why") or why)
    except Exception:
        pass

    from services.em_dash import rewrite_em_dashes
    from services.revision_validation import REJECTED, validate_option

    proposed = rewrite_em_dashes(proposed)
    verdict = validate_option(proposed, brand_guide=brand_text)
    if getattr(verdict, "verdict", None) == REJECTED or not getattr(verdict, "can_apply", True):
        # Fall back to the deterministic recognition line.
        proposed = "The reading hour was already yours."
        why = (
            "The revision keeps the recognition-based idea while making the language "
            "quieter and more specific to the campaign."
        )
    return proposed, why


def build_revision_plan(
    *,
    feedback: str,
    render_folder: Path,
    campaign_goal: str = "",
    brand_id: str = DEFAULT_BRAND_ID,
) -> RevisionPlan:
    category = classify_revision_feedback(feedback)
    original = _original_hook(render_folder)
    if category in {"copy", "caption", "creative_direction"}:
        proposed, why = propose_copy_revision(
            feedback=feedback,
            original=original,
            campaign_goal=campaign_goal,
            brand_id=brand_id,
        )
        return RevisionPlan(
            category="copy",
            summary_lines=[
                "Rewrite the opening on-screen hook",
                "Preserve the current footage and pacing",
                "Apply the Oh Betty Jaletti voice",
                "Re-render the reel with the revised typography",
            ],
            field_key="overlay_hook",
            field_label="Opening on-screen hook",
            original_copy=original,
            proposed_copy=proposed,
            why_changed=why,
        )
    if category == "color":
        return RevisionPlan(
            category="color",
            summary_lines=[
                "Adjust color and finishing from your note",
                "Preserve footage selection and on-screen copy",
                "Create a new finished version",
            ],
            original_copy=original,
            proposed_copy=original,
        )
    if category == "logo":
        return RevisionPlan(
            category="logo",
            summary_lines=[
                "Adjust logo / brand treatment",
                "Preserve footage and copy",
            ],
            original_copy=original,
            proposed_copy=original,
        )
    return RevisionPlan(
        category=category,
        summary_lines=[
            "Interpret the feedback and propose a supported change",
            "Create a new immutable version when possible",
        ],
        original_copy=original,
        proposed_copy=original,
        why_changed="This request may need a supported advanced path.",
    )


def start_revision_job(
    *,
    campaign_dir: Path,
    version_key: str,
    finish_version_id: str | None,
    feedback: str,
    render_folder: Path,
    campaign_goal: str = "",
    brand_id: str = DEFAULT_BRAND_ID,
) -> RevisionJob:
    """Create one idempotent job for this feedback on this version."""
    existing = active_job_for_version(campaign_dir, version_key)
    if existing and existing.is_active and existing.feedback.strip() == feedback.strip():
        return existing
    if (
        existing
        and existing.awaiting_confirmation
        and existing.feedback.strip() == feedback.strip()
    ):
        return existing

    now = datetime.now(timezone.utc).isoformat()
    job = RevisionJob(
        job_id=f"rev_{uuid4().hex[:12]}",
        campaign_id=campaign_dir.name,
        version_key=version_key,
        finish_version_id=finish_version_id,
        feedback=feedback.strip(),
        status="interpreting",
        phase_label=PHASE_LABELS["interpreting"],
        created_at=now,
        updated_at=now,
    )
    save_job(campaign_dir, job)

    try:
        plan = build_revision_plan(
            feedback=feedback,
            render_folder=render_folder,
            campaign_goal=campaign_goal,
            brand_id=brand_id,
        )
        job.plan = plan
        job.status = "awaiting_plan_confirmation"
        job.phase_label = PHASE_LABELS["awaiting_plan_confirmation"]
        save_job(campaign_dir, job)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.phase_label = PHASE_LABELS["failed"]
        job.error = str(exc).splitlines()[-1]
        save_job(campaign_dir, job)
    return job


def update_plan_copy(campaign_dir: Path, job: RevisionJob, proposed_copy: str) -> RevisionJob:
    if job.plan is None:
        return job
    job.plan.proposed_copy = proposed_copy.strip()
    save_job(campaign_dir, job)
    return job


def execute_revision_job(
    *,
    campaign_dir: Path,
    job: RevisionJob,
    version,
    active,
    brand_id: str = DEFAULT_BRAND_ID,
    campaign_goal: str = "",
    platform: str = "Instagram",
    progress=None,
) -> RevisionJob:
    """Rebuild media for an accepted plan. Creates a new immutable version."""
    from services.brand_compliance import evaluate_brand_compliance
    from studio.service import generate_best_edit, revise_best_edit, send_to_review
    from studio.versions import render_version_id

    def report(msg: str) -> None:
        if progress:
            progress(msg)

    if job.plan is None:
        job.status = "failed"
        job.error = "Revision plan is missing."
        job.phase_label = PHASE_LABELS["failed"]
        save_job(campaign_dir, job)
        return job

    try:
        new_render: Path | None = None
        render_version_number = int(version.version)
        parent_finish = job.finish_version_id or (
            active.finish_version_id if active is not None else None
        )

        if job.plan.category in {"copy", "caption", "creative_direction"}:
            job.status = "rewriting_copy"
            job.phase_label = PHASE_LABELS["rewriting_copy"]
            save_job(campaign_dir, job)
            report(PHASE_LABELS["rewriting_copy"])

            job.status = "rebuilding"
            job.phase_label = PHASE_LABELS["rebuilding"]
            save_job(campaign_dir, job)
            report(PHASE_LABELS["rebuilding"])
            new_render = _rebuild_reel_with_hook(
                version.folder,
                proposed_hook=job.plan.proposed_copy,
                job_id=job.job_id,
            )
            job.new_render_path = str(new_render)
            match = re.search(r"_v(\d+)\.mp4$", new_render.name)
            if match:
                render_version_number = int(match.group(1))
            job.new_render_version = render_version_number
            job.new_version_key = (
                f"{version.template_id}|{version.piece_id or '-'}|v{render_version_number}"
            )
            job.what_changed = [
                "Rewrote the opening hook",
                "Preserved the footage and pacing",
                "Re-rendered the on-screen typography",
                "Rechecked the asset against the Brand Guide",
            ]

            job.status = "finishing"
            job.phase_label = PHASE_LABELS["finishing"]
            save_job(campaign_dir, job)
            report(PHASE_LABELS["finishing"])

            outcome = generate_best_edit(
                render_folder=version.folder,
                campaign_id=campaign_dir.name,
                content_piece_id=version.piece_id,
                template_id=version.template_id,
                parent_render_version_id=render_version_id(render_version_number),
                parent_finish_version_id=parent_finish,
                source_file=Path(new_render),
                brand_id=brand_id,
                platform=platform,
                campaign_goal=campaign_goal,
                overlay_copy=job.plan.proposed_copy,
                progress=report,
                revision_note=job.feedback,
            )
        elif job.plan.category in {"color", "logo"}:
            job.status = "finishing"
            job.phase_label = PHASE_LABELS["finishing"]
            save_job(campaign_dir, job)
            report(PHASE_LABELS["finishing"])
            if not parent_finish:
                raise RuntimeError("No finished version to revise.")
            outcome = revise_best_edit(
                render_folder=version.folder,
                finish_version_id=parent_finish,
                revision_note=job.feedback,
                brand_id=brand_id,
                platform=platform,
                campaign_goal=campaign_goal,
                progress=report,
            )
            job.what_changed = [
                "Adjusted finishing from your note",
                "Preserved footage and on-screen copy",
                "Created a new finished version",
                "Rechecked the asset against the Brand Guide",
            ]
            job.new_version_key = version.key
            job.new_render_version = version.version
        else:
            raise RuntimeError(
                "This feedback needs a supported advanced path. "
                "Copy, color, and logo revisions are available from Decide."
            )

        if not outcome.get("ok"):
            raise RuntimeError(str(outcome.get("error") or "Finish failed."))

        record = outcome.get("record")
        if record is None:
            raise RuntimeError("Revision finish record was not created.")
        send_to_review(version.folder, record.finish_version_id)
        job.new_finish_version_id = record.finish_version_id

        job.status = "brand_check"
        job.phase_label = PHASE_LABELS["brand_check"]
        save_job(campaign_dir, job)
        report(PHASE_LABELS["brand_check"])

        from ui.decide_media import resolve_decide_media

        # Build a lightweight version stub so finish parent matching uses the new render id.
        media_version = version
        if job.new_render_version and job.new_render_version != version.version:
            from dataclasses import replace

            try:
                media_version = replace(version, version=int(job.new_render_version))
            except TypeError:
                media_version = version

        media = resolve_decide_media(media_version, record)
        expects_video = str(getattr(version, "kind", "")) == "video" or (
            media.canonical is not None and media.canonical.suffix.lower() in {".mp4", ".mov"}
        )
        report_brand = evaluate_brand_compliance(
            brand_id=brand_id,
            copy_text=job.plan.proposed_copy or job.plan.original_copy,
            media_path=media.canonical,
            expects_video=expects_video,
        )
        job.brand_check = report_brand.as_dict()
        if report_brand.blocking:
            job.status = "failed"
            job.error = (
                "Brand Check blocked this revision. "
                "The original approved version remains the campaign canonical."
            )
            job.phase_label = PHASE_LABELS["failed"]
            save_job(campaign_dir, job)
            return job

        job.status = "ready"
        job.phase_label = PHASE_LABELS["ready"]
        save_job(campaign_dir, job)
        return job
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.phase_label = PHASE_LABELS["failed"]
        job.error = str(exc).splitlines()[-1]
        save_job(campaign_dir, job)
        return job


def _rebuild_reel_with_hook(render_folder: Path, *, proposed_hook: str, job_id: str) -> Path:
    """Create a new immutable reel MP4 with revised on-screen hook."""
    from main import run_create_ritual_reel
    from review.versioning import ensure_baseline_version, next_version_number

    ensure_baseline_version(render_folder)
    settings = load_json(render_folder / "render_settings.json", default={}) or {}
    production = settings.get("production") or {}
    template = production.get("template") or {}
    overlay = _overlay_from_settings(render_folder)
    overlay["hook"] = [proposed_hook]

    clips = settings.get("clips") or template.get("sources") or []
    source_overrides = []
    for clip in clips:
        rel = clip.get("path") or clip.get("relative_path")
        if not rel:
            continue
        source_overrides.append(
            {
                "relative_path": rel,
                "target_duration_seconds": clip.get("target_duration_seconds")
                or (clip.get("segment") or {}).get("output_duration_seconds"),
            }
        )

    version = next_version_number(render_folder)
    video_name = f"cinematic_multi_clip_reel_v{version}.mp4"
    run_create_ritual_reel(
        out_dir=render_folder,
        source_overrides=source_overrides or None,
        target_duration_seconds=(template.get("target_duration_seconds") or 15.0),
        cta_appear_at_seconds=(settings.get("resolved") or {}).get("cta_appear_at_seconds") or 10.0,
        overlay_copy_overrides=overlay,
        output_filename=video_name,
        preserve_existing=True,
        versioning={
            "version": version,
            "parent_version": version - 1 if version > 1 else 1,
            "revision_request_ids": [job_id],
            "addressed_recommendation_ids": [],
        },
    )
    output = render_folder / video_name
    if not output.is_file():
        raise RuntimeError(f"Revised reel was not written: {video_name}")
    return output


def recover_stale_jobs(campaign_dir: Path, *, max_age_seconds: int = 1800) -> list[RevisionJob]:
    """Mark long-running jobs as failed so the UI cannot stay active forever."""
    recovered: list[RevisionJob] = []
    now = datetime.now(timezone.utc)
    for path in jobs_dir(campaign_dir).glob("*.json"):
        job = load_job(campaign_dir, path.stem)
        if job is None or not job.is_active:
            continue
        try:
            updated = datetime.fromisoformat(job.updated_at.replace("Z", "+00:00"))
        except Exception:
            updated = now
        if (now - updated).total_seconds() > max_age_seconds:
            job.status = "failed"
            job.phase_label = PHASE_LABELS["failed"]
            job.error = "This revision stopped unexpectedly. Your feedback is preserved — retry when ready."
            save_job(campaign_dir, job)
            recovered.append(job)
    return recovered
