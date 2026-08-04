"""Continue Campaign resolver — one next action for the active campaign.

Derives from `build_campaign_state()` so Today, Campaigns, and the workspace
never disagree with the backend. Does not invent a second workflow model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ui.campaign_state import (
    CampaignState,
    finish_records_for_version,
    finished_versions_sent_to_review,
)


# Founder-facing Today states (internal keys stay stable).
NO_ACTIVE_CAMPAIGN = "no_active_campaign"
CAMPAIGN_NEEDS_BRIEF = "campaign_needs_brief"
CONTENT_PLAN_READY = "content_plan_ready"
HUMAN_INPUT_REQUIRED = "human_input_required"
READY_TO_CREATE = "ready_to_create"
PROCESSING = "processing"
DRAFT_READY = "draft_ready"
REVISION_NEEDED = "revision_needed"
AWAITING_APPROVAL = "awaiting_approval"
READY_TO_EXPORT = "ready_to_export"
COMPLETE = "complete"
BLOCKED = "blocked"

# Workspace progression shown to the user.
WORKSPACE_STAGES: tuple[tuple[str, str], ...] = (
    ("brief", "Brief"),
    ("plan", "Plan"),
    ("capture", "Capture"),
    ("create", "Create"),
    ("decide", "Decide"),
    ("deliver", "Deliver"),
)

# Map Today state → workspace stage key.
_STATE_TO_WORKSPACE = {
    NO_ACTIVE_CAMPAIGN: "brief",
    CAMPAIGN_NEEDS_BRIEF: "brief",
    CONTENT_PLAN_READY: "plan",
    HUMAN_INPUT_REQUIRED: "capture",
    READY_TO_CREATE: "create",
    PROCESSING: "create",
    DRAFT_READY: "decide",
    REVISION_NEEDED: "decide",
    AWAITING_APPROVAL: "decide",
    READY_TO_EXPORT: "deliver",
    COMPLETE: "deliver",
    BLOCKED: "capture",
}

# Founder-facing campaign stage labels (replaces pipeline jargon in the UI).
FOUNDER_CAMPAIGN_LABELS = {
    NO_ACTIVE_CAMPAIGN: "Planning",
    CAMPAIGN_NEEDS_BRIEF: "Planning",
    CONTENT_PLAN_READY: "Planning",
    HUMAN_INPUT_REQUIRED: "Waiting for Footage",
    READY_TO_CREATE: "Creating",
    PROCESSING: "Creating",
    DRAFT_READY: "Ready for Review",
    REVISION_NEEDED: "Revising",
    AWAITING_APPROVAL: "Ready for Approval",
    READY_TO_EXPORT: "Ready to Deliver",
    COMPLETE: "Complete",
    BLOCKED: "Blocked",
}


@dataclass(frozen=True)
class PrimaryAction:
    label: str
    destination: str  # Today nav destination or "workspace"
    stage: str | None = None  # workspace stage key
    tab: str | None = None  # legacy/advanced tab when needed
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SecondaryAction:
    label: str
    destination: str
    stage: str | None = None
    tab: str | None = None


@dataclass(frozen=True)
class CampaignContinuation:
    """Resolved next move for the active campaign."""

    campaign_id: str | None
    campaign_name: str
    current_state: str
    current_stage: str  # workspace stage key
    founder_stage_label: str
    headline: str
    message: str
    why: str
    required_from_user: list[str]
    estimated_effort: str
    aftermath: str
    primary_action: PrimaryAction
    secondary_actions: list[SecondaryAction]
    blockers: list[str]
    confidence: float
    focus_version_key: str | None = None
    focus_piece_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "current_state": self.current_state,
            "current_stage": self.current_stage,
            "founder_stage_label": self.founder_stage_label,
            "headline": self.headline,
            "message": self.message,
            "why": self.why,
            "required_from_user": list(self.required_from_user),
            "estimated_effort": self.estimated_effort,
            "aftermath": self.aftermath,
            "primary_action": {
                "label": self.primary_action.label,
                "destination": self.primary_action.destination,
                "stage": self.primary_action.stage,
                "tab": self.primary_action.tab,
                "context": dict(self.primary_action.context),
            },
            "secondary_actions": [
                {
                    "label": a.label,
                    "destination": a.destination,
                    "stage": a.stage,
                    "tab": a.tab,
                }
                for a in self.secondary_actions
            ],
            "blockers": list(self.blockers),
            "confidence": self.confidence,
            "focus_version_key": self.focus_version_key,
            "focus_piece_id": self.focus_piece_id,
        }


def resolve_continuation(state: CampaignState) -> CampaignContinuation:
    """Derive the single next action from persisted campaign state."""
    if not state.exists or state.path is None:
        return _no_campaign()

    campaign_id = state.path.name
    name = state.name
    blockers = list(state.blockers)
    counts = state.counts
    revisions = state.revision_counts

    # Hard blockers that prevent ordinary progress.
    if _is_hard_blocked(state):
        return _blocked(state, campaign_id, name, blockers)

    if _needs_brief(state):
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=CAMPAIGN_NEEDS_BRIEF,
            headline="I need a clear campaign goal before I can plan the work.",
            message="Set the outcome you want, and I will recommend what to make.",
            why="Without a goal, every content direction is equally weak.",
            required=["A short campaign goal"],
            effort="2 minutes",
            aftermath="I will draft today’s content plan from your goal and available media.",
            primary=PrimaryAction("Set Campaign Goal", "workspace", stage="brief"),
            secondary=[
                SecondaryAction("View campaign", "Campaigns"),
            ],
            blockers=blockers,
            confidence=0.95,
        )

    if not state.pieces:
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=CAMPAIGN_NEEDS_BRIEF,
            headline="This campaign has no content plan yet.",
            message="I need campaign content before I can recommend a draft.",
            why="A campaign without planned pieces has nothing to create or review.",
            required=["Campaign content plan"],
            effort="A few minutes",
            aftermath="I will propose the strongest content direction for your goal.",
            primary=PrimaryAction("Start Planning", "workspace", stage="brief"),
            secondary=[SecondaryAction("View campaign", "Campaigns")],
            blockers=blockers,
            confidence=0.9,
        )

    missing_pieces = [p for p in state.pieces if p.status_key == "missing_inputs"]
    ready_pieces = [p for p in state.pieces if p.status_key == "ready_to_render"]
    focus_piece = missing_pieces[0] if missing_pieces else (ready_pieces[0] if ready_pieces else state.pieces[0])

    if missing_pieces and not state.versions:
        required = _shot_list_for(missing_pieces[0])
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=HUMAN_INPUT_REQUIRED,
            headline="I need footage before I can continue.",
            message=_capture_message(missing_pieces[0], required),
            why=(
                f"{missing_pieces[0].record.title} is the strongest next piece, "
                "but its source media is not available yet."
            ),
            required=required,
            effort=_estimate_capture(required),
            aftermath="Once the footage is in, I will create the best draft automatically.",
            primary=PrimaryAction(
                "View Shot List",
                "workspace",
                stage="capture",
                context={"piece_id": missing_pieces[0].record.piece_id},
            ),
            secondary=[
                SecondaryAction("Review Today’s Plan", "workspace", stage="plan"),
                SecondaryAction("Change priority", "Campaigns"),
            ],
            blockers=blockers,
            confidence=0.88,
            focus_piece_id=missing_pieces[0].record.piece_id,
        )

    if not state.versions and ready_pieces:
        title = ready_pieces[0].record.title
        platform = ready_pieces[0].record.platform or "your primary platform"
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=READY_TO_CREATE,
            headline="I have everything needed to create the draft.",
            message=f"Create one {platform}-first draft for {title}.",
            why=(
                "Source media is in place and a supported template is assigned. "
                "I can select, edit, finish, and review without further setup."
            ),
            required=[],
            effort="A few minutes of processing",
            aftermath="I will present one finished draft for your judgment.",
            primary=PrimaryAction(
                "Create Best Draft",
                "workspace",
                stage="create",
                context={"piece_id": ready_pieces[0].record.piece_id},
            ),
            secondary=[
                SecondaryAction("Review plan", "workspace", stage="plan"),
                SecondaryAction("View campaign", "Campaigns"),
            ],
            blockers=blockers,
            confidence=0.9,
            focus_piece_id=ready_pieces[0].record.piece_id,
        )

    if not state.versions and not ready_pieces:
        # Content exists but nothing can render yet — usually unsupported or plan-only.
        if any(p.status_key == "unsupported" for p in state.pieces):
            return _blocked(
                state,
                campaign_id,
                name,
                blockers
                or [
                    "I selected a concept the current templates cannot produce. "
                    "I can adapt it to a supported format."
                ],
            )
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=CONTENT_PLAN_READY,
            headline="I planned the strongest content direction for this campaign.",
            message="Review today’s plan, then we will gather what is needed to create.",
            why="The plan is ready, but nothing is queued to create yet.",
            required=[],
            effort="3 minutes",
            aftermath="Accepting the plan moves us to capture or create.",
            primary=PrimaryAction("Review Today’s Plan", "workspace", stage="plan"),
            secondary=[SecondaryAction("Edit campaign goal", "workspace", stage="brief")],
            blockers=blockers,
            confidence=0.85,
            focus_piece_id=focus_piece.record.piece_id,
        )

    # Revisions waiting to apply take priority over fresh review.
    if revisions.get("ready_to_apply", 0) > 0 or revisions.get("applying", 0) > 0:
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=REVISION_NEEDED,
            headline="I can address the requested changes.",
            message="A requested change is ready to apply as a new immutable version.",
            why="You asked for a revision, and the change is supported.",
            required=[],
            effort="A few minutes of processing",
            aftermath="I will return the revised draft for your decision.",
            primary=PrimaryAction("Apply Revision", "workspace", stage="decide"),
            secondary=[SecondaryAction("View Version History", "workspace", stage="decide")],
            blockers=blockers,
            confidence=0.87,
        )

    if revisions.get("awaiting_decision", 0) > 0:
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=REVISION_NEEDED,
            headline="I need your direction on a requested change.",
            message="Choose how I should revise the draft, or write natural-language feedback.",
            why="A change is open and waiting on your preference.",
            required=["A short note on what should change"],
            effort="2 minutes",
            aftermath="I will apply a supported revision and return a new version.",
            primary=PrimaryAction("Request Changes", "workspace", stage="decide"),
            secondary=[SecondaryAction("Review draft", "workspace", stage="decide")],
            blockers=blockers,
            confidence=0.84,
        )

    draft = _best_draft_for_review(state)
    if draft is not None:
        version, finish = draft
        title = state.piece_title(version) or version.display_name
        why = _draft_why(finish, state=state, title=title, version=version)
        headline_name = _campaign_hint(state, title) or title
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=DRAFT_READY,
            headline=f"Your {headline_name} draft is ready.",
            message="",
            why=why,
            required=[],
            effort="About 3 minutes to review",
            aftermath="Approve to prepare delivery, or ask for a revision.",
            primary=PrimaryAction(
                "Review Draft",
                "workspace",
                stage="decide",
                context={
                    "version_key": version.key,
                    "finish_version_id": finish.finish_version_id if finish else None,
                },
            ),
            secondary=[
                SecondaryAction("Not today", "Today"),
            ],
            blockers=blockers,
            confidence=0.91,
            focus_version_key=version.key,
            focus_piece_id=version.piece_id,
        )

    needs_rev = [v for v in state.versions if v.approval_status == "needs_revision" and v.is_latest]
    if needs_rev:
        version = needs_rev[0]
        title = state.piece_title(version) or version.display_name
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=REVISION_NEEDED,
            headline=f"I can revise {title}.",
            message="Tell me what feels off in plain language, and I will create a new version.",
            why="This draft was marked for revision and is waiting on your feedback.",
            required=["Natural-language feedback"],
            effort="2 minutes to write; a few minutes to apply",
            aftermath="I will return a revised draft for approval.",
            primary=PrimaryAction(
                "Apply Revision",
                "workspace",
                stage="decide",
                context={"version_key": version.key},
            ),
            secondary=[SecondaryAction("Review draft", "workspace", stage="decide")],
            blockers=blockers,
            confidence=0.86,
            focus_version_key=version.key,
            focus_piece_id=version.piece_id,
        )

    awaiting = [v for v in state.versions if v.approval_status == "awaiting_review" and v.is_latest]
    if awaiting and _campaign_has_finish(state):
        version = awaiting[0]
        title = state.piece_title(version) or version.display_name
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=AWAITING_APPROVAL,
            headline="The draft is ready for your decision.",
            message=f"Approve {title}, request changes, or reject it.",
            why="A finished draft is waiting. Export only uses versions you approve.",
            required=["Your decision"],
            effort="2 minutes",
            aftermath="Approval unlocks the publishing package.",
            primary=PrimaryAction(
                "Approve or Request Changes",
                "workspace",
                stage="decide",
                context={"version_key": version.key},
            ),
            secondary=[SecondaryAction("View campaign", "Campaigns")],
            blockers=blockers,
            confidence=0.89,
            focus_version_key=version.key,
            focus_piece_id=version.piece_id,
        )

    if awaiting and not _campaign_has_finish(state):
        version = awaiting[0]
        title = state.piece_title(version) or version.display_name
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=READY_TO_CREATE,
            headline="I have a render ready to finish.",
            message=f"Create the best finished draft for {title}.",
            why="A draft render exists, but finishing and Creative Director Review have not run yet.",
            required=[],
            effort="A few minutes of processing",
            aftermath="I will present one finished draft for your judgment.",
            primary=PrimaryAction(
                "Create Best Draft",
                "workspace",
                stage="create",
                context={"version_key": version.key},
            ),
            secondary=[SecondaryAction("View plan", "workspace", stage="plan")],
            blockers=blockers,
            confidence=0.88,
            focus_version_key=version.key,
            focus_piece_id=version.piece_id,
        )

    if counts.get("approved", 0) > 0 and state.export_count == 0:
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=READY_TO_EXPORT,
            headline="The approved publishing package is ready.",
            message="Download the assets, caption, and publishing notes.",
            why="At least one version is approved and nothing has been packaged yet.",
            required=[],
            effort="Under a minute",
            aftermath="Your package downloads, and Today will recommend the next move.",
            primary=PrimaryAction("Download Package", "workspace", stage="deliver"),
            secondary=[
                SecondaryAction("View package contents", "workspace", stage="deliver"),
                SecondaryAction("All campaign decisions", "workspace", stage="decide"),
            ],
            blockers=blockers,
            confidence=0.93,
        )

    if counts.get("approved", 0) > 0 and state.export_count > 0:
        # More work remaining?
        if ready_pieces or missing_pieces:
            if missing_pieces:
                required = _shot_list_for(missing_pieces[0])
                return _continuation(
                    campaign_id=campaign_id,
                    name=name,
                    current_state=HUMAN_INPUT_REQUIRED,
                    headline="Your best next move is the next piece.",
                    message=_capture_message(missing_pieces[0], required),
                    why="One asset is already delivered. The campaign still has planned work waiting on footage.",
                    required=required,
                    effort=_estimate_capture(required),
                    aftermath="I will create the next draft once footage is available.",
                    primary=PrimaryAction(
                        "View Shot List",
                        "workspace",
                        stage="capture",
                        context={"piece_id": missing_pieces[0].record.piece_id},
                    ),
                    secondary=[
                        SecondaryAction("Download package again", "workspace", stage="deliver"),
                        SecondaryAction("View campaign", "Campaigns"),
                    ],
                    blockers=blockers,
                    confidence=0.82,
                    focus_piece_id=missing_pieces[0].record.piece_id,
                )
            title = ready_pieces[0].record.title
            return _continuation(
                campaign_id=campaign_id,
                name=name,
                current_state=READY_TO_CREATE,
                headline="Your best next move is another draft.",
                message=f"Create the next draft for {title}.",
                why="Prior work is delivered. Remaining pieces are ready to create.",
                required=[],
                effort="A few minutes of processing",
                aftermath="I will present the next finished draft.",
                primary=PrimaryAction(
                    "Create Best Draft",
                    "workspace",
                    stage="create",
                    context={"piece_id": ready_pieces[0].record.piece_id},
                ),
                secondary=[SecondaryAction("Download last package", "workspace", stage="deliver")],
                blockers=blockers,
                confidence=0.84,
                focus_piece_id=ready_pieces[0].record.piece_id,
            )
        return _continuation(
            campaign_id=campaign_id,
            name=name,
            current_state=COMPLETE,
            headline="This campaign’s approved work is delivered.",
            message="Nothing urgent is waiting. Start a new campaign or revisit the library.",
            why="Approved assets have been packaged and no open pieces need attention.",
            required=[],
            effort="—",
            aftermath="Starting a new campaign gives me a fresh brief to plan from.",
            primary=PrimaryAction("Start a Campaign", "Campaigns"),
            secondary=[
                SecondaryAction("Download package again", "workspace", stage="deliver"),
                SecondaryAction("Open Insights", "Insights"),
            ],
            blockers=blockers,
            confidence=0.8,
        )

    # Fallback: plan review
    return _continuation(
        campaign_id=campaign_id,
        name=name,
        current_state=CONTENT_PLAN_READY,
        headline="Continue this campaign.",
        message=state.next_step.reason or "Review the plan and take the next clear step.",
        why="I derived the next move from the campaign’s current state.",
        required=[],
        effort="A few minutes",
        aftermath="I will keep moving the campaign forward after you respond.",
        primary=PrimaryAction("Continue", "workspace", stage=_workspace_for_legacy(state)),
        secondary=[SecondaryAction("View campaign", "Campaigns")],
        blockers=blockers,
        confidence=0.7,
        focus_piece_id=focus_piece.record.piece_id if state.pieces else None,
    )


def workspace_stage_for(continuation: CampaignContinuation) -> str:
    return continuation.current_stage


def founder_label_for_state(current_state: str) -> str:
    return FOUNDER_CAMPAIGN_LABELS.get(current_state, "Planning")


# --- internals --------------------------------------------------------------

def _continuation(
    *,
    campaign_id: str | None,
    name: str,
    current_state: str,
    headline: str,
    message: str,
    why: str,
    required: list[str],
    effort: str,
    aftermath: str,
    primary: PrimaryAction,
    secondary: list[SecondaryAction],
    blockers: list[str],
    confidence: float,
    focus_version_key: str | None = None,
    focus_piece_id: str | None = None,
) -> CampaignContinuation:
    stage = _STATE_TO_WORKSPACE.get(current_state, "plan")
    return CampaignContinuation(
        campaign_id=campaign_id,
        campaign_name=name,
        current_state=current_state,
        current_stage=stage,
        founder_stage_label=founder_label_for_state(current_state),
        headline=headline,
        message=message,
        why=why,
        required_from_user=required,
        estimated_effort=effort,
        aftermath=aftermath,
        primary_action=primary,
        secondary_actions=secondary,
        blockers=blockers,
        confidence=confidence,
        focus_version_key=focus_version_key,
        focus_piece_id=focus_piece_id,
    )


def _no_campaign() -> CampaignContinuation:
    return _continuation(
        campaign_id=None,
        name="No campaign",
        current_state=NO_ACTIVE_CAMPAIGN,
        headline="There is no active campaign.",
        message="Start a campaign and I will recommend the next move.",
        why="BettyOS plans and creates inside a campaign.",
        required=["A campaign goal and available media"],
        effort="5 minutes to begin",
        aftermath="I will propose the strongest content direction for your goal.",
        primary=PrimaryAction("Start a Campaign", "Campaigns"),
        secondary=[SecondaryAction("Open Library", "Library")],
        blockers=[],
        confidence=1.0,
    )


def _blocked(
    state: CampaignState,
    campaign_id: str,
    name: str,
    blockers: list[str],
) -> CampaignContinuation:
    detail = blockers[0] if blockers else "Something must be resolved before I can continue."
    return _continuation(
        campaign_id=campaign_id,
        name=name,
        current_state=BLOCKED,
        headline="I cannot continue until this is resolved.",
        message=detail,
        why="The campaign is blocked by a missing capability, asset, or configuration.",
        required=[detail],
        effort="Depends on the blocker",
        aftermath="Once resolved, I will resume at the correct stage.",
        primary=PrimaryAction("Resolve Blocker", "workspace", stage="capture"),
        secondary=[
            SecondaryAction("Open Settings", "Settings"),
            SecondaryAction("View campaign", "Campaigns"),
        ],
        blockers=blockers,
        confidence=0.95,
    )


def _needs_brief(state: CampaignState) -> bool:
    goal = (state.goal or "").strip()
    return not goal or goal == "No goal recorded"


def _is_hard_blocked(state: CampaignState) -> bool:
    # API / FFmpeg blockers only hard-stop when the next work needs them.
    text = " ".join(state.blockers).lower()
    if "no api key" in text and not state.pieces:
        return True
    if "ffmpeg not found" in text:
        needs_video = any(
            p.template is not None and p.template.renderer_module == "video" and p.can_render
            for p in state.pieces
        )
        if needs_video and not state.versions:
            return True
    if state.stage == "blocked" and state.blockers:
        # Unsupported-only campaigns with no path forward.
        if state.pieces and all(p.status_key in {"unsupported", "missing_inputs"} for p in state.pieces):
            if all(p.status_key == "unsupported" for p in state.pieces):
                return True
    return False


def _shot_list_for(piece) -> list[str]:
    missing = list(piece.missing_inputs)
    if missing:
        # Prefer human filenames over "Missing file:" prefixes.
        cleaned: list[str] = []
        for item in missing:
            text = str(item)
            if text.startswith("Missing file:"):
                cleaned.append(text.replace("Missing file:", "").strip())
            elif text == "No source media selected":
                cleaned.append("Source footage for this piece")
            else:
                cleaned.append(text)
        return cleaned[:5]
    assets = list(piece.record.source_assets or [])
    if assets:
        from pathlib import Path

        return [Path(a).name for a in assets[:5]]
    return ["Source footage for this piece"]


def _capture_message(piece, required: list[str]) -> str:
    n = len(required)
    if n == 1:
        return f"I need one clip for {piece.record.title}."
    return f"I need {n} clips for {piece.record.title}."


def _estimate_capture(required: list[str]) -> str:
    n = max(1, len(required))
    minutes = min(20, 3 + n * 2)
    return f"About {minutes} minutes of filming"


def _campaign_has_finish(state: CampaignState) -> bool:
    for version in state.versions:
        if finish_records_for_version(version):
            return True
    return False


def _best_draft_for_review(state: CampaignState):
    """Prefer a Studio finish sent to review; else None.

    When several drafts await judgment, prefer the one with persisted creative
    decisions so Today can explain the recommendation specifically.
    """
    pairs = finished_versions_sent_to_review(state.versions)
    candidates: list[tuple] = []
    for version, record in pairs:
        finish_status = getattr(record, "approval_status", None)
        if version.approval_status in {"awaiting_review", "needs_revision"} and (
            finish_status in {"awaiting_review", "needs_revision", "", None}
            or finish_status == "awaiting_review"
        ):
            candidates.append((version, record))
    if not candidates:
        for version, record in pairs:
            if version.approval_status == "awaiting_review":
                candidates.append((version, record))
    if not candidates:
        return None

    def _richness(pair) -> tuple:
        _version, record = pair
        decision = record.edit_decision or {}
        majors = decision.get("major_decisions") or []
        return (
            1 if majors else 0,
            1 if decision.get("rationale") else 0,
            record.updated_at or record.created_at or "",
        )

    candidates.sort(key=_richness, reverse=True)
    return candidates[0]

def soft_attention_items(state: CampaignState, continuation: CampaignContinuation) -> list[dict[str, str]]:
    """Non-blocking issues for a quiet Today disclosure — never the primary card."""
    items: list[dict[str, str]] = []
    failed = int(state.revision_counts.get("failed") or 0)
    if failed:
        verb = "does" if failed == 1 else "do"
        items.append(
            {
                "title": "A requested change could not be applied",
                "detail": (
                    f"{failed} earlier revision {'attempt' if failed == 1 else 'attempts'} "
                    f"{verb} not affect this draft. You can still approve or request a new change."
                ),
                "blocks_approval": "No",
            }
        )
    # Soft blockers that do not stop reviewing an already-ready draft.
    if continuation.current_state in {DRAFT_READY, AWAITING_APPROVAL, READY_TO_EXPORT}:
        for blocker in continuation.blockers:
            lowered = blocker.lower()
            if "failed to apply" in lowered:
                continue  # covered above
            if "missing source media" in lowered or "no working template" in lowered:
                items.append(
                    {
                        "title": "Other campaign work still needs attention",
                        "detail": (
                            f"{blocker} That does not block reviewing the draft ready now."
                        ),
                        "blocks_approval": "No",
                    }
                )
    return items


def primary_blockers_for_display(continuation: CampaignContinuation) -> list[str]:
    """Hard blockers only — omit soft revision-failure noise from the main card."""
    if continuation.current_state != BLOCKED:
        return []
    return [
        b
        for b in continuation.blockers
        if "failed to apply" not in b.lower()
    ]


def _draft_why(
    finish,
    *,
    state: CampaignState | None = None,
    title: str = "",
    version=None,
) -> str:
    """Specific creative reason this draft is the recommendation — never generic filler."""
    decision = _resolve_edit_decision(finish, version)

    decisions = [
        str(x).strip()
        for x in (
            decision.get("major_decisions")
            or decision.get("major_decision_summaries")
            or decision.get("key_decisions")
            or []
        )
        if str(x).strip()
    ][:3]

    # When the decision record is thin, synthesize from finish configuration fields.
    if not decisions and finish is not None:
        decisions = _decisions_from_finish_config(finish)

    platform = ""
    if isinstance(decision.get("platform"), str):
        platform = _clean_platform(decision["platform"])
    if not platform and state and version is not None:
        for piece in state.pieces:
            if version.piece_id and piece.record.piece_id == version.piece_id:
                platform = _clean_platform(piece.record.platform or "")
                break
        if not platform and state.platforms:
            platform = _clean_platform(state.platforms[0])


    campaign_hint = _campaign_hint(state, title)

    logo = decision.get("logo_decision") or {}
    logo_omitted = False
    if isinstance(logo, dict):
        logo_omitted = str(logo.get("value") or "").lower() in {"omit", "omitted", "none"}
    elif isinstance(logo, str):
        logo_omitted = logo.lower() in {"omit", "omitted", "none"}
    if not logo_omitted and finish is not None:
        logo_omitted = _finish_omits_logo(finish)

    phrases = _humanize_decision_phrases(decisions, logo_omitted=logo_omitted)
    if phrases:
        joined = _join_phrases(phrases)
        if campaign_hint and platform:
            return (
                f"This is the strongest draft because {joined} — "
                f"it best matches the {campaign_hint} direction for {platform}."
            )
        if campaign_hint:
            return (
                f"This is the strongest draft because {joined}, "
                f"which best serves {campaign_hint}."
            )
        return f"This is the strongest draft because {joined}."

    rationale = str(decision.get("rationale") or "").strip()
    if rationale and not _is_generic_rationale(rationale):
        cleaned = rationale
        if cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        if not cleaned.endswith("."):
            cleaned += "."
        return cleaned

    if campaign_hint and platform:
        return (
            f"This is the strongest draft currently finished for {campaign_hint} on {platform} — "
            f"review the sequence and decide."
        )
    if campaign_hint:
        return (
            f"This finished draft is the strongest version prepared for {campaign_hint} — "
            f"review it and decide."
        )
    return "This finished draft is ready for your judgment."


def _resolve_edit_decision(finish, version=None) -> dict:
    """Load creative decision data from the finish, its sidecar, or parent finish."""
    if finish is None:
        return {}

    raw = getattr(finish, "edit_decision", None) or {}
    if isinstance(raw, dict) and (
        raw.get("major_decisions") or raw.get("rationale") or raw.get("logo_decision")
    ):
        return raw

    folder = None
    if version is not None:
        folder = getattr(version, "folder", None)
    if folder is None:
        folder = getattr(finish, "render_folder", None)

    finish_id = getattr(finish, "finish_version_id", None)
    if folder is not None and finish_id:
        from src.persistence import load_json
        from studio.paths import finish_version_dir
        from studio.versions import load_finish_record

        side = load_json(finish_version_dir(folder, finish_id) / "edit_decision.json", default={}) or {}
        if isinstance(side, dict) and (
            side.get("major_decisions") or side.get("rationale") or side.get("logo_decision")
        ):
            return side

        # Inherit from parent finished version when this one is a thin revision shell.
        parent_id = getattr(finish, "parent_finish_version_id", None)
        if parent_id:
            parent_record = load_finish_record(folder, str(parent_id))
            if parent_record is not None:
                parent_decision = parent_record.edit_decision or {}
                if isinstance(parent_decision, dict) and (
                    parent_decision.get("major_decisions") or parent_decision.get("rationale")
                ):
                    return parent_decision
            parent_side = load_json(
                finish_version_dir(folder, str(parent_id)) / "edit_decision.json",
                default={},
            ) or {}
            if isinstance(parent_side, dict) and (
                parent_side.get("major_decisions") or parent_side.get("rationale")
            ):
                return parent_side

    return raw if isinstance(raw, dict) else {}


def _decisions_from_finish_config(finish) -> list[str]:
    lines: list[str] = []
    recipe = getattr(finish, "recipe_id", None)
    if recipe:
        label = str(recipe).replace("_", " ").replace("obj ", "OBJ ").strip()
        lines.append(f"Color recipe: {label}")
    if _finish_omits_logo(finish):
        lines.append("Logo omitted to protect visual hierarchy")
    return lines


def _finish_omits_logo(finish) -> bool:
    logo = getattr(finish, "logo_configuration", None)
    if isinstance(logo, dict):
        role = str(logo.get("role") or "").lower()
        return role in {"", "none", "omit", "omitted"}
    if logo is not None:
        role = str(getattr(logo, "role", "") or "").lower()
        return role in {"", "none", "omit", "omitted"}
    return False


def _campaign_hint(state: CampaignState | None, title: str) -> str:
    if title and "reading hour" in title.lower():
        return "Reading Hour"
    if state and state.goal and state.goal != "No goal recorded":
        goal = state.goal
        if "reading hour" in goal.lower():
            return "Reading Hour"
        # Prefer a short readable cue over the full goal sentence.
        if title and not title.lower().startswith("cinematic"):
            return title
        return title or state.name
    return title


def _clean_platform(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    for name in ("Pinterest", "Instagram", "TikTok", "YouTube", "Email"):
        if name.lower() in lowered:
            return name
    # Drop geometry suffixes like "Feed (4:5)".
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def _is_generic_rationale(text: str) -> bool:
    lowered = text.lower()
    generics = (
        "i selected, finished, and reviewed the strongest available version",
        "one best finish for",
        "guided by the brand guide and production rules",
    )
    # "One best finish for X using Y" alone is too templated unless revision feedback follows.
    if "revised from feedback" in lowered:
        return False
    return any(g in lowered for g in generics[:1]) or (
        lowered.startswith("one best finish for") and "revised from feedback" not in lowered
    )


def _humanize_decision_phrases(decisions: list[str], *, logo_omitted: bool) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for raw in decisions:
        phrase = _humanize_one_decision(raw)
        key = phrase.lower()
        if not phrase or key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
    if logo_omitted and not any("logo" in p.lower() for p in phrases):
        phrases.append("the logo was omitted to protect the composition")
    return phrases[:3]


def _humanize_one_decision(raw: str) -> str:
    text = raw.strip().rstrip(".")
    lowered = text.lower()
    # Already conversational.
    if lowered.startswith(("i ", "the ", "a ", "an ")):
        return lowered
    if lowered.startswith("color recipe:"):
        name = text.split(":", 1)[-1].strip()
        return f"the {name} finish keeps the tone restrained" if name else "the color finish stays restrained"
    if "logo omitted" in lowered or lowered.startswith("logo omit"):
        return "the logo was omitted to protect visual hierarchy"
    if lowered.startswith("framed for"):
        target = text.split("framed for", 1)[-1].strip()
        return f"the frame is tuned for {target}" if target else "the frame is tuned for the platform"
    if "cta" in lowered and ("earlier" in lowered or "moved" in lowered):
        return "the CTA arrives earlier"
    if "pacing" in lowered or "tighter" in lowered or "clip" in lowered:
        return "the sequence is tighter"
    if "warm" in lowered or "cool" in lowered or "temperature" in lowered:
        return "the color cast was corrected"
    # Fallback: lowercase clause without sounding like a config key.
    if ":" in text:
        label, _, value = text.partition(":")
        value = value.strip()
        if value:
            return f"{label.strip().lower()} set to {value}"
    return text[0].lower() + text[1:] if text else text


def _join_phrases(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return f"{', '.join(phrases[:-1])}, and {phrases[-1]}"


def _workspace_for_legacy(state: CampaignState) -> str:
    dest = state.next_step.destination
    mapping = {
        "Campaigns": "brief",
        "Create": "create",
        "Studio": "create",
        "Review": "decide",
        "Revisions": "decide",
        "Approvals": "decide",
        "Export": "deliver",
        "Home": "plan",
        "Today": "plan",
    }
    return mapping.get(dest, "plan")
