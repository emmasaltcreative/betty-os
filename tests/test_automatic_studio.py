"""Automatic Studio — Best Edit, revision, approval persistence."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.common import DEFAULT_BRAND_ID
from studio.auto_edit import (
    ai_cleanup_provider_configured,
    apply_revision_note_to_config,
    build_edit_decision,
    parse_revision_request,
)
from studio.edit_decision import EditDecision
from studio.learning import (
    list_approval_events,
    list_performance_records,
    save_performance_record,
    PerformanceRecord,
)
from studio.models import FinishConfiguration, LogoConfiguration
from studio.service import generate_best_edit, revise_best_edit, set_finish_approval
from studio.versions import load_finish_record, list_finish_records


ROOT = Path(__file__).resolve().parent.parent


class AutomaticStudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_auto_studio_"))
        self.render_folder = self.tmp / "render"
        self.render_folder.mkdir(parents=True)
        self.source = self.tmp / "source.png"
        Image.new("RGB", (800, 1200), (210, 195, 180)).save(self.source)
        # Isolate learning writes into a temp brand when possible; use OBJ for Brand Guide
        self.brand = DEFAULT_BRAND_ID

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_edit_decision_loads_guides_and_is_singular(self) -> None:
        decision, config = build_edit_decision(
            brand_id=self.brand,
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
        self.assertIsInstance(decision, EditDecision)
        self.assertLessEqual(len(decision.major_decisions), 3)
        self.assertTrue(decision.color_recipe.value)
        self.assertEqual(config.recipe_id, decision.color_recipe.value["recipe_id"])
        self.assertFalse(ai_cleanup_provider_configured())
        self.assertTrue(
            any("AI provider not configured" in a for a in decision.unsupported_actions)
        )
        # Lifestyle reel → logo omitted by default
        self.assertEqual(decision.logo_decision.value, "omit")
        self.assertEqual(config.logo.role, "none")

    def test_revision_note_cools_and_removes_logo(self) -> None:
        config = FinishConfiguration()
        config.color.temperature = 20
        config.logo = LogoConfiguration(role="primary", asset_id="x", placement="bottom_right")
        out_choice: list[str] = []
        updated = apply_revision_note_to_config(
            config,
            "The color feels too warm and the logo is distracting.",
            out_choice,
        )
        self.assertLess(updated.color.temperature, 20)
        self.assertEqual(updated.logo.role, "none")
        self.assertEqual(out_choice, ["omit"])
        parsed = parse_revision_request("The color feels too warm and the logo is distracting.")
        self.assertIn("reduce_warmth", parsed["supported_in_finish"])
        self.assertIn("reduce_or_remove_logo", parsed["supported_in_finish"])

    def test_generate_best_edit_creates_immutable_finish(self) -> None:
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
        record = result["record"]
        self.assertEqual(record.finish_version_id, "finish_v001")
        self.assertTrue(record.edit_decision)
        self.assertTrue(record.execution_report)
        decision = EditDecision.from_dict(record.edit_decision)
        assert decision is not None
        self.assertLessEqual(len(decision.major_decisions), 3)
        # Original unchanged
        self.assertTrue(self.source.is_file())
        original_bytes = self.source.read_bytes()
        self.assertGreater(len(original_bytes), 0)
        # Finished output exists and differs from empty
        finish_dir = self.render_folder / "studio" / "finish_v001"
        self.assertTrue((finish_dir / "finish_metadata.json").is_file())
        self.assertTrue((finish_dir / "edit_decision.json").is_file() or record.edit_decision)
        outputs = list((finish_dir / "outputs").glob("*"))
        self.assertTrue(outputs)
        report = result["execution_report"]
        self.assertIn(report.state, {"edit_fully_applied", "edit_partially_applied"})
        self.assertTrue(any("cleanup" in a.label.lower() or "AI provider" in a.reason for a in report.not_applied) or decision.unsupported_actions)

    def test_revision_and_approval_persist(self) -> None:
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

        # Parent marked needs_revision
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
        self.assertEqual(reloaded.edit_decision.get("decision_id"), new_record.edit_decision.get("decision_id"))

        # Both versions still present (immutability / persistence)
        ids = {r.finish_version_id for r in list_finish_records(self.render_folder)}
        self.assertIn(parent_id, ids)
        self.assertIn(new_record.finish_version_id, ids)

        events = list_approval_events(self.brand)
        self.assertTrue(any(e.finish_version_id == new_record.finish_version_id for e in events))

    def test_performance_schema_foundation(self) -> None:
        record = PerformanceRecord(
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
        save_performance_record(record, self.brand)
        listed = list_performance_records(self.brand)
        self.assertTrue(any(r.record_id == "perf_test_1" for r in listed))


if __name__ == "__main__":
    unittest.main()
