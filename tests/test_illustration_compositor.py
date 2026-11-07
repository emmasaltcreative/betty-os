"""Deterministic truth layer: the invariants the brand cannot compromise on."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from illustration import canon, compositor
from illustration.compositor import LabelGeometry
from illustration.models import LayerManifest
from tests.test_illustration_vault import QUATREFOIL_SVG, SIGNATURE_SVG

PRODUCT_ID = "a_woman_remembered_10ml"


class CompositorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name)
        self.flower = self.src / "flower.svg"
        self.flower.write_text(QUATREFOIL_SVG, encoding="utf-8")
        self.signature = self.src / "signature.svg"
        self.signature.write_text(SIGNATURE_SVG, encoding="utf-8")
        canon.reset_cache()
        self.product = canon.product(PRODUCT_ID)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _label(self, height: int = 480):
        manifest = LayerManifest()
        mark = compositor.load_mark(self.flower, target_width=512)
        signature = compositor.load_mark(self.signature, target_width=800)
        geometry = LabelGeometry(
            width=int(height * 1.73), height=height,
            ghost_tile_px=int(height * self.product.label.ghost_tile_ratio),
            margin_px=int(height * 0.06),
        )
        label = compositor.build_label(
            self.product, geometry, mark=mark, signature=signature, manifest=manifest
        )
        return label, manifest, geometry


class MarkTests(CompositorTestCase):
    def test_aspect_ratio_is_never_distorted(self) -> None:
        """The house mark is never stretched to fit a box."""
        for box in [(300, 300), (512, 120), (120, 512)]:
            placed = compositor.load_mark(
                self.signature, target_width=box[0], target_height=box[1]
            )
            self.assertAlmostEqual(
                placed.width / placed.height, 400 / 90, delta=0.1,
                msg=f"signature distorted in box {box}",
            )
            self.assertLessEqual(placed.width, box[0])
            self.assertLessEqual(placed.height, box[1])

    def test_missing_artwork_raises_rather_than_substituting(self) -> None:
        with self.assertRaises(compositor.CompositorError):
            compositor.load_mark(self.src / "nope.svg", target_width=100)

    def test_tint_preserves_alpha(self) -> None:
        mark = compositor.load_mark(self.flower, target_width=128)
        tinted = compositor.tint(mark, "#C9A227")
        self.assertEqual(
            mark.getchannel("A").getextrema(), tinted.getchannel("A").getextrema()
        )


class LabelTests(CompositorTestCase):
    def test_negative_space_is_fully_transparent(self) -> None:
        """Amber glass must show through; alpha is 0 where there is no ink."""
        label, manifest, _ = self._label()
        self.assertEqual(label.getchannel("A").getextrema()[0], 0)
        self.assertEqual(label.getpixel((1, 1))[3], 0)
        base = manifest.find("label_base")
        self.assertTrue(base["transparent"])
        self.assertEqual(base["alpha_in_negative_space"], 0)

    def test_ghost_motif_is_half_alpha_not_a_fill(self) -> None:
        mark = compositor.load_mark(self.flower, target_width=256)
        geometry = LabelGeometry(width=600, height=360, ghost_tile_px=60)
        ghost = compositor.build_ghost_repeat(
            mark, geometry, 0.5, color=self.product.label.ghost_motif_color
        )
        alpha = ghost.getchannel("A")
        self.assertLessEqual(alpha.getextrema()[1], 130)
        self.assertEqual(alpha.getextrema()[0], 0)  # gaps remain transparent

    def test_signature_sits_below_the_edp_text(self) -> None:
        _, manifest, _ = self._label()
        signature = manifest.find("house_signature")
        subtitles = manifest.find("label_subtitles")
        self.assertTrue(signature["below_edp"])
        self.assertGreaterEqual(signature["y"], subtitles["bottom_y"])

    def test_no_notes_line_is_invented(self) -> None:
        _, manifest, _ = self._label()
        notes = manifest.find("label_notes_line")
        self.assertIsNone(notes["text"])
        self.assertTrue(notes["omitted"])
        self.assertFalse(notes["invented"])

    def test_notes_line_is_drawn_when_the_label_really_has_one(self) -> None:
        product = canon.product(PRODUCT_ID)
        product.label.notes_line = "IRIS · ROSE · JASMINE · PEAR"
        manifest = LayerManifest()
        mark = compositor.load_mark(self.flower, target_width=256)
        compositor.build_label(
            product, LabelGeometry(width=800, height=460), mark=mark, manifest=manifest
        )
        self.assertEqual(
            manifest.find("label_notes_line")["text"], "IRIS · ROSE · JASMINE · PEAR"
        )


class BottleTests(CompositorTestCase):
    def test_both_gold_ends_are_rendered_as_layers(self) -> None:
        manifest = LayerManifest()
        _, box = compositor.render_bottle_schematic(self.product, manifest=manifest)
        top = manifest.find("gold_end_top")
        bottom = manifest.find("gold_end_bottom")
        self.assertTrue(top["present"])
        self.assertTrue(bottom["present"])
        self.assertNotEqual(top["mechanism"], bottom["mechanism"])
        self.assertEqual(box[0], 0)

    def test_label_runs_lengthwise_on_an_upright_bottle(self) -> None:
        label, manifest, _ = self._label()
        bottle, box = compositor.render_bottle_schematic(
            self.product, size=(400, 1000), manifest=manifest
        )
        compositor.place_label_lengthwise(
            bottle, label, bottle_box=box, manifest=manifest
        )
        placement = manifest.find("product_label")
        self.assertEqual(placement["orientation"], "lengthwise")
        self.assertEqual(placement["rotated_degrees"], 90)
        self.assertEqual(placement["geometric_accuracy"], "approximate")

    def test_empty_bottle_bounds_are_rejected(self) -> None:
        label, _, _ = self._label()
        base = Image.new("RGBA", (200, 200))
        with self.assertRaises(compositor.CompositorError):
            compositor.place_label_lengthwise(base, label, bottle_box=(10, 10, 10, 10))


class CanvasTests(CompositorTestCase):
    def test_rectangular_source_is_padded_not_stretched(self) -> None:
        source = Image.new("RGB", (1600, 900), (10, 20, 30))
        fitted = compositor.fit_to_canvas(source, "shopify_pdp_square", mode="contain")
        self.assertEqual(fitted.size, (2048, 2048))
        self.assertEqual(fitted.getpixel((5, 5)), (246, 241, 231))

    def test_cover_mode_crops_without_distortion(self) -> None:
        source = Image.new("RGB", (1600, 900), (10, 20, 30))
        fitted = compositor.fit_to_canvas(source, "shopify_pdp_square", mode="cover")
        self.assertEqual(fitted.size, (2048, 2048))
        self.assertEqual(fitted.getpixel((1024, 1024)), (10, 20, 30))

    def test_export_writes_real_decodable_files(self) -> None:
        source = Image.new("RGB", (2048, 2048), (240, 235, 225))
        with tempfile.TemporaryDirectory() as tmp:
            written = compositor.export(
                source, Path(tmp), "OBJ_test_scene_2048_v001", include_webp=True
            )
            for kind, path in written.items():
                self.assertTrue(path.is_file())
                self.assertEqual(path.stem, "OBJ_test_scene_2048_v001")
                with Image.open(path) as img:
                    img.load()
                    self.assertEqual(img.size, (2048, 2048))

    def test_all_canvas_presets_export_at_their_exact_size(self) -> None:
        source = Image.new("RGB", (1200, 1200), (200, 200, 200))
        with tempfile.TemporaryDirectory() as tmp:
            for canvas, expected in compositor.CANVAS_PRESETS.items():
                written = compositor.export(
                    source, Path(tmp), f"OBJ_{canvas}", canvas=canvas
                )
                with Image.open(written["png"]) as img:
                    self.assertEqual(img.size, expected, f"{canvas} wrong size")

    def test_safe_area_margins(self) -> None:
        report = compositor.safe_area_report("shopify_pdp_square", 9.0)
        self.assertEqual(report["left"], 184)
        self.assertEqual(report["right"], 2048 - 184)


class NavigationTests(unittest.TestCase):
    def test_studio_is_contextual_not_a_sidebar_item(self) -> None:
        """The Experience 2 five-destination rule is not widened by this feature."""
        from ui.nav import CONTEXTUAL_DESTINATIONS, ILLUSTRATION_STUDIO, NAV_ITEMS

        self.assertIn(ILLUSTRATION_STUDIO, CONTEXTUAL_DESTINATIONS)
        self.assertNotIn(ILLUSTRATION_STUDIO, NAV_ITEMS)
        self.assertNotIn("Illustration Studio", NAV_ITEMS)


if __name__ == "__main__":
    unittest.main()
