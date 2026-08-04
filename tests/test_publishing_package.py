"""Decisive publishing package — selection, validation, structure, modes."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from ui.campaign_state import RenderVersion
from ui.export_service import (
    ARCHIVE_MODE,
    PUBLISHING_MODE,
    build_plan,
    create_export_package,
    normalize_mode,
)
from ui.publishing_validation import (
    file_sha256,
    validate_carousel_slides,
    validate_copy_text,
    validate_media_file,
    validate_pinterest_metadata_text,
)


ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = ROOT / "outputs" / "2026-07-27_191825_campaign"


def _version(
    *,
    template_id: str,
    folder: Path,
    version: int = 1,
    kind: str = "image",
    piece_id: str | None = "piece_001",
    approval_status: str = "approved",
    media: list[Path] | None = None,
    support: list[Path] | None = None,
    display_name: str | None = None,
) -> RenderVersion:
    media_files = list(media or [])
    support_files = list(support or [])
    primary = media_files[0] if media_files else (support_files[0] if support_files else None)
    return RenderVersion(
        template_id=template_id,
        display_name=display_name or template_id.replace("_", " ").title(),
        folder=folder,
        piece_id=piece_id,
        version=version,
        kind=kind,
        primary_path=primary,
        media_files=media_files,
        support_files=support_files,
        approval_status=approval_status,
        is_latest=True,
    )


def _write_png(path: Path, color=(20, 40, 60), size=(100, 150)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _state(versions: list[RenderVersion], *, tmp: Path, pieces=None):
    from ui.campaign_state import CampaignState, NextStep

    piece_mocks = pieces or []
    return CampaignState(
        path=tmp,
        name="Test Campaign",
        goal="Ship clean packages",
        package_path=None,
        package_name="",
        platforms=["Instagram", "Pinterest"],
        pieces=piece_mocks,
        versions=versions,
        stage="approved",
        blockers=[],
        next_step=NextStep("Deliver", "workspace", ""),
        steps=[],
        activity=[],
        created_at="—",
        updated_at="—",
        revision_counts={},
        review_is_current=False,
        has_review=False,
        export_count=0,
    )


class PublishingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_pub_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_incomplete_copy_rejection(self) -> None:
        result = validate_copy_text("", required=True)
        self.assertFalse(result.ok)

    def test_internal_production_note_rejection(self) -> None:
        text = "Extract a frame from assets/reading-hour-shoot/IMG_2545.mov later."
        result = validate_copy_text(text, required=True)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "production_notes" for i in result.issues))

    def test_pinterest_blank_description(self) -> None:
        text = "# Pinterest Pin Description\n\n**Title:** Hello\n\n**Description:**\n\n**CTA:** Go\n"
        result = validate_pinterest_metadata_text(text)
        self.assertFalse(result.ok)

    def test_missing_file_handling(self) -> None:
        result = validate_media_file(self.tmp / "missing.png", expect="image")
        self.assertFalse(result.ok)
        self.assertEqual(result.blockers[0].code, "missing_file")

    def test_carousel_slide_ordering_helper(self) -> None:
        a = _write_png(self.tmp / "slide2.png", (1, 2, 3))
        b = _write_png(self.tmp / "slide1.png", (4, 5, 6))
        c = _write_png(self.tmp / "slide3.png", (7, 8, 9))
        from ui.export_service import _ordered_carousel_slides

        ordered = _ordered_carousel_slides([a, b, c])
        self.assertEqual([p.name for p in ordered], ["slide1.png", "slide2.png", "slide3.png"])
        self.assertTrue(validate_carousel_slides(ordered).ok)


class PublishingSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_sel_"))
        self.folder = self.tmp / "text_led_editorial_pin" / "piece_001"
        self.folder.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_final_version_per_content_piece(self) -> None:
        v1 = _version(
            template_id="text_led_editorial_pin",
            folder=self.folder,
            version=1,
            media=[_write_png(self.folder / "pin_v1.png", (10, 10, 10))],
            support=[_write_text(self.folder / "caption_v1.md", "Warm caption for the pin.")],
        )
        v2 = _version(
            template_id="text_led_editorial_pin",
            folder=self.folder,
            version=2,
            media=[_write_png(self.folder / "pin_v2.png", (20, 20, 20))],
            support=[_write_text(self.folder / "caption_v2.md", "Newer warm caption for the pin.")],
        )
        state = _state([v1, v2], tmp=self.tmp)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        pins = [i for i in plan.included if i.summary_kind == "pin"]
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0].render_version_id, "render_v002")
        self.assertTrue(any(e.category == "superseded" for e in plan.excluded))

    def test_approved_render_fallback(self) -> None:
        media = _write_png(self.folder / "pin_v1.png")
        caption = _write_text(self.folder / "caption_v1.md", "A clean publishable caption.")
        version = _version(
            template_id="text_led_editorial_pin",
            folder=self.folder,
            media=[media],
            support=[caption],
        )
        state = _state([version], tmp=self.tmp)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        self.assertEqual(len(plan.included), 1)
        self.assertIsNone(plan.included[0].finish_version_id)
        self.assertEqual(plan.included[0].render_version_id, "render_v001")

    def test_orphaned_metadata_exclusion(self) -> None:
        meta = _write_text(
            self.folder / "meta_v1.md",
            "# Pinterest Pin Description\n\n**Title:** Solo\n\n**Description:**\n\n"
            "A real description without instructions.\n\n**CTA:** Join\n",
        )
        version = _version(
            template_id="pinterest_caption_metadata",
            folder=self.folder,
            kind="copy",
            piece_id="piece_orphan",
            media=[],
            support=[meta],
            display_name="Pinterest Caption & Metadata",
        )
        state = _state([version], tmp=self.tmp)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        self.assertEqual(plan.included, [])
        self.assertTrue(
            any("No matching final visual asset" in e.reason for e in plan.excluded)
        )
        self.assertTrue(any(e.category == "orphaned" for e in plan.excluded))

    def test_approved_only_enforcement(self) -> None:
        media = _write_png(self.folder / "pin_v1.png")
        version = _version(
            template_id="text_led_editorial_pin",
            folder=self.folder,
            media=[media],
            support=[_write_text(self.folder / "caption_v1.md", "Ready caption.")],
            approval_status="needs_revision",
        )
        state = _state([version], tmp=self.tmp)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        self.assertEqual(plan.included, [])
        self.assertTrue(any("revision" in e.reason.lower() for e in plan.excluded))

    def test_hash_based_duplicate_removal(self) -> None:
        shared = _write_png(self.folder / "shared.png", (9, 9, 9))
        other_folder = self.tmp / "editorial_static_pin" / "piece_002"
        other_folder.mkdir(parents=True)
        duplicate = other_folder / "dup.png"
        shutil.copy2(shared, duplicate)
        caption = _write_text(self.folder / "caption.md", "Shared caption text is fine.")
        caption2 = _write_text(other_folder / "caption.md", "Another caption text is fine.")
        v1 = _version(
            template_id="text_led_editorial_pin",
            folder=self.folder,
            piece_id="piece_001",
            media=[shared],
            support=[caption],
        )
        v2 = _version(
            template_id="editorial_static_pin",
            folder=other_folder,
            piece_id="piece_002",
            media=[duplicate],
            support=[caption2],
            display_name="Editorial Static Pin",
        )
        state = _state([v1, v2], tmp=self.tmp)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        self.assertEqual(len(plan.included), 1)
        self.assertTrue(plan.duplicates_removed)
        self.assertTrue(any(e.category == "duplicate" for e in plan.excluded))

    def test_clean_filename_generation_and_readme(self) -> None:
        media = _write_png(self.folder / "pin_v1.png")
        caption = _write_text(self.folder / "caption_v1.md", "Readable caption ready to publish.")
        version = _version(
            template_id="text_led_editorial_pin",
            folder=self.folder,
            media=[media],
            support=[caption],
        )
        piece = MagicMock()
        piece.record.piece_id = "piece_001"
        piece.record.title = "Still Life Reading Hour"
        state = _state([version], tmp=self.tmp, pieces=[piece])
        export_root = self.tmp / "exports"
        export_root.mkdir()
        with unittest.mock.patch("ui.export_service.exports_dir", return_value=export_root):
            result = create_export_package(
                state, mode=PUBLISHING_MODE, acknowledge_warnings=True
            )
        self.assertTrue(result.ok, result.message + str(result.detail))
        assert result.path is not None
        with zipfile.ZipFile(result.path) as zf:
            names = zf.namelist()
            self.assertTrue(any(n.endswith("README.txt") for n in names))
            self.assertTrue(any(n.endswith("manifest.json") for n in names))
            self.assertFalse(any("/studio/" in n for n in names))
            self.assertFalse(any("/v1/" in n for n in names))
            readme = next(n for n in names if n.endswith("README.txt"))
            text = zf.read(readme).decode("utf-8")
            self.assertIn("Included", text)
            self.assertIn("Historical versions remain in BettyOS", text)
            manifest_name = next(n for n in names if n.endswith("manifest.json"))
            payload = json.loads(zf.read(manifest_name))
            self.assertEqual(payload["mode"], PUBLISHING_MODE)
            self.assertTrue(payload["deliverables"])
            self.assertIn("render_version_id", payload["deliverables"][0])


class FinishOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_fin_"))
        self.folder = self.tmp / "cinematic_multi_clip_reel"
        self.folder.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_latest_approved_finish_selection_and_parent_exclusion(self) -> None:
        # Tiny valid-enough mp4 is hard; use png finish through static template path
        # by mocking resolve_finish_outputs via a real finish folder layout.
        from studio.models import FinishRecord
        from studio.paths import finish_version_dir

        parent_media = _write_png(self.folder / "parent_v1.png", (1, 1, 1))
        version = _version(
            template_id="editorial_static_pin",
            folder=self.folder,
            kind="image",
            media=[parent_media],
            support=[_write_text(self.folder / "caption.md", "Finish caption is publishable.")],
            display_name="Editorial Static Pin",
        )

        def _finish(fid: str, parent: str, updated: str) -> FinishRecord:
            out_dir = finish_version_dir(self.folder, fid) / "outputs"
            out_dir.mkdir(parents=True, exist_ok=True)
            finished = _write_png(out_dir / "finished.png", (50, 50, 50))
            meta = {
                "finish_version_id": fid,
                "campaign_id": "test",
                "content_piece_id": "piece_001",
                "template_id": "editorial_static_pin",
                "parent_render_version_id": parent,
                "parent_finish_version_id": None,
                "source_asset_id": None,
                "source_output_id": None,
                "source_file": str(parent_media),
                "media_type": "static",
                "recipe_id": None,
                "recipe_version": 1,
                "logo_configuration": {},
                "lighting_configuration": {},
                "color_configuration": {},
                "texture_configuration": {},
                "geometry_configuration": {},
                "lut_configuration": {},
                "export_configuration": {},
                "video_configuration": {},
                "output_files": [f"outputs/{finished.name}"],
                "preview_files": [],
                "validation_results": {},
                "status": "ready_for_review",
                "approval_status": "approved",
                "created_at": updated,
                "updated_at": updated,
            }
            (finish_version_dir(self.folder, fid) / "finish_metadata.json").write_text(
                json.dumps(meta), encoding="utf-8"
            )
            return FinishRecord.from_dict(meta)

        _finish("finish_v001", "render_v001", "2026-01-01T00:00:00+00:00")
        _finish("finish_v002", "render_v001", "2026-02-01T00:00:00+00:00")

        state = _state([version], tmp=self.tmp)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        self.assertEqual(len(plan.included), 1)
        item = plan.included[0]
        self.assertEqual(item.finish_version_id, "finish_v002")
        self.assertEqual(item.parent_render_version_id, "render_v001")
        # Parent render bytes must not appear beside the finish.
        self.assertTrue(all(parent_media.name not in f.archive_name for f in item.package_files))
        self.assertTrue(
            any("parent render" in e.label.lower() or "Replaced by approved Studio" in e.reason
                for e in plan.excluded)
        )
        # Manifest lineage fields present on item
        self.assertIsNotNone(item.render_version_id)


class ModeAndRegressionTests(unittest.TestCase):
    def test_default_publishing_mode_alias(self) -> None:
        self.assertEqual(normalize_mode("approved"), PUBLISHING_MODE)
        self.assertEqual(normalize_mode("publishing"), PUBLISHING_MODE)

    def test_advanced_archive_mode_label(self) -> None:
        if not CAMPAIGN.is_dir():
            self.skipTest("Regression campaign not present")
        from ui.campaign_state import build_campaign_state

        state = build_campaign_state(CAMPAIGN)
        plan = build_plan(state, mode=ARCHIVE_MODE)
        self.assertEqual(plan.mode, ARCHIVE_MODE)
        self.assertTrue(plan.include_metadata)
        self.assertTrue(any("Archive Package" in w for w in plan.warnings))
        # Archive still includes multiple reel versions when present
        reel_items = [
            i for i in plan.included if i.version and i.version.template_id == "cinematic_multi_clip_reel"
        ]
        self.assertGreaterEqual(len(reel_items), 2)

    def test_regression_campaign_publishing_package(self) -> None:
        if not CAMPAIGN.is_dir():
            self.skipTest("Regression campaign not present")
        from ui.campaign_state import build_campaign_state

        state = build_campaign_state(CAMPAIGN)
        plan = build_plan(state, mode=PUBLISHING_MODE)

        reels = [i for i in plan.included if i.summary_kind == "reel"]
        self.assertGreaterEqual(len(reels), 1)
        cinematic = [r for r in reels if r.finish_version_id == "finish_v004"]
        self.assertEqual(len(cinematic), 1)
        self.assertEqual(cinematic[0].parent_render_version_id, "render_v001")

        # No duplicate reel media / no studio folder paths in archive names
        for item in plan.included:
            for pkg in item.package_files:
                self.assertNotIn("/studio/", pkg.archive_name)
                self.assertNotIn("/finish_v", pkg.archive_name)

        self.assertTrue(
            any(
                "Pinterest" in e.label and e.category == "orphaned"
                for e in plan.excluded
            )
        )
        self.assertTrue(any(e.category == "superseded" for e in plan.excluded))

        # Historical assets untouched: parent files still on disk after plan
        parent = CAMPAIGN / "cinematic_multi_clip_reel" / "ritual_reel_v1.mp4"
        self.assertTrue(parent.is_file())

        export_root = Path(tempfile.mkdtemp(prefix="betty_export_out_"))
        try:
            with unittest.mock.patch("ui.export_service.exports_dir", return_value=export_root):
                result = create_export_package(
                    state, mode=PUBLISHING_MODE, acknowledge_warnings=True
                )
            self.assertTrue(result.ok, result.message)
            assert result.path is not None
            with zipfile.ZipFile(result.path) as zf:
                names = zf.namelist()
                self.assertTrue(any(n.endswith("README.txt") for n in names))
                self.assertTrue(any(n.endswith("manifest.json") for n in names))
                reel_files = [n for n in names if n.endswith(".mp4")]
                self.assertGreaterEqual(len(reel_files), 1)
                payload = json.loads(
                    zf.read(next(n for n in names if n.endswith("manifest.json")))
                )
                reel_entry = next(
                    d
                    for d in payload["deliverables"]
                    if d["media_type"] == "video" and d.get("finish_version_id") == "finish_v004"
                )
                self.assertEqual(reel_entry["finish_version_id"], "finish_v004")
                self.assertEqual(reel_entry["parent_render_version_id"], "render_v001")
                readme = zf.read(next(n for n in names if n.endswith("README.txt"))).decode()
                self.assertIn("Excluded", readme)
                self.assertIn("Historical versions remain in BettyOS", readme)

            # Restart persistence: export zip remains
            self.assertTrue(result.path.is_file())
            self.assertTrue(parent.is_file())
        finally:
            shutil.rmtree(export_root, ignore_errors=True)

    def test_excluded_incomplete_copy_does_not_block_valid_package(self) -> None:
        if not CAMPAIGN.is_dir():
            self.skipTest("Regression campaign not present")
        from ui.campaign_state import build_campaign_state
        from ui.export_service import VAGUE_INCOMPLETE_COPY

        state = build_campaign_state(CAMPAIGN)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        self.assertGreaterEqual(len(plan.included), 5)
        self.assertEqual(plan.validation_status, "ready")
        self.assertTrue(plan.create_enabled)
        self.assertNotIn(VAGUE_INCOMPLETE_COPY, plan.warnings)
        orphaned = [e for e in plan.excluded if e.category == "orphaned"]
        self.assertEqual(len(orphaned), 2)
        for exclusion in orphaned:
            self.assertEqual(exclusion.reason, "No matching final visual asset.")
        self.assertTrue(
            any("do not block this package" in line for line in plan.info_notes)
        )
        self.assertFalse(
            any("incomplete publishing copy" in line.lower() for line in plan.info_notes)
        )
        included_ids = {i.content_piece_id for i in plan.included if i.content_piece_id}
        for exclusion in orphaned:
            self.assertNotIn(exclusion.content_piece_id, included_ids)

    def test_selected_deliverable_incomplete_required_copy_blocks(self) -> None:
        folder = self.tmp / "instagram_caption" / "piece_x" if hasattr(self, "tmp") else None
        tmp = Path(tempfile.mkdtemp(prefix="betty_block_copy_"))
        try:
            folder = tmp / "instagram_caption" / "piece_blank"
            folder.mkdir(parents=True)
            blank = _write_text(folder / "caption_v1.md", "   \n")
            version = _version(
                template_id="instagram_caption",
                folder=folder,
                kind="copy",
                piece_id="piece_blank",
                media=[],
                support=[blank],
                display_name="Instagram Caption",
            )
            state = _state([version], tmp=tmp)
            plan = build_plan(state, mode=PUBLISHING_MODE)
            self.assertTrue(plan.is_empty or plan.is_blocked)
            self.assertFalse(plan.create_enabled)
            self.assertTrue(
                any(e.category == "incomplete" and e.actionable for e in plan.excluded)
            )
            joined = " ".join(plan.blockers + plan.warnings + plan.summary.blocking_copy_lines)
            self.assertTrue(
                "incomplete" in joined.lower() or any("blank" in e.reason.lower() for e in plan.excluded)
            )
            self.assertNotIn(
                "This asset is approved visually, but its publishing copy is incomplete.",
                plan.warnings,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_warning_language_names_exact_condition(self) -> None:
        from ui.export_service import blocking_incomplete_copy_message

        msg = blocking_incomplete_copy_message(
            "Still life, reading hour",
            ["Pinterest description"],
        )
        self.assertIn("Still life, reading hour", msg)
        self.assertIn("Pinterest description", msg)
        self.assertNotEqual(
            msg,
            "This asset is approved visually, but its publishing copy is incomplete.",
        )

    def test_grouped_exclusion_counts_are_accurate(self) -> None:
        if not CAMPAIGN.is_dir():
            self.skipTest("Regression campaign not present")
        from ui.campaign_state import build_campaign_state
        from ui.export_service import group_exclusions

        state = build_campaign_state(CAMPAIGN)
        plan = build_plan(state, mode=PUBLISHING_MODE)
        grouped = group_exclusions(plan.excluded)
        self.assertEqual(
            plan.summary.superseded_count,
            len(grouped.get("superseded", [])),
        )
        self.assertEqual(
            plan.summary.rejected_count,
            len(grouped.get("rejected", [])),
        )
        self.assertEqual(
            plan.summary.incomplete_count,
            len(grouped.get("incomplete", [])),
        )
        self.assertEqual(
            plan.summary.orphaned_count,
            len(grouped.get("orphaned", [])),
        )
        self.assertEqual(plan.summary.ready_item_count, len(plan.included))
        orphaned = grouped.get("orphaned") or []
        self.assertTrue(orphaned)
        self.assertTrue(all(e.reason == "No matching final visual asset." for e in orphaned))

    def test_package_history_remains_available(self) -> None:
        if not CAMPAIGN.is_dir():
            self.skipTest("Regression campaign not present")
        from ui.campaign_state import build_campaign_state
        from ui.export_service import list_existing_packages

        state = build_campaign_state(CAMPAIGN)
        # Function remains callable for Deliver Package History disclosure.
        packages = list_existing_packages(state)
        self.assertIsInstance(packages, list)

    def test_completing_excluded_records_triggers_revalidation(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="betty_complete_meta_"))
        try:
            pin_folder = tmp / "editorial_static_pin" / "piece_meta"
            pin_folder.mkdir(parents=True)
            meta_folder = tmp / "pinterest_caption_metadata" / "piece_meta"
            meta_folder.mkdir(parents=True)
            media = _write_png(pin_folder / "pin.png")
            caption = _write_text(pin_folder / "caption.md", "A quiet pin caption ready to publish.")
            meta = _write_text(
                meta_folder / "meta.md",
                "# Pinterest Pin Description\n\n**Title:** Quiet hour\n\n"
                "**Description:**\n\n**CTA:** Join the waitlist\n",
            )
            pin = _version(
                template_id="editorial_static_pin",
                folder=pin_folder,
                piece_id="piece_meta",
                media=[media],
                support=[caption],
                display_name="Editorial Static Pin",
            )
            metadata = _version(
                template_id="pinterest_caption_metadata",
                folder=meta_folder,
                kind="copy",
                piece_id="piece_meta",
                media=[],
                support=[meta],
                display_name="Pinterest Caption & Metadata",
            )
            state = _state([pin, metadata], tmp=tmp)
            before = build_plan(state, mode=PUBLISHING_MODE)
            self.assertEqual(len([i for i in before.included if i.summary_kind == "pin"]), 1)
            self.assertTrue(
                any(
                    e.category == "incomplete" and "blank" in e.reason.lower()
                    for e in before.excluded
                )
            )

            from ui.publishing_copy_fix import (
                approve_draft,
                open_completion_session,
                revalidate_after_completion,
            )

            session = open_completion_session(state, before)
            self.assertEqual(session.count, 1)
            approve_draft(session.drafts[0])
            after = revalidate_after_completion(state)
            self.assertTrue(
                any(i.summary_kind == "metadata" for i in after.included),
                msg=f"excluded={[(e.reason, e.category) for e in after.excluded]}",
            )
            self.assertEqual(after.validation_status, "ready")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_video_handling(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="betty_badvid_"))
        try:
            bad = tmp / "broken.mp4"
            bad.write_bytes(b"not a real video")
            result = validate_media_file(bad, expect="video")
            self.assertFalse(result.ok)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_file_hash_stable(self) -> None:
        path = _write_png(Path(tempfile.mkdtemp()) / "x.png")
        try:
            self.assertEqual(file_sha256(path), file_sha256(path))
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
