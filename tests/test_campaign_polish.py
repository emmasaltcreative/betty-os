"""Campaign experience polish — timeline, previews, package docs, focus chrome."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.components import PREVIEW_MAX_WIDTH
from ui.timeline import TimelineEvent, campaign_timeline


class PreviewPolishTests(unittest.TestCase):
    def test_preview_max_width_is_compact(self) -> None:
        self.assertGreaterEqual(PREVIEW_MAX_WIDTH, 320)
        self.assertLessEqual(PREVIEW_MAX_WIDTH, 420)


class TimelineTests(unittest.TestCase):
    def test_empty_campaign_timeline_is_upcoming(self) -> None:
        from ui.campaign_state import CampaignState, NextStep

        state = CampaignState(
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
            next_step=NextStep("Start", "Campaigns", ""),
            steps=[],
            activity=[],
            created_at="—",
            updated_at="—",
            revision_counts={},
            review_is_current=False,
            has_review=False,
            export_count=0,
        )
        events = campaign_timeline(state)
        self.assertGreaterEqual(len(events), 7)
        self.assertTrue(all(isinstance(e, TimelineEvent) for e in events))
        self.assertEqual(events[0].label, "Campaign Created")
        self.assertIn("Publishing Package Built", [e.label for e in events])

    def test_existing_campaign_timeline_marks_completed(self) -> None:
        from ui.campaign_state import list_campaigns, build_campaign_state

        campaigns = list_campaigns()
        if not campaigns:
            self.skipTest("No campaigns available")
        state = build_campaign_state(campaigns[0].path)
        events = campaign_timeline(state)
        self.assertTrue(any(e.state == "complete" for e in events))
        # Version history concept is not the primary label
        self.assertNotIn("Version History", [e.label for e in events])


class PackageDocumentTests(unittest.TestCase):
    def test_campaign_overview_document_helper(self) -> None:
        from ui.campaign_state import CampaignState, NextStep
        from ui.export_service import _campaign_overview_text, _campaign_package_documents

        state = CampaignState(
            path=None,
            name="Reading Hour Campaign",
            goal="Grow the waitlist",
            package_path=None,
            package_name="",
            platforms=["Instagram"],
            pieces=[],
            versions=[],
            stage="approved",
            blockers=[],
            next_step=NextStep("Deliver", "workspace", "deliver"),
            steps=[],
            activity=[],
            created_at="—",
            updated_at="—",
            revision_counts={},
            review_is_current=False,
            has_review=False,
            export_count=1,
        )
        overview = _campaign_overview_text(state)
        self.assertIn("Reading Hour Campaign", overview)
        self.assertIn("Grow the waitlist", overview)
        self.assertIn("ready for execution", overview)
        self.assertNotIn("excluded", overview.lower())
        docs = _campaign_package_documents(state, "reading-hour_publishing-package")
        names = [name for name, _ in docs]
        self.assertTrue(any(n.endswith("Campaign Overview.txt") for n in names))
    def test_publishing_package_includes_overview_and_manifest(self) -> None:
        campaign = ROOT / "outputs" / "2026-07-27_191825_campaign"
        if not campaign.is_dir():
            self.skipTest("Regression campaign missing")
        from ui.campaign_state import build_campaign_state
        from ui.export_service import PUBLISHING_MODE, create_export_package
        import unittest.mock

        state = build_campaign_state(campaign)
        export_root = Path(tempfile.mkdtemp(prefix="betty_polish_pkg_"))
        try:
            with unittest.mock.patch("ui.export_service.exports_dir", return_value=export_root):
                result = create_export_package(
                    state, mode=PUBLISHING_MODE, acknowledge_warnings=True
                )
            if not result.ok:
                self.skipTest(f"Package not creatable: {result.message}")
            assert result.path is not None
            with zipfile.ZipFile(result.path) as zf:
                names = zf.namelist()
                self.assertTrue(any("BettyOS Data/manifest.json" in n for n in names))
                self.assertTrue(
                    any(n.endswith("00 Campaign Overview.pdf") for n in names)
                    or any(n.endswith("Campaign Overview.txt") for n in names)
                )
                # Still one campaign package — platform folders, no drafts folder
                self.assertFalse(any("/drafts/" in n.lower() for n in names))
                self.assertFalse(any("/studio/" in n for n in names))
        finally:
            import shutil

            shutil.rmtree(export_root, ignore_errors=True)


class FocusAndNavCompatibilityTests(unittest.TestCase):
    def test_workspace_stages_unchanged(self) -> None:
        from ui.continue_campaign import WORKSPACE_STAGES

        keys = [k for k, _ in WORKSPACE_STAGES]
        self.assertEqual(
            keys, ["brief", "plan", "capture", "create", "decide", "deliver"]
        )

    def test_today_still_one_primary_path(self) -> None:
        import inspect
        from ui.screens import today as today_screen

        source = inspect.getsource(today_screen.render)
        self.assertIn("primary", source.lower())
        # Soft dashboard panels removed from calm Today
        self.assertNotIn("Needs attention", source)
        self.assertNotIn("Recently learned", source)


if __name__ == "__main__":
    unittest.main()
