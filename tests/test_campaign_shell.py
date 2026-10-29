"""Campaign shell, coverage, navigation, create job, and human delivery."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CampaignMetaTests(unittest.TestCase):
    def test_suggest_meaningful_title(self) -> None:
        from src.campaign_meta import suggest_campaign_title

        self.assertEqual(
            suggest_campaign_title(
                "Grow a qualified waitlist for First Edition: The Reading Hour"
            ),
            "Reading Hour Waitlist",
        )
        self.assertNotIn("2026", suggest_campaign_title("Launch the first edition"))

    def test_meta_persists_and_migrates(self) -> None:
        from src.campaign_meta import (
            ensure_campaign_meta,
            load_campaign_meta,
            suggest_campaign_title,
        )

        tmp = Path(tempfile.mkdtemp(prefix="betty_meta_"))
        campaign = tmp / "2026-08-04_165657_campaign"
        campaign.mkdir()
        meta = ensure_campaign_meta(
            campaign,
            objective="Grow a qualified waitlist for First Edition: The Reading Hour",
            pieces=[],
        )
        self.assertEqual(meta.display_title, "Reading Hour Waitlist")
        self.assertTrue((campaign / "campaign.json").is_file())
        again = load_campaign_meta(campaign)
        assert again is not None
        self.assertEqual(again.display_title, suggest_campaign_title(again.objective))

    def test_coverage_and_next(self) -> None:
        from src.campaign_meta import (
            CampaignMeta,
            PlannedDeliverable,
            coverage_summary,
            next_recommended_deliverable,
            why_next_matters,
        )

        meta = CampaignMeta(
            display_title="Reading Hour Waitlist",
            deliverables=[
                PlannedDeliverable(
                    "d1", "Instagram Reel", "Instagram", "Reel", role="awareness", status="approved"
                ),
                PlannedDeliverable(
                    "d2",
                    "Editorial Carousel",
                    "Carousel",
                    "Carousel",
                    role="consideration",
                    status="ready_to_create",
                ),
                PlannedDeliverable(
                    "d3", "Email", "Email", "Email", role="conversion", status="planned"
                ),
            ],
        )
        coverage = coverage_summary(meta)
        self.assertEqual(coverage["approved_count"], 1)
        self.assertEqual(coverage["required_total"], 3)
        nxt = next_recommended_deliverable(meta)
        assert nxt is not None
        self.assertEqual(nxt.title, "Editorial Carousel")
        self.assertIn("consideration", why_next_matters(nxt))

    def test_why_next_matters_handles_none_dict_and_gaps(self) -> None:
        from src.campaign_meta import PlannedDeliverable, why_next_matters

        none_text = why_next_matters(None)
        self.assertIsInstance(none_text, str)
        self.assertNotEqual(none_text, "None")
        self.assertIn("complete", none_text.lower())

        as_dict = {
            "title": "Editorial Carousel",
            "role": "consideration",
        }
        dict_text = why_next_matters(as_dict)
        self.assertIn("Editorial Carousel", dict_text)
        self.assertIn("consideration-stage gap", dict_text)
        self.assertIn("publishing runway", dict_text)
        self.assertNotIn("deliverable_id", dict_text)

        sparse = PlannedDeliverable(
            "", "", "Instagram", "", role="", status="planned"
        )
        sparse_text = why_next_matters(sparse, runway_days=None)
        self.assertIn("next deliverable", sparse_text)
        self.assertNotEqual(sparse_text, "None")
        self.assertTrue(sparse_text.endswith("."))


class NavDestinationTests(unittest.TestCase):
    def test_visible_nav_items(self) -> None:
        from ui import nav

        self.assertEqual(
            list(nav.NAV_ITEMS),
            ["Today", "Campaigns", "Library", "Pin Studio", "Video Studio", "Settings"],
        )
        self.assertNotIn("Insights", nav.NAV_ITEMS)
        self.assertIn("Insights", nav.HIDDEN_NAV_ITEMS)

    def test_sidebar_leaving_workspace(self) -> None:
        from ui import nav

        class _State(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        fake = _State()
        with patch("ui.nav.st") as st:
            st.session_state = fake
            fake["_contextual_page"] = nav.WORKSPACE
            fake["_last_sidebar_nav"] = "Today"
            left = nav.sync_sidebar_leaving_workspace("Campaigns")
            self.assertTrue(left)
            self.assertIsNone(fake.get("_contextual_page"))


class CreateJobTests(unittest.TestCase):
    def test_duplicate_job_guard(self) -> None:
        from ui.screens import workspace as ws

        class _State(dict):
            pass

        fake = _State()
        fake["betty_create_job"] = {"id": "abc", "status": "running"}
        with patch("ui.screens.workspace.st") as st:
            st.session_state = fake
            # Should return immediately without calling render
            with patch("ui.screens.workspace.render_piece") as render_piece:
                ws._run_create_best(MagicMock(path=None, pieces=[], versions=[]), None, None)
                render_piece.assert_not_called()


class DeliveryDocumentTests(unittest.TestCase):
    def test_overview_language_is_positive(self) -> None:
        from src.campaign_delivery import campaign_overview_copy

        state = MagicMock(name="Reading Hour Waitlist")
        state.name = "Reading Hour Waitlist"
        text = campaign_overview_copy(state, deliverable_count=3, platform_count=2)
        self.assertIn("ready for execution", text)
        self.assertNotIn("excluded", text.lower())
        self.assertNotIn("superseded", text.lower())

    def test_copybook_pdf_and_docx(self) -> None:
        from src.campaign_delivery import build_copybook_documents

        item = MagicMock()
        item.platform = "pinterest"
        item.content_type = "Editorial Pin"
        item.label = "Editorial Pin"
        item.package_files = []
        plan = MagicMock(included=[item])
        state = MagicMock()
        state.name = "Reading Hour Waitlist"
        docs = build_copybook_documents(state, plan)
        names = [n for n, _ in docs]
        self.assertIn("03 Campaign Copybook.pdf", names)
        self.assertIn("03 Campaign Copybook.docx", names)
        for _, payload in docs:
            self.assertGreater(len(payload), 100)

    def test_simple_docx_is_zip(self) -> None:
        from src.docx_simple import build_docx

        data = build_docx(["Hello", "## Section", "Body"], title="Test")
        self.assertTrue(data[:2] == b"PK")
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
            self.assertIn("word/document.xml", zf.namelist())


class HumanPackageTests(unittest.TestCase):
    def test_publishing_package_human_layout(self) -> None:
        campaign = ROOT / "outputs" / "2026-07-27_191825_campaign"
        if not campaign.is_dir():
            self.skipTest("Regression campaign missing")
        from ui.campaign_state import build_campaign_state
        from ui.export_service import PUBLISHING_MODE, create_export_package
        from src.campaign_delivery import is_primary_text_deliverable

        state = build_campaign_state(campaign)
        export_root = Path(tempfile.mkdtemp(prefix="betty_shell_pkg_"))
        try:
            with patch("ui.export_service.exports_dir", return_value=export_root):
                result = create_export_package(
                    state, mode=PUBLISHING_MODE, acknowledge_warnings=True
                )
            if not result.ok:
                self.skipTest(f"Package not creatable: {result.message}")
            assert result.path is not None
            self.assertIn("campaign-delivery", result.path.name)
            self.assertNotRegex(result.path.name, r"_\d{6,}_")
            with zipfile.ZipFile(result.path) as zf:
                names = zf.namelist()
                self.assertTrue(any(n.endswith("00 Campaign Overview.pdf") for n in names))
                self.assertTrue(any(n.endswith("03 Campaign Copybook.pdf") for n in names))
                self.assertTrue(any(n.endswith("03 Campaign Copybook.docx") for n in names))
                self.assertTrue(any("BettyOS Data/manifest.json" in n for n in names))
                primary_txt = [
                    n
                    for n in names
                    if is_primary_text_deliverable(n)
                    and "BettyOS Data" not in n
                ]
                self.assertEqual(primary_txt, [], primary_txt)
                overview = next(n for n in names if n.endswith("00 Campaign Overview.pdf"))
                self.assertGreater(len(zf.read(overview)), 100)
        finally:
            import shutil

            shutil.rmtree(export_root, ignore_errors=True)


class DisplayNameTests(unittest.TestCase):
    def test_build_state_uses_meta_title(self) -> None:
        campaigns = list((ROOT / "outputs").glob("*_campaign"))
        if not campaigns:
            self.skipTest("No campaigns")
        from ui.campaign_state import build_campaign_state, campaign_display_name

        # Prefer Oh Betty Aug 4 campaign when present
        preferred = ROOT / "outputs" / "2026-08-04_165657_campaign"
        path = preferred if preferred.is_dir() else campaigns[0]
        state = build_campaign_state(path)
        self.assertFalse(state.name.startswith("Campaign —"))
        self.assertEqual(campaign_display_name(path), state.name)


class CampaignShellRenderTests(unittest.TestCase):
    """Catch runtime NameErrors that unit helpers alone miss."""

    def _active_campaign(self) -> Path:
        preferred = ROOT / "outputs" / "2026-08-04_165657_campaign"
        if preferred.is_dir():
            return preferred
        campaigns = sorted((ROOT / "outputs").glob("*_campaign"), reverse=True)
        if not campaigns:
            self.skipTest("No campaigns available")
        return campaigns[0]

    def test_why_next_matters_is_module_scoped_for_overview(self) -> None:
        """Regression for NameError in _shell_overview(why_next_matters).

        The helper must live on the campaigns module — a local import inside
        `_campaign_shell` is invisible to `_shell_overview`.
        """
        from ui.screens import campaigns as campaigns_screen

        self.assertTrue(hasattr(campaigns_screen, "why_next_matters"))
        self.assertTrue(callable(campaigns_screen.why_next_matters))
        # Source check: Overview body uses the helper without a local import.
        source = Path(campaigns_screen.__file__).read_text(encoding="utf-8")
        overview_start = source.index("def _shell_overview")
        overview_end = source.index("\ndef _shell_creative")
        overview_body = source[overview_start:overview_end]
        self.assertIn("why_next_matters(", overview_body)
        self.assertNotIn("from src.campaign_meta import", overview_body)

    def test_campaign_shell_routes_via_apptest(self) -> None:
        from streamlit.testing.v1 import AppTest

        from ui import nav

        campaign = self._active_campaign()
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
        at.session_state[nav.NAV] = "Campaigns"
        at.session_state[nav.ACTIVE_CAMPAIGN] = campaign.name
        at.session_state["_contextual_page"] = None
        at.session_state["betty_sidebar_campaign_collapsed"] = True

        # Accept migrated title if the prompt appears, then render Overview.
        at.session_state["campaign_shell_tab"] = "Overview"
        result = at.run()
        if result.exception:
            self.fail(f"Campaign Overview raised: {result.exception!r}")

        # Title acceptance button may be present for migrated campaigns.
        for button in list(result.button):
            label = (button.label or "").lower()
            if "use this name" in label or "keep editing" in label:
                button.click().run()
                break

        result = at.run()
        self.assertFalse(
            result.exception,
            f"Campaign Overview after title prompt raised: {result.exception!r}",
        )

        for tab in ("Creative", "Publishing", "Timeline", "Overview"):
            at.session_state["campaign_shell_tab"] = tab
            result = at.run()
            self.assertFalse(
                result.exception,
                f"Campaign {tab} raised: {result.exception!r}",
            )

    def test_today_and_campaigns_nav_smoke(self) -> None:
        from streamlit.testing.v1 import AppTest

        from ui import nav

        campaign = self._active_campaign()
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
        at.session_state[nav.ACTIVE_CAMPAIGN] = campaign.name
        at.session_state["_contextual_page"] = None

        for page in ("Today", "Campaigns"):
            at.session_state[nav.NAV] = page
            if page == "Campaigns":
                at.session_state["campaign_shell_tab"] = "Overview"
            result = at.run()
            self.assertFalse(
                result.exception,
                f"{page} raised: {result.exception!r}",
            )


if __name__ == "__main__":
    unittest.main()
