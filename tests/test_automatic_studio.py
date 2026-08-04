"""Automatic Studio — Best Edit, revision, approval, learning persistence."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.brand import BRAND_BRAIN_FILES
from src.common import DEFAULT_BRAND_ID, ROOT
from studio.auto_edit import (
    ai_cleanup_provider_configured,
    apply_revision_note_to_config,
    build_edit_decision,
    parse_revision_request,
)
from studio.edit_decision import EditDecision
from studio.learning import (
    PerformanceRecord,
    list_approval_events,
    list_performance_findings,
    list_performance_records,
    save_performance_record,
)
from studio.models import FinishConfiguration, LogoConfiguration, utc_now_iso
from studio.service import generate_best_edit, revise_best_edit, set_finish_approval
from studio.versions import list_finish_records, load_finish_record, render_version_id


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
        self.obj_brand = DEFAULT_BRAND_ID

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.brand_dir, ignore_errors=True)

    def test_build_edit_decision_loads_guidance_and_reports_cleanup(self) -> None:
        with patch.dict(
            os.environ,
            {k: "" for k in ("BETTYOS_AI_CLEANUP_PROVIDER", "REPLICATE_API_TOKEN", "OPENAI_API_KEY")},
        ):
            decision, config = build_edit_decision(
                source_file=self.source,
                brand_id=self.brand,
                platform="instagram_reel",
                content_type="lifestyle",
                campaign_goal="A quiet reading ritual reel",
                template_id="ritual_reel",
                campaign_id="campaign_auto",
                content_piece_id="piece_001",
            )

        self.assertTrue(decision.brand_guide_loaded)
        self.assertTrue(decision.production_rules_loaded)
        self.assertTrue(decision.brand_guide_files)
        self.assertTrue(decision.production_rule_files)
        self.assertIsInstance(decision, EditDecision)
        self.assertLessEqual(len(decision.major_decisions), 3)
        self.assertTrue(decision.color_recipe.value)
        self.assertEqual(config.recipe_id, decision.color_recipe.value["recipe_id"])
        self.assertEqual(decision.recipe_id, config.recipe_id)
        self.assertFalse(ai_cleanup_provider_configured())
        self.assertTrue(
            any("AI provider not configured" in a for a in decision.unsupported_actions)
        )
        self.assertEqual(decision.logo_decision.value, "omit")
        self.assertEqual(config.logo.role, "none")
        self.assertTrue(decision.selective_cleanup)
        self.assertTrue(
            all(
                item.unsupported_reason == "ai_provider_required"
                for item in decision.selective_cleanup
            )
        )

    def test_build_edit_decision_with_obj_brand_guides(self) -> None:
        decision, config = build_edit_decision(
            brand_id=self.obj_brand,
            campaign_id="camp_test",
            content_piece_id="piece_1",
            template_id="ritual_reel",
            platform="Instagram Reels",
            campaign_goal="Grow waitlist with quiet lifestyle reels",
            piece_objective="Invite a rainy reading ritual",
            piece_format="lifestyle reel",
            media_type="static",
            source_file=self.source,
            parent_render_version_id="render_v001",
        )
        self.assertTrue(decision.brand_guide_loaded)
        self.assertTrue(decision.production_rules_loaded)
        self.assertEqual(decision.logo_decision.value, "omit")
        self.assertEqual(config.logo.role, "none")
        self.assertLessEqual(len(decision.major_decisions), 3)

    def test_revision_note_cools_and_removes_logo(self) -> None:
        config = FinishConfiguration()
        config.color.temperature = 12
        config.video.temperature = 12
        config.logo.role = "primary"
        config.logo.asset_id = "ba_fake"

        revised, actions = apply_revision_note_to_config(
            config, "This is too warm and the logo is distracting."
        )

        self.assertLess(revised.color.temperature, 12)
        self.assertLess(revised.video.temperature, 12)
        self.assertEqual(revised.logo.role, "none")
        self.assertIsNone(revised.logo.asset_id)
        self.assertTrue(any(action.action == "revision:logo_omit" for action in actions))

        out_choice: list[str] = []
        config2 = FinishConfiguration()
        config2.color.temperature = 20
        config2.logo = LogoConfiguration(role="primary", asset_id="x", placement="bottom_right")
        updated, _ = apply_revision_note_to_config(
            config2,
            "The color feels too warm and the logo is distracting.",
            out_choice,
        )
        self.assertLess(updated.color.temperature, 20)
        self.assertEqual(updated.logo.role, "none")
        self.assertEqual(out_choice, ["omit"])
        parsed = parse_revision_request("The color feels too warm and the logo is distracting.")
        self.assertIn("reduce_warmth", parsed["supported_in_finish"])
        self.assertIn("reduce_or_remove_logo", parsed["supported_in_finish"])

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
        self.assertTrue(
            (self.render_folder / "studio" / "finish_v001" / "edit_decision.json").is_file()
        )
        self.assertTrue(
            (self.render_folder / "studio" / "finish_v001" / "execution_report.json").is_file()
        )
        decision = EditDecision.from_dict(record.edit_decision)
        assert decision is not None
        self.assertLessEqual(len(decision.major_decisions), 3)
        outputs = list((self.render_folder / "studio" / "finish_v001" / "outputs").glob("*"))
        self.assertTrue(outputs)
        report = result["execution_report"]
        self.assertIn(report.state, {"edit_fully_applied", "edit_partially_applied"})
        self.assertTrue(
            any("cleanup" in a.label.lower() or "AI provider" in a.reason for a in report.not_applied)
            or decision.unsupported_actions
        )

    def test_generate_best_edit_pinterest_path(self) -> None:
        result = generate_best_edit(
            render_folder=self.render_folder,
            campaign_id="camp_auto",
            content_piece_id="piece_auto",
            template_id="editorial_static_pin",
            parent_render_version_id="render_v001",
            source_file=self.source,
            brand_id=self.brand,
            platform="Pinterest",
            campaign_goal="Editorial discovery",
            piece_objective="Quiet pin for waitlist",
            piece_format="editorial pin",
        )
        self.assertTrue(result.get("ok"), result.get("error"))
        self.assertEqual(result["record"].finish_version_id, "finish_v001")
        self.assertTrue(result["record"].execution_report)

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
            content_type="lifestyle_reel",
            platform="instagram_reel",
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
            content_type="lifestyle_reel",
            platform="instagram_reel",
        )
        self.assertTrue(approved.get("ok"), approved.get("error"))

        first_record = load_finish_record(self.render_folder, first_id)
        second_record = load_finish_record(self.render_folder, second_id)
        self.assertIsNotNone(first_record)
        self.assertIsNotNone(second_record)
        assert first_record is not None and second_record is not None
        self.assertEqual(first_record.approval_status, "needs_revision")
        self.assertEqual(first_record.revision_note, "Too warm; logo distracting.")
        self.assertEqual(second_record.parent_finish_version_id, first_id)
        self.assertEqual(second_record.revision_note, "Too warm; logo distracting.")
        events = list_approval_events(self.brand)
        self.assertEqual(
            [event.approval_status for event in events],
            ["needs_revision", "approved"],
        )

    def test_revision_and_approval_persist_theirs_api(self) -> None:
        first = generate_best_edit(
            render_folder=self.render_folder,
            campaign_id="camp_auto",
            content_piece_id="piece_auto",
            template_id="ritual_reel",
            parent_render_version_id="render_v001",
            source_file=self.source,
            brand_id=self.brand,
            platform="Instagram Reels",
            campaign_goal="Lifestyle ritual",
            piece_objective="Rainy reading",
            piece_format="lifestyle reel",
        )
        self.assertTrue(first.get("ok"), first.get("error"))
        parent_id = first["record"].finish_version_id

        revised = revise_best_edit(
            render_folder=self.render_folder,
            finish_version_id=parent_id,
            revision_note="The color feels too warm and the logo is distracting.",
            brand_id=self.brand,
            platform="Instagram Reels",
            campaign_goal="Lifestyle ritual",
            piece_objective="Rainy reading",
            piece_format="lifestyle reel",
        )
        self.assertTrue(revised.get("ok"), revised.get("error"))
        new_record = revised["record"]
        self.assertNotEqual(new_record.finish_version_id, parent_id)
        self.assertEqual(new_record.parent_finish_version_id, parent_id)
        self.assertIn("warm", (new_record.revision_note or "").lower())

        parent = load_finish_record(self.render_folder, parent_id)
        assert parent is not None
        self.assertEqual(parent.approval_status, "needs_revision")

        approved = set_finish_approval(
            render_folder=self.render_folder,
            finish_version_id=new_record.finish_version_id,
            status="approved",
            brand_id=self.brand,
            platform="Instagram Reels",
            content_type="lifestyle_reel",
        )
        self.assertTrue(approved.get("ok"))
        reloaded = load_finish_record(self.render_folder, new_record.finish_version_id)
        assert reloaded is not None
        self.assertEqual(reloaded.approval_status, "approved")
        self.assertTrue(reloaded.edit_decision)
        self.assertEqual(
            reloaded.edit_decision.get("decision_id"),
            new_record.edit_decision.get("decision_id"),
        )

        ids = {r.finish_version_id for r in list_finish_records(self.render_folder)}
        self.assertIn(parent_id, ids)
        self.assertIn(new_record.finish_version_id, ids)

        events = list_approval_events(self.brand)
        self.assertTrue(any(e.finish_version_id == new_record.finish_version_id for e in events))

    def test_performance_schema_foundation(self) -> None:
        lean = PerformanceRecord(
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
        save_performance_record(lean)
        records = list_performance_records(self.brand)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].metric_name, "save_rate")
        self.assertEqual(list_performance_findings(self.brand), [])

        rich = PerformanceRecord(
            record_id="perf_test_1",
            campaign_id="camp_auto",
            content_piece_id="piece_auto",
            template_id="ritual_reel",
            render_version_id="render_v001",
            finish_version_id="finish_v001",
            platform="instagram",
            impressions=1000,
            views=800,
            completion_rate=0.42,
        )
        save_performance_record(rich, self.brand)
        listed = list_performance_records(self.brand)
        self.assertTrue(any(r.record_id == "perf_test_1" for r in listed))
        self.assertTrue(any(r.record_id == "perf_001" for r in listed))


if __name__ == "__main__":
    unittest.main()
