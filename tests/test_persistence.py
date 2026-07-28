"""Persistence tests independent of Streamlit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.persistence import atomic_write_json, load_json
from src.templates.approvals_store import (
    load_campaign_approvals,
    upsert_approval,
    write_campaign_approvals,
)
from src.templates.assignments import load_assignments, set_piece_template
from src.templates.classifier import classify_content_piece
from src.templates.models import ContentPieceRecord
from src.templates.registry import get_template, list_templates


class PersistenceTests(unittest.TestCase):
    def test_atomic_write_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            atomic_write_json(path, {"ok": True, "n": 1})
            data = load_json(path)
            self.assertEqual(data, {"ok": True, "n": 1})

    def test_atomic_write_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            atomic_write_json(path, {"v": 1})
            atomic_write_json(path, {"v": 2})
            self.assertEqual(load_json(path)["v"], 2)

    def test_approval_upsert_persists_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            saved = upsert_approval(
                campaign,
                asset_id="piece_001",
                template_id="editorial_static_pin",
                render_version_id="v1",
                status="needs_revision",
                note="CTA too late",
                file_path="editorial_static_pin/piece_001",
            )
            self.assertEqual(saved["status"], "needs_revision")
            self.assertEqual(saved["note"], "CTA too late")
            self.assertEqual(saved["campaign_id"], "demo_campaign")
            reloaded = load_campaign_approvals(campaign)
            self.assertEqual(len(reloaded["items"]), 1)
            self.assertEqual(reloaded["items"][0]["status"], "needs_revision")

    def test_approval_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            write_campaign_approvals(
                campaign,
                {
                    "items": [
                        {
                            "asset_id": "a1",
                            "template_id": "instagram_caption",
                            "render_version_id": "v1",
                            "status": "approved",
                            "note": "",
                            "file_path": "instagram_caption/a1",
                        }
                    ]
                },
            )
            data = json.loads((campaign / "approvals.json").read_text())
            item = data["items"][0]
            for key in (
                "campaign_id",
                "asset_id",
                "template_id",
                "render_version_id",
                "status",
                "note",
                "updated_at",
            ):
                self.assertIn(key, item)

    def test_piece_template_override_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "2026_demo_content_package.md"
            package.write_text("# demo\n", encoding="utf-8")
            set_piece_template(
                package,
                piece_id="piece_001_demo",
                template_id="editorial_static_pin",
                override=True,
            )
            data = load_assignments(package)
            self.assertEqual(
                data["pieces"]["piece_001_demo"]["template_id"],
                "editorial_static_pin",
            )
            self.assertTrue(data["pieces"]["piece_001_demo"]["override"])

    def test_classifier_assigns_canonical_template_not_title(self) -> None:
        piece = ContentPieceRecord(
            piece_id="piece_001",
            title="A book you have been saving",
            platform="Instagram Reels (9:16)",
            format="Reels (9:16, vertical)",
            objective="Drive waitlist",
            source_assets=[
                "assets/reading-hour-shoot/IMG_2545.mov",
                "assets/reading-hour-shoot/IMG_2547.mov",
            ],
            body_markdown="**Platform:** Instagram Reels",
            number="1",
        )
        result = classify_content_piece(piece)
        self.assertEqual(result.primary_template_id, "cinematic_multi_clip_reel")
        self.assertNotEqual(result.primary_template_id, piece.title)
        self.assertGreater(result.confidence, 0)
        self.assertLessEqual(result.confidence, 1)

    def test_registry_has_thirty_templates(self) -> None:
        templates = list_templates()
        self.assertEqual(len(templates), 30)
        ready = [t for t in templates if t.renderer_status == "ready"]
        self.assertGreaterEqual(len(ready), 17)
        self.assertIsNotNone(get_template("cinematic_multi_clip_reel"))
        self.assertIsNotNone(get_template("editorial_static_pin"))


if __name__ == "__main__":
    unittest.main()
