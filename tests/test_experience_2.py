"""Experience 2 — guided creative OS: nav, Today resolver, workspace, journal."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ui.continue_campaign import (
    AWAITING_APPROVAL,
    BLOCKED,
    COMPLETE,
    CONTENT_PLAN_READY,
    DRAFT_READY,
    HUMAN_INPUT_REQUIRED,
    NO_ACTIVE_CAMPAIGN,
    READY_TO_CREATE,
    READY_TO_EXPORT,
    REVISION_NEEDED,
    WORKSPACE_STAGES,
    resolve_continuation,
)
from ui.journal import journal_for_campaign, recent_learning_summary
from ui.nav import LEGACY_TO_STAGE, NAV_ITEMS, WORKSPACE
from ui.status import STEP_DESTINATION, WORKFLOW_STEPS


def _empty_state(**overrides):
    from ui.campaign_state import CampaignState, NextStep

    base = CampaignState(
        path=None,
        name="No campaign",
        goal="No goal recorded",
        package_path=None,
        package_name="",
        platforms=[],
        pieces=[],
        versions=[],
        stage="planning",
        blockers=[],
        next_step=NextStep("Start a Campaign", "Campaigns", ""),
        steps=[],
        activity=[],
        created_at="—",
        updated_at="—",
        revision_counts={
            "awaiting_decision": 0,
            "ready_to_apply": 0,
            "needs_human": 0,
            "failed": 0,
            "applied": 0,
            "applying": 0,
            "proposed": 0,
            "generating": 0,
            "options_ready": 0,
            "selected": 0,
            "approved_to_apply": 0,
            "dismissed": 0,
        },
        review_is_current=False,
        has_review=False,
        export_count=0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class NavigationReductionTests(unittest.TestCase):
    def test_primary_nav_is_five_destinations(self) -> None:
        self.assertEqual(
            list(NAV_ITEMS),
            ["Today", "Campaigns", "Library", "Insights", "Settings"],
        )

    def test_pipeline_pages_not_in_primary_nav(self) -> None:
        forbidden = {"Create", "Studio", "Review", "Revisions", "Approvals", "Export", "Home"}
        self.assertTrue(forbidden.isdisjoint(set(NAV_ITEMS)))

    def test_legacy_destinations_map_to_workspace_stages(self) -> None:
        self.assertEqual(LEGACY_TO_STAGE["Create"], "create")
        self.assertEqual(LEGACY_TO_STAGE["Studio"], "create")
        self.assertEqual(LEGACY_TO_STAGE["Review"], "decide")
        self.assertEqual(LEGACY_TO_STAGE["Approvals"], "decide")
        self.assertEqual(LEGACY_TO_STAGE["Export"], "deliver")
        self.assertEqual(WORKSPACE, "workspace")

    def test_workflow_steps_are_founder_facing(self) -> None:
        labels = [label for _, label in WORKFLOW_STEPS]
        self.assertEqual(labels, ["Brief", "Plan", "Capture", "Create", "Decide", "Deliver"])
        self.assertEqual(len(WORKSPACE_STAGES), 6)

    def test_step_destinations_point_at_workspace(self) -> None:
        for key in ("brief", "plan", "capture", "create", "decide", "deliver"):
            self.assertEqual(STEP_DESTINATION[key], "workspace")


class TodayResolverTests(unittest.TestCase):
    def test_no_active_campaign(self) -> None:
        result = resolve_continuation(_empty_state())
        self.assertEqual(result.current_state, NO_ACTIVE_CAMPAIGN)
        self.assertEqual(result.primary_action.label, "Start a Campaign")
        self.assertEqual(result.primary_action.destination, "Campaigns")

    def test_needs_brief_when_goal_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            state = _empty_state(path=campaign, name="Demo", goal="No goal recorded")
            result = resolve_continuation(state)
            self.assertEqual(result.current_state, CAMPAIGN_NEEDS_BRIEF := "campaign_needs_brief")
            self.assertEqual(result.primary_action.stage, "brief")

    def test_content_plan_ready_without_versions(self) -> None:
        piece = MagicMock()
        piece.status_key = "unsupported"
        piece.record.piece_id = "piece_001"
        piece.record.title = "Test"
        piece.record.platform = "Pinterest"
        piece.missing_inputs = []
        piece.can_render = False
        piece.template = None
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            state = _empty_state(
                path=campaign,
                name="Demo",
                goal="Grow a waitlist",
                pieces=[piece],
                stage="blocked",
                blockers=["I selected a concept the current templates cannot produce."],
            )
            result = resolve_continuation(state)
            self.assertIn(result.current_state, {BLOCKED, CONTENT_PLAN_READY})

    def test_human_input_required(self) -> None:
        piece = MagicMock()
        piece.status_key = "missing_inputs"
        piece.record.piece_id = "piece_001"
        piece.record.title = "Reading Hour"
        piece.record.platform = "Pinterest"
        piece.record.source_assets = []
        piece.missing_inputs = ["No source media selected"]
        piece.can_render = True
        piece.template = None
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            state = _empty_state(
                path=campaign,
                name="Demo",
                goal="Grow a waitlist",
                pieces=[piece],
            )
            result = resolve_continuation(state)
            self.assertEqual(result.current_state, HUMAN_INPUT_REQUIRED)
            self.assertEqual(result.primary_action.stage, "capture")
            self.assertTrue(result.required_from_user)

    def test_ready_to_create(self) -> None:
        piece = MagicMock()
        piece.status_key = "ready_to_render"
        piece.record.piece_id = "piece_001"
        piece.record.title = "Reading Hour"
        piece.record.platform = "Pinterest"
        piece.missing_inputs = []
        piece.can_render = True
        piece.template = None
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            state = _empty_state(
                path=campaign,
                name="Demo",
                goal="Grow a waitlist",
                pieces=[piece],
            )
            result = resolve_continuation(state)
            self.assertEqual(result.current_state, READY_TO_CREATE)
            self.assertEqual(result.primary_action.label, "Create Best Draft")

    def test_ready_to_export(self) -> None:
        version = MagicMock()
        version.approval_status = "approved"
        version.is_latest = True
        version.key = "t|p|v1"
        version.piece_id = "piece_001"
        version.display_name = "Reel"
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            state = _empty_state(
                path=campaign,
                name="Demo",
                goal="Grow a waitlist",
                pieces=[MagicMock(status_key="approved", record=MagicMock(piece_id="piece_001", title="X", platform="IG", source_assets=[]), missing_inputs=[], can_render=True, template=None, versions=[version])],
                versions=[version],
                export_count=0,
            )
            # Force counts via property is hard; patch counts
            with patch.object(type(state), "counts", property(lambda self: {
                "pieces": 1,
                "ready_to_render": 0,
                "missing_inputs": 0,
                "unsupported": 0,
                "rendered": 1,
                "renders": 1,
                "needs_revision": 0,
                "awaiting_approval": 0,
                "approved": 1,
                "rejected": 0,
            })):
                with patch("ui.continue_campaign._campaign_has_finish", return_value=True):
                    with patch("ui.continue_campaign._best_draft_for_review", return_value=None):
                        result = resolve_continuation(state)
            self.assertEqual(result.current_state, READY_TO_EXPORT)
            self.assertEqual(result.primary_action.stage, "deliver")

    def test_continuation_dict_shape(self) -> None:
        result = resolve_continuation(_empty_state())
        payload = result.to_dict()
        for key in (
            "campaign_id",
            "current_stage",
            "headline",
            "message",
            "why",
            "required_from_user",
            "primary_action",
            "secondary_actions",
            "blockers",
            "confidence",
        ):
            self.assertIn(key, payload)
        self.assertIn("label", payload["primary_action"])
        self.assertIn("destination", payload["primary_action"])


class LiveCampaignCompatibilityTests(unittest.TestCase):
    def test_existing_campaign_resolves(self) -> None:
        from ui.campaign_state import build_campaign_state, list_campaigns

        campaigns = list_campaigns()
        if not campaigns:
            self.skipTest("No live campaigns in outputs/")
        state = build_campaign_state(campaigns[0].path)
        result = resolve_continuation(state)
        self.assertTrue(result.headline)
        self.assertTrue(result.primary_action.label)
        self.assertIn(result.current_stage, {k for k, _ in WORKSPACE_STAGES})
        # Progress rail uses six founder stages
        self.assertEqual(len(state.steps), 6)
        self.assertEqual([s.label for s in state.steps], ["Brief", "Plan", "Capture", "Create", "Decide", "Deliver"])

    def test_journal_does_not_raise(self) -> None:
        from ui.campaign_state import build_campaign_state, list_campaigns

        campaigns = list_campaigns()
        if not campaigns:
            self.skipTest("No live campaigns in outputs/")
        state = build_campaign_state(campaigns[0].path)
        entries = journal_for_campaign(state, limit=5)
        self.assertIsInstance(entries, list)
        # Learning summary may be empty before promotions
        self.assertIsInstance(recent_learning_summary(), list)

    def test_workspace_context_persists(self) -> None:
        from src.persistence import load_json
        from ui.nav import WORKSPACE_CONTEXT_FILE, persist_workspace_context

        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            with patch("ui.nav.st") as mock_st:
                mock_st.session_state = {
                    "selected_piece": "piece_001",
                    "focus_version_key": "t|p|v1",
                    "pending_workspace_stage": "decide",
                    "interrupted_flow": None,
                }
                persist_workspace_context(campaign, stage="decide")
            data = load_json(campaign / WORKSPACE_CONTEXT_FILE)
            self.assertEqual(data["campaign_id"], "demo_campaign")
            self.assertEqual(data["stage"], "decide")
            self.assertEqual(data["selected_piece"], "piece_001")


class WorkspaceStageSelectorTests(unittest.TestCase):
    """Regression: pending stage must bind before the stage widget exists."""

    class _GuardedSession(dict):
        """Mimic Streamlit: refuse writes to a key after its widget is created."""

        def __init__(self) -> None:
            super().__init__()
            self.widget_keys: set[str] = set()

        def __setitem__(self, key, value):  # type: ignore[override]
            if key in self.widget_keys:
                raise RuntimeError(
                    f"st.session_state.{key} cannot be modified after the widget "
                    f"with key {key} is instantiated."
                )
            super().__setitem__(key, value)

        def mark_widget(self, key: str) -> None:
            self.widget_keys.add(key)

    def test_write_after_widget_instantiation_raises(self) -> None:
        """Documents the previous error condition on key=workspace_stage."""
        session = self._GuardedSession()
        session["workspace_stage"] = "Plan"
        session.mark_widget("workspace_stage")
        with self.assertRaises(RuntimeError) as ctx:
            session["workspace_stage"] = "Decide"
        self.assertIn("cannot be modified after the widget", str(ctx.exception))

    def test_pending_decide_applied_before_selector_widget(self) -> None:
        from ui import nav
        from ui.screens.workspace import (
            STAGE_KEYS,
            STAGE_SELECTOR_KEY,
            prepare_workspace_stage_selector,
        )

        session = self._GuardedSession()
        session[nav.PENDING_STAGE] = "decide"

        def fake_step_selector(label, options, *, key):
            # Widget is now live — further writes to `key` must fail.
            session.mark_widget(key)
            return session.get(key)

        with (
            patch("ui.screens.workspace.st") as workspace_st,
            patch("ui.nav.st", workspace_st),
            patch("ui.nav.step_selector", side_effect=fake_step_selector),
        ):
            workspace_st.session_state = session
            selected = prepare_workspace_stage_selector("create")

        self.assertEqual(selected, "Decide")
        self.assertEqual(session[STAGE_SELECTOR_KEY], "Decide")
        self.assertEqual(STAGE_KEYS[selected], "decide")
        self.assertIsNone(session.get(nav.PENDING_STAGE))
        # No post-widget write attempted — would have raised.
        self.assertIn(STAGE_SELECTOR_KEY, session.widget_keys)


class RecommendationCopyTests(unittest.TestCase):
    def test_draft_why_uses_major_decisions_not_generic(self) -> None:
        from ui.continue_campaign import _draft_why

        finish = MagicMock()
        finish.edit_decision = {
            "major_decisions": [
                "Color recipe: OBJ Pinterest Editorial",
                "Logo omitted to protect visual hierarchy",
                "Framed for Pinterest Pin",
            ],
            "platform": "Pinterest",
            "logo_decision": {"value": "omit"},
            "rationale": "One best finish for editorial_pin using OBJ Pinterest Editorial.",
        }
        state = _empty_state(goal="Grow a waitlist for Reading Hour", name="Reading Hour")
        version = MagicMock(piece_id=None)
        why = _draft_why(finish, state=state, title="Reading Hour reel", version=version)
        self.assertNotIn("I selected, finished, and reviewed the strongest available version", why)
        self.assertIn("strongest draft", why.lower())
        self.assertTrue(
            "logo" in why.lower() or "finish" in why.lower() or "frame" in why.lower()
        )

    def test_failed_revision_is_soft_attention_not_primary(self) -> None:
        from ui.continue_campaign import soft_attention_items, primary_blockers_for_display

        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            state = _empty_state(
                path=campaign,
                name="Demo",
                goal="Grow a waitlist",
                blockers=["1 revision failed to apply. Nothing was changed."],
            )
            state.revision_counts["failed"] = 1
            result = resolve_continuation(state)
            # Soft attention captures the failure; primary card blockers stay empty unless BLOCKED.
            attention = soft_attention_items(state, result)
            self.assertTrue(attention)
            self.assertEqual(attention[0]["blocks_approval"], "No")
            if result.current_state != "blocked":
                self.assertEqual(primary_blockers_for_display(result), [])


class PrimaryActionSelectionTests(unittest.TestCase):
    def test_each_state_has_one_primary_label(self) -> None:
        cases = [
            (_empty_state(), "Start a Campaign"),
        ]
        for state, expected in cases:
            result = resolve_continuation(state)
            self.assertEqual(result.primary_action.label, expected)
            self.assertTrue(result.primary_action.label)
            # Secondary actions must not duplicate the primary label
            for secondary in result.secondary_actions:
                self.assertNotEqual(secondary.label, result.primary_action.label)


if __name__ == "__main__":
    unittest.main()
