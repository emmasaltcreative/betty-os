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


class LogoTreatmentRegressionTests(unittest.TestCase):
    """Current-draft case: Oh Betty seed jade badge must never auto-apply."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_logo_reg_"))
        self.source = self.tmp / "reading_hour.png"
        Image.new("RGB", (1080, 1920), (228, 219, 205)).save(self.source)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seed_jade_rectangle_is_not_a_suitable_mark(self) -> None:
        from studio.brand_assets import analyze_mark_pixels, select_best_logo_asset

        seed = (
            ROOT
            / "brands"
            / DEFAULT_BRAND_ID
            / "studio"
            / "assets"
            / "ba_12a2e9d21f_seed_logo.png"
        )
        if not seed.is_file():
            self.skipTest("Oh Betty seed logo missing")
        analysis = analyze_mark_pixels(seed)
        self.assertTrue(analysis["looks_like_solid_rectangle"])
        self.assertFalse(analysis["suitable_transparent_mark"])
        self.assertIsNone(select_best_logo_asset(DEFAULT_BRAND_ID))

    def test_current_instagram_reel_draft_omits_jade_badge(self) -> None:
        """Regression: Reading Hour Instagram Reels draft must omit the jade badge."""
        decision, config = build_edit_decision(
            brand_id=DEFAULT_BRAND_ID,
            campaign_id="2026-07-27_191825_campaign",
            content_piece_id="piece_001_the_part_of_the_day_that_s_yours",
            template_id="cinematic_multi_clip_reel",
            platform="Instagram Reels (9:16)",
            campaign_goal=(
                "Grow a qualified waitlist for First Edition: The Reading Hour "
                "by making the reading ritual feel recognized, specific, and worth waiting for."
            ),
            piece_objective="The part of the day that's yours",
            piece_format="Instagram Reels (9:16)",
            media_type="static",
            source_file=self.source,
            overlay_copy="The part of the day that's yours.",
        )
        self.assertEqual(decision.logo_decision.value, "omit")
        self.assertEqual(config.logo.role, "none")
        self.assertIsNone(config.logo.asset_id)
        self.assertNotIn("ba_12a2e9d21f", str(config.logo.to_dict()))

    def test_editorial_pin_omits_when_only_badge_exists(self) -> None:
        from studio.auto_edit import decide_logo

        choice, reason, _source, logo = decide_logo(
            brand_id=DEFAULT_BRAND_ID,
            platform="Pinterest (2:3)",
            content_type="editorial_pin",
            campaign_goal="Grow waitlist",
            piece_objective="Still life, reading hour",
            overlay_mentions_brand=False,
            findings=[],
        )
        self.assertEqual(choice, "omit")
        self.assertEqual(logo.role, "none")
        self.assertTrue(
            "transparent" in reason.lower()
            or "badge" in reason.lower()
            or "composition" in reason.lower()
            or "atmosphere" in reason.lower()
        )

    def test_brand_named_in_copy_omits_logo(self) -> None:
        from studio.auto_edit import decide_logo

        choice, reason, _source, logo = decide_logo(
            brand_id=DEFAULT_BRAND_ID,
            platform="Instagram Reels",
            content_type="lifestyle_reel",
            campaign_goal="Grow waitlist",
            piece_objective="Evening ritual",
            overlay_mentions_brand=True,
            findings=[],
        )
        self.assertEqual(choice, "omit")
        self.assertEqual(logo.role, "none")
        self.assertIn("named", reason.lower())

    def test_brand_guardian_rejects_badge_and_tight_margin(self) -> None:
        from studio.models import FinishConfiguration, LogoConfiguration
        from studio.validation import validate_logo

        seed_id = "ba_12a2e9d21f"
        cfg = FinishConfiguration()
        cfg.logo = LogoConfiguration(
            role="primary",
            asset_id=seed_id,
            placement="bottom_right",
            size_mode="subtle",
            safe_margin_mode="pixels",
            safe_margin_value=12,
        )
        items = validate_logo(
            cfg,
            brand_id=DEFAULT_BRAND_ID,
            canvas_size=(1080, 1920),
            duration=None,
            media_type="static",
            source=self.source,
        )
        codes = {i.code for i in items if i.outcome == "fail"}
        self.assertIn("brand_guardian_logo_badge", codes)
        self.assertTrue(
            "brand_guardian_logo_edge" in codes or "brand_guardian_unreadable_logo" in codes
        )

    def test_suitable_transparent_wordmark_can_still_apply_for_product(self) -> None:
        from studio.auto_edit import decide_logo
        from studio.brand_assets import upload_brand_asset
        from PIL import ImageDraw

        brand = f"logo_ok_{self.tmp.name}"
        brand_dir = ROOT / "brands" / brand
        brand_dir.mkdir(parents=True, exist_ok=True)
        try:
            mark = self.tmp / "wordmark.png"
            img = Image.new("RGBA", (220, 64), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((10, 18), "Oh Betty", fill=(30, 30, 30, 255))
            img.save(mark)
            upload_brand_asset(
                mark,
                brand_id=brand,
                display_name="Wordmark",
                role="wordmark",
                set_as_default=True,
            )
            choice, _reason, _source, logo = decide_logo(
                brand_id=brand,
                platform="Email",
                content_type="product",
                campaign_goal="Sell the collection",
                piece_objective="Product hero",
                overlay_mentions_brand=False,
                findings=[],
            )
            self.assertEqual(choice, "required")
            self.assertEqual(logo.role, "wordmark")
            self.assertIsNotNone(logo.asset_id)
            self.assertGreaterEqual(logo.safe_margin_value, 48)
        finally:
            shutil.rmtree(brand_dir, ignore_errors=True)

    def test_omit_finish_pixels_have_no_solid_jade_bottom_right(self) -> None:
        """When logo omission is selected, finished pixels must not contain the jade badge."""
        from studio.image_pipeline import process_static_image
        from studio.models import FinishConfiguration, LogoConfiguration
        from studio.overlay_diagnostics import overlay_events

        out = self.tmp / "omit_finished.png"
        cfg = FinishConfiguration()
        cfg.logo = LogoConfiguration(role="none")
        result = process_static_image(
            self.source,
            cfg,
            brand_id=DEFAULT_BRAND_ID,
            output_path=out,
            preview_path=self.tmp / "omit_preview.jpg",
        )
        self.assertTrue(result.get("ok"))
        self.assertTrue(out.is_file())
        jade_frac = _bottom_right_jade_fraction(out)
        self.assertLess(
            jade_frac,
            0.01,
            f"Solid jade rectangle still present in bottom-right (frac={jade_frac:.4f})",
        )
        applied = [e for e in overlay_events() if e.applied and e.kind == "logo"]
        self.assertEqual(applied, [])

    def test_pipeline_hard_blocks_seed_jade_badge_even_if_config_requests_it(self) -> None:
        """Pixel path must refuse ba_12a2e9d21f even when an old finish config asks for it."""
        from studio.image_pipeline import process_static_image
        from studio.models import FinishConfiguration, LogoConfiguration
        from studio.overlay_diagnostics import overlay_events

        # Baseline: compositing the seed onto cream would leave a dense jade block.
        out = self.tmp / "blocked_finished.png"
        cfg = FinishConfiguration()
        cfg.logo = LogoConfiguration(
            role="primary",
            asset_id="ba_12a2e9d21f",
            placement="bottom_right",
            size_mode="subtle",
            opacity=0.8,
        )
        result = process_static_image(
            self.source,
            cfg,
            brand_id=DEFAULT_BRAND_ID,
            output_path=out,
        )
        self.assertTrue(result.get("ok"))
        jade_frac = _bottom_right_jade_fraction(out)
        self.assertLess(
            jade_frac,
            0.01,
            f"Hard-block failed; jade badge written (frac={jade_frac:.4f})",
        )
        skipped = [
            e
            for e in overlay_events()
            if e.kind == "skipped_logo" and e.asset_id == "ba_12a2e9d21f"
        ]
        self.assertTrue(skipped, "Expected diagnostic skip for seed badge")
        self.assertFalse(any(e.applied and e.kind == "logo" for e in overlay_events()))


def _bottom_right_jade_fraction(path: Path, *, jade=(47, 111, 94), tol: float = 35.0) -> float:
    import numpy as np

    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w, _ = img.shape
    region = img[int(h * 0.88) :, int(w * 0.82) :]
    dist = np.linalg.norm(region - np.array(jade, dtype=np.float32), axis=-1)
    return float((dist < tol).mean())
