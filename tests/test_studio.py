"""Studio unit tests — persistence, processing, LUT, validation."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from studio.apply_recipe import apply_recipe_to_config
from studio.brand_assets import (
    archive_asset,
    list_assets,
    rename_asset,
    restore_asset,
    upload_brand_asset,
)
from studio.image_pipeline import logo_box, process_static_image
from studio.luts import apply_cube_to_rgb, parse_cube, upload_lut
from studio.models import FinishConfiguration, LogoConfiguration
from studio.package import build_studio_package, output_is_downloadable
from studio.paths import download_basename, sanitize_filename
from studio.recipes import (
    archive_recipe,
    ensure_default_recipes,
    get_recipe,
    list_recipes,
    update_recipe,
)
from studio.service import create_finish, send_to_review
from studio.validation import summarize, validate_config, validate_source
from studio.versions import (
    create_finished_version,
    load_draft,
    load_finish_record,
    next_finish_version_id,
    save_draft,
)
from studio.video_pipeline import build_video_filter_chain, ffmpeg_available


ROOT = Path(__file__).resolve().parent.parent


class StudioPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_studio_"))
        self.brand = f"test_brand_{self.tmp.name}"
        self.brand_dir = ROOT / "brands" / self.brand
        self.brand_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.brand_dir, ignore_errors=True)

    def test_brand_asset_persistence(self) -> None:
        logo = self.tmp / "logo.png"
        Image.new("RGBA", (120, 40), (47, 111, 94, 200)).save(logo)
        record = upload_brand_asset(
            logo,
            brand_id=self.brand,
            display_name="Primary Mark",
            role="primary",
            set_as_default=True,
        )
        listed = list_assets(self.brand)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].display_name, "Primary Mark")
        renamed = rename_asset(record.asset_id, "OBJ Mark", self.brand)
        self.assertEqual(renamed.display_name, "OBJ Mark")
        archive_asset(record.asset_id, self.brand)
        self.assertEqual(list_assets(self.brand), [])
        restore_asset(record.asset_id, self.brand)
        self.assertEqual(len(list_assets(self.brand)), 1)

    def test_recipe_versioning(self) -> None:
        ensure_default_recipes(self.brand)
        recipes = list_recipes(self.brand)
        self.assertGreaterEqual(len(recipes), 10)
        recipe = get_recipe("obj_editorial_lifestyle", self.brand)
        self.assertIsNotNone(recipe)
        assert recipe is not None
        updated = update_recipe(
            recipe.recipe_id,
            self.brand,
            lighting_defaults={**recipe.lighting_defaults, "exposure": 0.5},
        )
        self.assertEqual(updated.version, recipe.version + 1)
        self.assertTrue(updated.history)
        # Prior finished snapshot identity preserved on recipe object history
        self.assertEqual(updated.history[-1]["lighting_defaults"]["exposure"], recipe.lighting_defaults.get("exposure", 0.0))
        archive_recipe(recipe.recipe_id, self.brand)
        active_ids = {r.recipe_id for r in list_recipes(self.brand)}
        self.assertNotIn(recipe.recipe_id, active_ids)

    def test_draft_and_version_ids(self) -> None:
        folder = self.tmp / "render"
        folder.mkdir()
        cfg = FinishConfiguration()
        saved = save_draft(folder, "draft_test", cfg)
        self.assertIsNotNone(load_draft(folder, "draft_test"))
        self.assertEqual(saved["_draft_id"], "draft_test")
        self.assertEqual(next_finish_version_id(folder), "finish_v001")


class StudioImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_img_"))
        self.brand = f"img_brand_{self.tmp.name}"
        (ROOT / "brands" / self.brand / "studio").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(ROOT / "brands" / self.brand, ignore_errors=True)

    def test_logo_position_and_opacity(self) -> None:
        x, y = logo_box((1000, 1500), (180, 60), LogoConfiguration(placement="bottom_right"), safe_margin_px=24)
        self.assertEqual(x, 1000 - 180 - 24)
        self.assertEqual(y, 1500 - 60 - 24)

    def test_safe_margin_top_left(self) -> None:
        x, y = logo_box((800, 800), (100, 40), LogoConfiguration(placement="top_left"), safe_margin_px=32)
        self.assertEqual(x, 32)
        self.assertEqual(y, 32)

    def test_crop_validation(self) -> None:
        src = self.tmp / "src.png"
        Image.new("RGB", (400, 600), (200, 180, 160)).save(src)
        cfg = FinishConfiguration()
        cfg.geometry.crop_left = 0.6
        cfg.geometry.crop_right = 0.4
        items = validate_config(cfg, source=src, brand_id=self.brand, media_type="static", canvas_size=(400, 600))
        self.assertTrue(any(i.code == "crop" and i.outcome == "fail" for i in items))

    def test_static_process_and_immutable_finish(self) -> None:
        src = self.tmp / "editorial.png"
        Image.new("RGB", (600, 900), (230, 220, 210)).save(src)
        # Transparent letterform-style mark — not a solid rectangular badge.
        logo = self.tmp / "mark.png"
        mark = Image.new("RGBA", (160, 48), (0, 0, 0, 0))
        from PIL import ImageDraw

        ImageDraw.Draw(mark).text((8, 12), "OBJ", fill=(20, 80, 60, 230))
        mark.save(logo)
        asset = upload_brand_asset(
            logo, brand_id=self.brand, display_name="Mark", role="primary", set_as_default=True
        )
        ensure_default_recipes(self.brand)
        recipe = get_recipe("obj_editorial_lifestyle", self.brand)
        assert recipe is not None
        cfg = apply_recipe_to_config(recipe)
        cfg.logo.role = "primary"
        cfg.logo.asset_id = asset.asset_id
        cfg.logo.placement = "bottom_right"
        cfg.logo.size_mode = "standard"
        cfg.logo.safe_margin_mode = "pixels"
        cfg.logo.safe_margin_value = 48
        cfg.lighting.exposure = 0.1
        cfg.texture.grain_amount = 8
        cfg.export.format = "png"

        render_folder = self.tmp / "piece"
        render_folder.mkdir()
        # Keep original bytes
        original = src.read_bytes()
        result = create_finish(
            render_folder=render_folder,
            campaign_id="test_campaign",
            content_piece_id="piece_001",
            template_id="editorial_static_pin",
            parent_render_version_id="render_v001",
            parent_finish_version_id=None,
            source_file=src,
            config=cfg,
            brand_id=self.brand,
        )
        self.assertTrue(result.get("ok"), result.get("error"))
        record = result["record"]
        self.assertEqual(record.finish_version_id, "finish_v001")
        self.assertEqual(src.read_bytes(), original)
        out = render_folder / "studio" / "finish_v001" / record.output_files[0]
        self.assertTrue(out.is_file())
        self.assertGreater(out.stat().st_size, 0)
        # Second finish increments
        result2 = create_finish(
            render_folder=render_folder,
            campaign_id="test_campaign",
            content_piece_id="piece_001",
            template_id="editorial_static_pin",
            parent_render_version_id="render_v001",
            parent_finish_version_id="finish_v001",
            source_file=src,
            config=cfg,
            brand_id=self.brand,
        )
        self.assertTrue(result2.get("ok"), result2.get("error"))
        self.assertEqual(result2["record"].finish_version_id, "finish_v002")
        # Immutable: finish_v001 still intact
        self.assertTrue((render_folder / "studio" / "finish_v001" / "finish_metadata.json").is_file())
        send = send_to_review(render_folder, "finish_v001")
        self.assertTrue(send.get("ok"))
        self.assertEqual(send["record"].status, "ready_for_review")

    def test_filename_sanitation(self) -> None:
        self.assertEqual(sanitize_filename("../evil name!!.png"), "evil_name_.png")
        name = download_basename("camp/a", "piece b", "OBJ Editorial", "finish_v001", ".png")
        self.assertNotIn("/", name)
        self.assertTrue(name.endswith(".png"))


class StudioLutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_lut_"))
        self.brand = f"lut_brand_{self.tmp.name}"
        (ROOT / "brands" / self.brand / "studio").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(ROOT / "brands" / self.brand, ignore_errors=True)

    def _write_identity_cube(self, path: Path, size: int = 2) -> None:
        lines = ["TITLE \"Identity\"", f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    lines.append(
                        f"{r / (size - 1):.6f} {g / (size - 1):.6f} {b / (size - 1):.6f}"
                    )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_parse_and_apply(self) -> None:
        path = self.tmp / "id.cube"
        self._write_identity_cube(path, 3)
        cube = parse_cube(path)
        self.assertEqual(cube.size, 3)
        rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
        out = apply_cube_to_rgb(rgb, cube, intensity=1.0)
        self.assertTrue(np.allclose(out, 0.5, atol=0.05))

    def test_invalid_lut_rejection(self) -> None:
        bad = self.tmp / "bad.cube"
        bad.write_text("not a lut\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            parse_cube(bad)
        record = upload_lut(bad, brand_id=self.brand, display_name="Bad")
        self.assertEqual(record.status, "Invalid File")


class StudioVideoCommandTests(unittest.TestCase):
    def test_filter_chain_includes_eq(self) -> None:
        cfg = FinishConfiguration()
        cfg.video.brightness = 10
        cfg.video.contrast = 1.1
        cfg.video.saturation = 1.0
        filters, _ = build_video_filter_chain(
            cfg,
            brand_id="oh_betty_jaletti",
            meta={"duration": 5.0, "width": 1080, "height": 1920, "logo_xy": (10, 10)},
            logo_png=None,
        )
        joined = ";".join(filters)
        self.assertIn("eq=", joined)

    def test_ffmpeg_failure_handling(self) -> None:
        from studio.video_pipeline import process_video

        if not ffmpeg_available():
            self.skipTest("ffmpeg unavailable")
        tmp = Path(tempfile.mkdtemp())
        try:
            bogus = tmp / "missing.mp4"
            result = process_video(
                bogus,
                FinishConfiguration(),
                brand_id="oh_betty_jaletti",
                output_path=tmp / "out.mp4",
                work_dir=tmp,
            )
            self.assertFalse(result.get("ok"))
            self.assertIn("error", result)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class StudioSourceValidationTests(unittest.TestCase):
    def test_missing_source(self) -> None:
        items = validate_source(Path("/tmp/does_not_exist_betty.png"))
        self.assertEqual(summarize(items)["outcome"], "fail")

    def test_corrupt_image(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            bad = tmp / "bad.png"
            bad.write_bytes(b"not-an-image")
            items = validate_source(bad)
            self.assertEqual(summarize(items)["outcome"], "fail")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_download_existence(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            folder = tmp / "render"
            (folder / "studio" / "finish_v001" / "outputs").mkdir(parents=True)
            out = folder / "studio" / "finish_v001" / "outputs" / "finished.png"
            Image.new("RGB", (10, 10), (1, 2, 3)).save(out)
            from studio.models import FinishRecord
            from studio.models import utc_now_iso

            now = utc_now_iso()
            record = FinishRecord(
                finish_version_id="finish_v001",
                campaign_id="c",
                content_piece_id="p",
                template_id="t",
                parent_render_version_id="render_v001",
                parent_finish_version_id=None,
                source_asset_id=None,
                source_output_id=None,
                source_file="x.png",
                media_type="static",
                recipe_id=None,
                recipe_version=1,
                logo_configuration={},
                lighting_configuration={},
                color_configuration={},
                texture_configuration={},
                geometry_configuration={},
                lut_configuration={},
                export_configuration={},
                video_configuration={},
                output_files=["outputs/finished.png"],
                preview_files=[],
                validation_results={},
                status="draft",
                approval_status="not_submitted",
                created_at=now,
                updated_at=now,
            )
            self.assertIsNotNone(output_is_downloadable(folder, record))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
