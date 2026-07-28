"""Acceptance-oriented tests for Sprint 15 template + persistence flows."""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from renderers.copy import render_copy_template
from renderers.static import render_static_template
from src.templates.approvals_store import load_campaign_approvals, upsert_approval
from src.templates.assignments import load_assignments, set_piece_template
from src.templates.migration import migrate_campaign
from src.templates.pieces import parse_content_piece_records

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceTests(unittest.TestCase):
    def test_parse_pieces_and_assign_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "pkg_content_package.md"
            package.write_text(
                """
# Package
### Piece 1 — A book you have been saving
**Platform:** Instagram Reels (9:16)
**Objective:** Waitlist
**Exact Asset File Paths:**
- `assets/reading-hour-shoot/IMG_2545.mov`
- `assets/reading-hour-shoot/IMG_2547.mov`
**Suggested Format:** Reels (9:16, vertical)
""",
                encoding="utf-8",
            )
            pieces = parse_content_piece_records(package.read_text(encoding="utf-8"))
            self.assertEqual(len(pieces), 1)
            self.assertTrue(pieces[0].piece_id.startswith("piece_001_"))
            set_piece_template(
                package,
                piece_id=pieces[0].piece_id,
                template_id="cinematic_multi_clip_reel",
                override=True,
            )
            saved = load_assignments(package)
            self.assertEqual(
                saved["pieces"][pieces[0].piece_id]["template_id"],
                "cinematic_multi_clip_reel",
            )

    def test_static_and_copy_render_produce_outputs(self) -> None:
        asset = ROOT / "assets" / "reading-hour-shoot" / "IMG_2545.mov"
        if not asset.exists():
            self.skipTest("source asset missing")
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "acc_campaign"
            campaign.mkdir()
            static = render_static_template(
                template_id="editorial_static_pin",
                content_piece_id="piece_001_test",
                source_assets=["assets/reading-hour-shoot/IMG_2545.mov"],
                campaign_dir=campaign,
                copy_fields={
                    "headline": "The Reading Hour",
                    "cta_text": "Join the waitlist",
                },
            )
            self.assertTrue(static["ok"])
            self.assertTrue(Path(static["outputs"][0]).is_file())

            copy = render_copy_template(
                template_id="instagram_caption",
                content_piece_id="piece_001_test",
                campaign_dir=campaign,
                copy_fields={
                    "caption": "A book you've been saving.",
                    "cta_text": "Join the waitlist",
                },
                title="A book you have been saving",
            )
            self.assertTrue(copy["ok"])
            self.assertTrue(Path(copy["outputs"][0]).is_file())

    def test_carousel_render(self) -> None:
        from renderers.carousel import render_carousel_template

        asset = ROOT / "assets" / "reading-hour-shoot" / "IMG_2545.mov"
        if not asset.exists():
            self.skipTest("source asset missing")
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "acc_campaign"
            campaign.mkdir()
            result = render_carousel_template(
                template_id="editorial_carousel",
                content_piece_id="piece_002_test",
                source_assets=["assets/reading-hour-shoot/IMG_2545.mov"],
                campaign_dir=campaign,
                copy_fields={"headline": "The Reading Hour", "cta_text": "Join the waitlist"},
            )
            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(result["outputs"]), 3)

    def test_approval_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "acc_campaign"
            campaign.mkdir()
            upsert_approval(
                campaign,
                asset_id="piece_001_test",
                template_id="editorial_static_pin",
                render_version_id="v1",
                status="needs_revision",
                note="Move CTA earlier",
                file_path="editorial_static_pin/piece_001_test",
            )
            again = load_campaign_approvals(campaign)
            self.assertEqual(again["items"][0]["status"], "needs_revision")
            self.assertEqual(again["items"][0]["note"], "Move CTA earlier")

    def test_migration_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "mig_campaign"
            ritual = campaign / "ritual_reel"
            ritual.mkdir(parents=True)
            (ritual / "ritual_reel_draft.mp4").write_bytes(b"fake-video")
            (ritual / "caption.md").write_text("caption", encoding="utf-8")
            report = migrate_campaign(campaign)
            self.assertTrue(
                any(m["template_id"] == "cinematic_multi_clip_reel" for m in report["migrated"])
            )
            self.assertTrue((campaign / "ritual_reel" / "ritual_reel_draft.mp4").exists())
            self.assertTrue(
                (campaign / "cinematic_multi_clip_reel" / "ritual_reel_draft.mp4").exists()
            )


if __name__ == "__main__":
    unittest.main()
