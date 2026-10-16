"""Active Settings logo — source of truth, suitability, and package lineage."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common import DEFAULT_BRAND_ID
from services.active_logo import (
    clear_active_brand_mark,
    evaluate_logo_suitability,
    resolve_active_logo,
    set_active_brand_mark,
)
from studio.brand_assets import (
    analyze_mark_pixels,
    is_suitable_transparent_mark,
    select_best_logo_asset,
    upload_brand_asset,
)
from studio.paths import brand_assets_dir, brand_assets_index


class LogoSuitabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_logo_suit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_plain_jade_rectangle_fails(self) -> None:
        seed = (
            ROOT
            / "brands"
            / DEFAULT_BRAND_ID
            / "studio"
            / "assets"
            / "ba_12a2e9d21f_seed_logo.png"
        )
        if not seed.is_file():
            self.skipTest("seed missing")
        result = evaluate_logo_suitability(seed)
        self.assertFalse(result.suitable)
        self.assertEqual(result.severity, "blocking")
        analysis = analyze_mark_pixels(seed)
        self.assertTrue(analysis["looks_like_solid_rectangle"])

    def test_nearly_uniform_color_fails(self) -> None:
        path = self.tmp / "flat.png"
        Image.new("RGBA", (200, 80), (36, 108, 84, 255)).save(path)
        result = evaluate_logo_suitability(path)
        self.assertFalse(result.suitable)

    def test_corrupt_image_fails(self) -> None:
        path = self.tmp / "corrupt.png"
        path.write_bytes(b"not-an-image")
        result = evaluate_logo_suitability(path)
        self.assertFalse(result.suitable)

    def test_empty_transparent_image_fails(self) -> None:
        path = self.tmp / "empty.png"
        Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(path)
        result = evaluate_logo_suitability(path)
        self.assertFalse(result.suitable)

    def test_plain_svg_rect_fails(self) -> None:
        path = self.tmp / "rect.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40">'
            '<rect x="0" y="0" width="100" height="40" fill="#246c54"/></svg>',
            encoding="utf-8",
        )
        result = evaluate_logo_suitability(path)
        self.assertFalse(result.suitable)

    def test_valid_svg_mark_passes(self) -> None:
        svg = (
            ROOT
            / "brands"
            / DEFAULT_BRAND_ID
            / "studio"
            / "assets"
            / "ba_1ce4b91d16_oh_betty_jaletti_four_petal_mark_knockout.svg"
        )
        if not svg.is_file():
            self.skipTest("Settings logo missing")
        result = evaluate_logo_suitability(svg)
        self.assertTrue(result.suitable)

    def test_suitability_not_filename_based(self) -> None:
        path = self.tmp / "official_logo.png"
        Image.new("RGBA", (200, 80), (36, 108, 84, 255)).save(path)
        result = evaluate_logo_suitability(path)
        self.assertFalse(result.suitable)


class ActiveLogoResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brand_id = f"test_brand_{self.id().split('.')[-1]}"
        self.assets_dir = brand_assets_dir(self.brand_id)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.index = brand_assets_index(self.brand_id)

    def tearDown(self) -> None:
        brand_root = ROOT / "brands" / self.brand_id
        shutil.rmtree(brand_root, ignore_errors=True)

    def _upload_valid_png(self, name: str = "mark.png") -> str:
        path = self.assets_dir / name
        # Transparent mark with varied pixels (not a solid rectangle).
        img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        for i in range(20, 100):
            for j in range(20, 100):
                if (i + j) % 3 == 0:
                    img.putpixel((i, j), (40, 40, 50, 255))
                elif (i * j) % 5 == 0:
                    img.putpixel((i, j), (80, 70, 60, 230))
        path.write_bytes(b"")  # placeholder; overwrite via save
        img.save(path)
        record = upload_brand_asset(
            path,
            brand_id=self.brand_id,
            display_name="Test Mark",
            role="emblem",
            set_as_default=True,
            original_filename=name,
        )
        return record.asset_id

    def test_valid_upload_can_be_selected_and_persists(self) -> None:
        asset_id = self._upload_valid_png()
        mark = set_active_brand_mark(asset_id, brand_id=self.brand_id)
        self.assertEqual(mark.asset_id, asset_id)
        self.assertTrue(mark.suitable)
        # Simulate restart — reload from disk.
        again = resolve_active_logo(self.brand_id, bootstrap=False)
        self.assertIsNotNone(again)
        self.assertEqual(again.asset_id, asset_id)
        data = json.loads(self.index.read_text(encoding="utf-8"))
        self.assertEqual(data.get("active_brand_mark_id"), asset_id)

    def test_invalid_replacement_does_not_displace_valid(self) -> None:
        asset_id = self._upload_valid_png()
        set_active_brand_mark(asset_id, brand_id=self.brand_id)
        flat = self.assets_dir / "flat.png"
        Image.new("RGBA", (200, 80), (36, 108, 84, 255)).save(flat)
        bad = upload_brand_asset(
            flat,
            brand_id=self.brand_id,
            display_name="Flat Jade",
            role="primary",
            set_as_default=False,
            original_filename="flat.png",
        )
        with self.assertRaises(ValueError):
            set_active_brand_mark(bad.asset_id, brand_id=self.brand_id)
        still = resolve_active_logo(self.brand_id, bootstrap=False)
        self.assertEqual(still.asset_id, asset_id)

    def test_jade_only_library_selects_none(self) -> None:
        seed = (
            ROOT
            / "brands"
            / DEFAULT_BRAND_ID
            / "studio"
            / "assets"
            / "ba_12a2e9d21f_seed_logo.png"
        )
        if not seed.is_file():
            self.skipTest("seed missing")
        # Copy seed into isolated brand index via upload.
        record = upload_brand_asset(
            seed,
            brand_id=self.brand_id,
            display_name="Seed Jade",
            role="primary",
            set_as_default=True,
            original_filename="seed_logo.png",
        )
        self.assertFalse(is_suitable_transparent_mark(record))
        self.assertIsNone(select_best_logo_asset(self.brand_id))
        clear_active_brand_mark(self.brand_id)
        self.assertIsNone(resolve_active_logo(self.brand_id, bootstrap=True))


class BrandCheckLogoTests(unittest.TestCase):
    def test_omit_passes_when_rules_specify_no_logo(self) -> None:
        from services.brand_compliance import evaluate_brand_compliance

        report = evaluate_brand_compliance(
            copy_text="Quiet recognition.",
            logo_required=False,
            expects_video=False,
        )
        keys = {i.key for i in report.items}
        self.assertIn("brand_mark_omit", keys)
        self.assertFalse(any(i.key == "brand_mark_missing" and i.severity == "blocking" for i in report.items))

    def test_required_missing_blocks(self) -> None:
        from services.brand_compliance import evaluate_brand_compliance

        with patch("services.active_logo.resolve_active_logo", return_value=None):
            report = evaluate_brand_compliance(
                copy_text="Product shot",
                logo_required=True,
                expects_video=False,
            )
        self.assertTrue(report.blocking)


class DocumentLogoTests(unittest.TestCase):
    def test_overview_pdf_and_docx_embed_active_logo(self) -> None:
        from src.campaign_delivery.documents import build_copybook_documents, build_overview_documents
        from services.active_logo import resolve_active_logo, rasterize_logo_png

        mark = resolve_active_logo(DEFAULT_BRAND_ID, bootstrap=True)
        if mark is None or not mark.suitable:
            self.skipTest("No active Settings logo")
        png = rasterize_logo_png(mark)
        if png is None:
            self.skipTest("Could not rasterize active logo")

        state = type("S", (), {"name": "Reading Hour Waitlist", "goal": "Waitlist", "stage": "decide"})()
        plan = type("P", (), {"included": []})()
        docs = build_overview_documents(state, plan)
        self.assertTrue(any(n.endswith(".pdf") for n, _ in docs))
        pdf_bytes = next(b for n, b in docs if n.endswith(".pdf"))
        self.assertGreater(len(pdf_bytes), 1000)
        # PDF should reference an image XObject when logo is embedded.
        self.assertIn(b"/XObject", pdf_bytes)

        copybook = build_copybook_documents(state, plan)
        docx = next((b for n, b in copybook if n.endswith(".docx")), None)
        self.assertIsNotNone(docx)
        import zipfile
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(docx)) as zf:
            self.assertIn("word/media/logo.png", zf.namelist())


def _zip_names(payload: bytes) -> list[str]:
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(payload)) as zf:
        return list(zf.namelist())


if __name__ == "__main__":
    unittest.main()
