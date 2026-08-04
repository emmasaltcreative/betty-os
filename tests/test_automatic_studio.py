"""Automatic Studio finishing tests."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.brand import BRAND_BRAIN_FILES
from src.common import ROOT
from studio.auto_edit import apply_revision_note_to_config, build_edit_decision
from studio.learning import (
    PerformanceRecord,
    list_approval_events,
    list_performance_findings,
    list_performance_records,
    save_performance_record,
)
from studio.models import FinishConfiguration, utc_now_iso
from studio.service import generate_best_edit, revise_best_edit, set_finish_approval
from studio.versions import load_finish_record, render_version_id


class AutomaticStudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_auto_studio_"))
        self.brand = f"auto_brand_{self.tmp.name}"
        self.brand_dir = ROOT / "brands" / self.brand
        self.brand_dir.mkdir(parents=True, exist_ok=True)
        for name in BRAND_BRAIN_FILES:
            (self.brand_dir / name).write_text(
                "Oh Betty Jaletti is editorial, restrained, literary, and warm without clutter.\n",
                encoding="utf-8",
            )
        self.source = self.tmp / "lifestyle.png"
        Image.new("RGB", (640, 960), (228, 219, 205)).save(self.source)
        self.render_folder = self.tmp / "render"
        self.render_folder.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.brand_dir, ignore_errors=True)

    def test_build_edit_decision_loads_guidance_and_reports_cleanup(self) -> None:
        with patch.dict(os.environ, {k: "" for k in ("BETTYOS_AI_CLEANUP_PROVIDER", "REPLICATE_API_TOKEN", "OPENAI_API_KEY")}):
            decision, config = build_edit_decision(
                source_file=self.source,
                brand_id=self.brand,
                platform="instagram_reel",
                content_type="lifestyle",
                campaign_goal="A quiet reading ritual reel",
                template_id="ritual_reel",
            )

        self.assertTrue(decision.brand_guide_loaded)
        self.assertTrue(decision.production_rules_loaded)
        self.assertLessEqual(len(decision.major_decisions), 3)
        self.assertEqual(decision.logo_decision.value, "omit")
        self.assertEqual(config.logo.role, "none")
        self.assertTrue(decision.selective_cleanup)
        self.assertTrue(
            all(item.unsupported_reason == "ai_provider_required" for item in decision.selective_cleanup)
        )

    def test_revision_note_cools_and_removes_logo(self) -> None:
        config = FinishConfiguration()
        config.color.temperature = 12
        config.video.temperature = 12
        config.logo.role = "primary"
        config.logo.asset_id = "ba_fake"

        revised, actions = apply_revision_note_to_config(config, "This is too warm and the logo is distracting.")

        self.assertLess(revised.color.temperature, config.color.temperature)
        self.assertLess(revised.video.temperature, config.video.temperature)
        self.assertEqual(revised.logo.role, "none")
        self.assertIsNone(revised.logo.asset_id)
        self.assertTrue(any(action.action == "revision:logo_omit" for action in actions))

    def test_generate_best_edit_creates_immutable_finish_with_decision(self) -> None:
        original = self.source.read_bytes()
        result = generate_best_edit(
            render_folder=self.render_folder,
            campaign_id="campaign_auto",
            content_piece_id="piece_001",
            template_id="ritual_reel",
            parent_render_version_id=render_version_id(1),
            source_file=self.source,
            brand_id=self.brand,
            platform="instagram_reel",
            content_type="lifestyle",
            campaign_goal="Finish the reading ritual.",
        )

        self.assertTrue(result.get("ok"), result.get("error"))
        record = result["record"]
        self.assertEqual(record.finish_version_id, "finish_v001")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertTrue(record.edit_decision)
        self.assertEqual(record.edit_decision["logo_decision"]["value"], "omit")
        self.assertTrue((self.render_folder / "studio" / "finish_v001" / "edit_decision.json").is_file())
        self.assertTrue((self.render_folder / "studio" / "finish_v001" / "execution_report.json").is_file())

    def test_revise_and_approve_persist_both_versions_and_learning_events(self) -> None:
        first = generate_best_edit(
            render_folder=self.render_folder,
            campaign_id="campaign_auto",
            content_piece_id="piece_001",
            template_id="ritual_reel",
            parent_render_version_id=render_version_id(1),
            source_file=self.source,
            brand_id=self.brand,
            platform="instagram_reel",
            content_type="lifestyle",
            campaign_goal="Finish the reading ritual.",
        )
        self.assertTrue(first.get("ok"), first.get("error"))
        first_id = first["record"].finish_version_id
        needs = set_finish_approval(
            render_folder=self.render_folder,
            finish_version_id=first_id,
            approval_status="needs_revision",
            revision_note="Too warm; logo distracting.",
            brand_id=self.brand,
        )
        self.assertTrue(needs.get("ok"), needs.get("error"))

        revised = revise_best_edit(
            render_folder=self.render_folder,
            campaign_id="campaign_auto",
            content_piece_id="piece_001",
            template_id="ritual_reel",
            parent_render_version_id=render_version_id(1),
            parent_finish_version_id=first_id,
            source_file=self.source,
            revision_note="Too warm; logo distracting.",
            brand_id=self.brand,
            platform="instagram_reel",
            content_type="lifestyle",
            campaign_goal="Finish the reading ritual.",
        )
        self.assertTrue(revised.get("ok"), revised.get("error"))
        second_id = revised["record"].finish_version_id
        approved = set_finish_approval(
            render_folder=self.render_folder,
            finish_version_id=second_id,
            approval_status="approved",
            brand_id=self.brand,
        )
        self.assertTrue(approved.get("ok"), approved.get("error"))

        first_record = load_finish_record(self.render_folder, first_id)
        second_record = load_finish_record(self.render_folder, second_id)
        self.assertIsNotNone(first_record)
        self.assertIsNotNone(second_record)
        assert first_record is not None
        assert second_record is not None
        self.assertEqual(first_record.approval_status, "needs_revision")
        self.assertEqual(first_record.revision_note, "Too warm; logo distracting.")
        self.assertEqual(second_record.approval_status, "approved")
        self.assertEqual(second_record.parent_finish_version_id, first_id)
        self.assertEqual(second_record.revision_note, "Too warm; logo distracting.")
        events = list_approval_events(self.brand)
        self.assertEqual([event.approval_status for event in events], ["needs_revision", "approved"])

    def test_performance_schema_foundation(self) -> None:
        record = PerformanceRecord(
            record_id="perf_001",
            brand_id=self.brand,
            campaign_id="campaign_auto",
            content_piece_id="piece_001",
            finish_version_id="finish_v001",
            platform="instagram_reel",
            metric_name="save_rate",
            metric_value=0.14,
            metric_unit="ratio",
            observed_at=utc_now_iso(),
        )
        save_performance_record(record)

        records = list_performance_records(self.brand)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].metric_name, "save_rate")
        self.assertEqual(list_performance_findings(self.brand), [])


if __name__ == "__main__":
    unittest.main()
