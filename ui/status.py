"""One status vocabulary for the whole product.

Every status shown anywhere in BettyOS resolves through this module so that the
same underlying state always gets the same words and the same colour. Backend
files keep their own raw values; this layer maps them to product language.
"""

from __future__ import annotations

from dataclasses import dataclass

NEUTRAL = "neutral"
ACTIVE = "active"
POSITIVE = "positive"
ATTENTION = "attention"
BLOCKED = "blocked"


@dataclass(frozen=True)
class Status:
    key: str
    label: str
    tone: str
    meaning: str = ""


def _index(statuses: tuple[Status, ...]) -> dict[str, Status]:
    return {s.key: s for s in statuses}


# --- Campaign ---------------------------------------------------------------

CAMPAIGN_STATUSES: tuple[Status, ...] = (
    Status("planning", "Planning", NEUTRAL, "Brief captured, no content generated yet."),
    Status("creating", "Creating", ACTIVE, "Content exists and is being rendered."),
    Status("reviewing", "Reviewing", ACTIVE, "Renders exist and are waiting on creative review."),
    Status("revising", "Revising", ACTIVE, "Approved revisions are waiting to be run."),
    Status("awaiting_approval", "Awaiting Approval", ATTENTION, "Renders need a final decision."),
    Status("approved", "Approved", POSITIVE, "At least one render is approved and ready to export."),
    Status("exported", "Exported", POSITIVE, "An export package has been created."),
    Status("blocked", "Blocked", BLOCKED, "Something must be fixed before work can continue."),
)

CAMPAIGN_STAGE_ORDER = tuple(s.key for s in CAMPAIGN_STATUSES if s.key != "blocked")

_CAMPAIGN = _index(CAMPAIGN_STATUSES)


# --- Content piece ----------------------------------------------------------

CONTENT_STATUSES: tuple[Status, ...] = (
    Status("draft", "Draft", NEUTRAL, "Written, no template assigned yet."),
    Status("ready_to_render", "Ready to Render", ATTENTION, "Everything needed is in place."),
    Status("missing_inputs", "Missing Inputs", BLOCKED, "Required source files or copy are missing."),
    Status("rendering", "Rendering", ACTIVE, "A render is running now."),
    Status("rendered", "Rendered", POSITIVE, "A render exists and can be reviewed."),
    Status("needs_revision", "Needs Revision", ATTENTION, "A reviewer asked for changes."),
    Status("awaiting_approval", "Awaiting Approval", ATTENTION, "Waiting on a final decision."),
    Status("approved", "Approved", POSITIVE, "Signed off and exportable."),
    Status("rejected", "Rejected", BLOCKED, "Will not be used."),
    Status("unsupported", "Not Supported", BLOCKED, "No working template can produce this piece."),
)

_CONTENT = _index(CONTENT_STATUSES)


# --- Template ---------------------------------------------------------------

TEMPLATE_STATUSES: tuple[Status, ...] = (
    Status("ready", "Ready", POSITIVE, "Produces the output this template describes."),
    Status("partial", "Partial", ATTENTION, "Produces output, but not everything it promises."),
    Status("planned", "Planned", NEUTRAL, "Described only. Cannot produce output."),
    Status("manual_only", "Manual Only", NEUTRAL, "Finished by hand outside BettyOS."),
)

_TEMPLATE = _index(TEMPLATE_STATUSES)


# --- Action feedback --------------------------------------------------------

ACTION_STATUSES: tuple[Status, ...] = (
    Status("saving", "Saving", ACTIVE),
    Status("saved", "Saved", POSITIVE),
    Status("failed", "Failed", BLOCKED),
    Status("running", "Running", ACTIVE),
    Status("complete", "Complete", POSITIVE),
    Status("blocked", "Blocked", BLOCKED),
)

_ACTION = _index(ACTION_STATUSES)


# --- Revision capability ----------------------------------------------------

# Three levels, from `services.revision_types`. A copy rewrite is never called
# manual work: if a language model can propose it from the Brand Guide, it is
# AI_ASSISTED and a person approves the wording before anything is rendered.
CAPABILITY_STATUSES: tuple[Status, ...] = (
    Status(
        "READY_TO_APPLY",
        "Ready to Apply",
        POSITIVE,
        "One setting BettyOS can change on its own, with no creative judgement.",
    ),
    Status(
        "AI_ASSISTED",
        "AI Suggestion Available",
        ACTIVE,
        "BettyOS can propose wording from the Brand Guide for you to approve.",
    ),
    Status(
        "HUMAN_INPUT_REQUIRED",
        "Human Input Required",
        ATTENTION,
        "Something has to be supplied or decided before this can be done.",
    ),
)

_CAPABILITY = _index(CAPABILITY_STATUSES)


# --- Revision request lifecycle ---------------------------------------------

REVISION_REQUEST_STATUSES: tuple[Status, ...] = (
    Status("proposed", "Awaiting Decision", ATTENTION, "No suggestions generated yet."),
    Status("generating", "Generating", ACTIVE, "BettyOS is writing options now."),
    Status("options_ready", "Options Ready", ATTENTION, "Suggestions are waiting for a choice."),
    Status("selected", "Ready to Apply", ATTENTION, "An option is chosen and awaiting approval."),
    Status("approved_to_apply", "Approved to Apply", ATTENTION, "Approved; the render will follow."),
    Status("applying", "Applying", ACTIVE, "A new version is being built."),
    Status("applied", "Applied", POSITIVE, "A new version exists and is awaiting review."),
    Status("failed", "Failed", BLOCKED, "Nothing was changed. The reason is recorded."),
    Status("dismissed", "Dismissed", NEUTRAL, "Set aside without changing anything."),
)

_REVISION_REQUEST = _index(REVISION_REQUEST_STATUSES)


# --- Mapping from backend raw values ---------------------------------------

# campaign approvals.json / versions.json review_status
_APPROVAL_TO_CONTENT = {
    "approved": "approved",
    "needs_revision": "needs_revision",
    "rejected": "rejected",
    "awaiting_review": "awaiting_approval",
}

# latest_scores.json recommendation status
_RECOMMENDATION_TO_LABEL = {
    "proposed": Status("proposed", "Open", ATTENTION),
    "approved": Status("approved", "Approved", POSITIVE),
    "dismissed": Status("dismissed", "Dismissed", NEUTRAL),
    "in_progress": Status("in_progress", "Running", ACTIVE),
    "completed": Status("completed", "Complete", POSITIVE),
    "failed": Status("failed", "Failed", BLOCKED),
}

PRIORITY_LABELS = {"high": "High impact", "medium": "Medium impact", "low": "Low impact"}
PRIORITY_TONES = {"high": ATTENTION, "medium": NEUTRAL, "low": NEUTRAL}


def _fallback(key: str) -> Status:
    return Status(key, key.replace("_", " ").title(), NEUTRAL)


def campaign_status(key: str) -> Status:
    return _CAMPAIGN.get(key) or _fallback(key)


def content_status(key: str) -> Status:
    return _CONTENT.get(key) or _fallback(key)


def template_status(key: str) -> Status:
    return _TEMPLATE.get(key) or _fallback(key)


def action_status(key: str) -> Status:
    return _ACTION.get(key) or _fallback(key)


def capability_status(key: str) -> Status:
    return _CAPABILITY.get(key) or _fallback(key)


def revision_request_status(key: str) -> Status:
    return _REVISION_REQUEST.get(key) or _fallback(key)


def content_status_for_approval(raw: str) -> Status:
    return content_status(_APPROVAL_TO_CONTENT.get(raw, "awaiting_approval"))


def recommendation_status(raw: str) -> Status:
    return _RECOMMENDATION_TO_LABEL.get(raw) or _fallback(raw)


def priority_status(raw: str) -> Status:
    key = raw if raw in PRIORITY_LABELS else "medium"
    return Status(key, PRIORITY_LABELS[key], PRIORITY_TONES[key])


# --- Workflow steps ---------------------------------------------------------

WORKFLOW_STEPS: tuple[tuple[str, str], ...] = (
    ("brief", "Brief"),
    ("content", "Content"),
    ("create", "Create"),
    ("studio", "Studio"),
    ("review", "Review"),
    ("revise", "Revise"),
    ("approve", "Approve"),
    ("export", "Export"),
)

# Which product area each workflow step belongs to.
STEP_DESTINATION = {
    "brief": "Campaigns",
    "content": "Create",
    "create": "Create",
    "studio": "Studio",
    "review": "Review",
    "revise": "Revisions",
    "approve": "Approvals",
    "export": "Export",
}
