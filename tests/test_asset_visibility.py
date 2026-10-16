"""Internal QA assets must stay out of the campaign product flow."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.asset_visibility import (
    classify_asset_folder,
    filter_user_facing_versions,
    is_internal_asset_folder,
    write_asset_meta,
)
from ui.campaign_state import RenderVersion, discover_render_versions


def _version(folder: Path, template_id: str = "cinematic_multi_clip_reel") -> RenderVersion:
    return RenderVersion(
        template_id=template_id,
        display_name=template_id.replace("_", " ").title(),
        folder=folder,
        piece_id=None,
        version=1,
        kind="image",
        primary_path=None,
        is_latest=True,
        approval_status="awaiting_review",
    )


class AssetVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_vis_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_meta_marks_internal(self) -> None:
        folder = self.tmp / "editorial_static_pin"
        folder.mkdir()
        write_asset_meta(folder, visibility="internal", purpose="smoke_test", notes="qa")
        info = classify_asset_folder(folder)
        self.assertTrue(info.is_internal)
        self.assertEqual(info.purpose, "smoke_test")

    def test_name_heuristic_smoke(self) -> None:
        folder = self.tmp / "logo_smoke_product"
        folder.mkdir()
        self.assertTrue(is_internal_asset_folder(folder))

    def test_campaign_folder_is_user_facing(self) -> None:
        folder = self.tmp / "cinematic_multi_clip_reel"
        folder.mkdir()
        self.assertFalse(is_internal_asset_folder(folder))

    def test_filter_user_facing_versions(self) -> None:
        good = self.tmp / "cinematic_multi_clip_reel"
        bad = self.tmp / "logo_smoke_product"
        good.mkdir()
        bad.mkdir()
        versions = [_version(good), _version(bad, "logo_smoke_product")]
        filtered = filter_user_facing_versions(versions)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].template_id, "cinematic_multi_clip_reel")


class CampaignDiscoveryExclusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_camp_"))
        self.campaign = self.tmp / "campaign"
        self.campaign.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_media(self, folder: Path, name: str = "out_v1.png") -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    def test_smoke_folder_not_discovered(self) -> None:
        real = self.campaign / "cinematic_multi_clip_reel"
        smoke = self.campaign / "logo_smoke_product"
        self._seed_media(real, "cinematic_multi_clip_reel_v1.mp4")
        self._seed_media(smoke, "source.png")
        versions = discover_render_versions(self.campaign)
        ids = {v.template_id for v in versions}
        self.assertIn("cinematic_multi_clip_reel", ids)
        self.assertNotIn("logo_smoke_product", ids)

    def test_relocated_qa_not_discovered(self) -> None:
        real = self.campaign / "editorial_static_pin"
        qa = self.campaign / "BettyOS Data" / "qa" / "logo_smoke_product"
        self._seed_media(real, "pin_v1.png")
        self._seed_media(qa, "finished.png")
        write_asset_meta(qa, visibility="internal", purpose="smoke_test")
        versions = discover_render_versions(self.campaign)
        ids = {v.template_id for v in versions}
        self.assertIn("editorial_static_pin", ids)
        self.assertNotIn("logo_smoke_product", ids)
        self.assertNotIn("BettyOS Data", ids)


class ProductFlowIntegrationTests(unittest.TestCase):
    def test_reading_hour_excludes_smoke_and_prefers_real(self) -> None:
        campaign = ROOT / "outputs" / "2026-08-04_165657_campaign"
        if not campaign.is_dir():
            self.skipTest("Reading Hour campaign missing")
        from ui.campaign_state import build_campaign_state
        from ui.continue_campaign import resolve_continuation
        from ui.export_service import PUBLISHING_MODE, build_plan

        state = build_campaign_state(campaign)
        ids = {v.template_id for v in state.versions}
        self.assertNotIn("logo_smoke_product", ids)
        self.assertTrue(
            any(
                tid in ids
                for tid in (
                    "cinematic_multi_clip_reel",
                    "editorial_static_pin",
                    "text_led_editorial_pin",
                )
            )
        )

        continuation = resolve_continuation(state)
        focus = continuation.focus_version_key or ""
        self.assertNotIn("logo_smoke", focus.lower())

        plan = build_plan(state, mode=PUBLISHING_MODE, selected_keys=set())
        labels = " ".join(
            str(getattr(i, "label", "")) + str(getattr(i, "display_name", ""))
            for i in plan.included
        ).lower()
        self.assertNotIn("logo smoke", labels)
        self.assertNotIn("logo_smoke", labels)

        # Diagnostics can still see the preserved QA validation.
        qa = campaign / "BettyOS Data" / "qa" / "logo_smoke_product"
        self.assertTrue(qa.is_dir())
        meta = json.loads((qa / "betty_asset_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta.get("visibility"), "internal")
        self.assertEqual(meta.get("purpose"), "smoke_test")
        self.assertTrue(meta.get("logo_asset_id"))


class ApprovedDecideCtaTests(unittest.TestCase):
    def test_workspace_hides_approve_when_already_approved(self) -> None:
        source = (ROOT / "ui" / "screens" / "workspace.py").read_text(encoding="utf-8")
        self.assertIn("is_approved", source)
        self.assertIn("This version is already approved", source)
        self.assertIn("Request revision", source)
        self.assertIn('_is_user_facing_version', source)


if __name__ == "__main__":
    unittest.main()
