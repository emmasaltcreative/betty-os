"""Decide media: canonical video vs poster stills."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.decide_media import (
    expects_video_deliverable,
    resolve_decide_media,
    resolve_canonical_finish_media,
)


def _write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class DecideMediaResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_decide_media_"))
        self.folder = self.tmp / "cinematic_multi_clip_reel"
        self.folder.mkdir()
        self.finish_dir = self.folder / "studio" / "finish_v001"
        self.video = _write(self.finish_dir / "outputs" / "finished.mp4", b"\x00\x00ftyp")
        self.poster = _write(self.finish_dir / "previews" / "preview.jpg", b"\xff\xd8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _version(self, **overrides):
        version = MagicMock()
        version.folder = self.folder
        version.template_id = "cinematic_multi_clip_reel"
        version.kind = "video"
        version.display_name = "Cinematic Multi-Clip Reel"
        version.primary_path = self.folder / "cinematic_multi_clip_reel_v1.mp4"
        _write(version.primary_path, b"render")
        for key, value in overrides.items():
            setattr(version, key, value)
        return version

    def _finish(self, *, media_type: str = "video"):
        record = MagicMock()
        record.finish_version_id = "finish_v001"
        record.media_type = media_type
        record.output_files = ["outputs/finished.mp4"]
        record.preview_files = ["previews/preview.jpg"]
        return record

    def test_canonical_video_not_replaced_by_poster(self) -> None:
        version = self._version()
        active = self._finish()
        media = resolve_decide_media(version, active)
        self.assertEqual(media.kind, "video")
        self.assertEqual(media.canonical.resolve(), self.video.resolve())
        self.assertEqual(media.poster.resolve(), self.poster.resolve())
        self.assertTrue(media.can_approve)
        self.assertIsNone(media.blocking_message)
        # Old bug path: preview preferred over output
        canonical, poster = resolve_canonical_finish_media(version, active)
        self.assertNotEqual(canonical.suffix.lower(), ".jpg")
        self.assertEqual(canonical.suffix.lower(), ".mp4")
        self.assertEqual(poster.suffix.lower(), ".jpg")

    def test_image_asset_resolves_to_image(self) -> None:
        pin_folder = self.tmp / "editorial_static_pin"
        png = _write(pin_folder / "pin_v1.png", b"PNG")
        version = MagicMock()
        version.folder = pin_folder
        version.template_id = "editorial_static_pin"
        version.kind = "image"
        version.primary_path = png
        media = resolve_decide_media(version, None)
        self.assertEqual(media.kind, "image")
        self.assertEqual(media.canonical.resolve(), png.resolve())
        self.assertTrue(media.can_approve)

    def test_missing_video_blocks_approval(self) -> None:
        version = self._version()
        active = self._finish()
        active.output_files = ["outputs/missing.mp4"]
        # Leave poster in place — must not unlock approval.
        media = resolve_decide_media(version, active)
        self.assertFalse(media.can_approve)
        self.assertIsNotNone(media.blocking_message)
        self.assertIn("Video output is missing", media.blocking_message)
        self.assertTrue(media.expects_video)

    def test_poster_only_finish_blocks_video_approval(self) -> None:
        version = self._version()
        active = self._finish()
        # Corrupt metadata to point only at the poster as "output"
        active.output_files = ["previews/preview.jpg"]
        media = resolve_decide_media(version, active)
        self.assertTrue(media.expects_video)
        self.assertFalse(media.can_approve)
        self.assertIn("Video output is missing", media.blocking_message or "")

    def test_expects_video_from_file_not_label(self) -> None:
        version = self._version(display_name="Looks like a pin", kind="video")
        self.assertTrue(expects_video_deliverable(version, self._finish()))
        image = self._version(
            template_id="editorial_static_pin",
            kind="image",
            display_name="Cinematic Multi-Clip Reel",  # misleading label
            primary_path=_write(self.tmp / "still.png"),
        )
        self.assertFalse(expects_video_deliverable(image, None))


class OhBettyReelRegressionTests(unittest.TestCase):
    def test_oh_betty_reel_decide_resolves_mp4(self) -> None:
        campaign = ROOT / "outputs" / "2026-08-04_165657_campaign"
        if not campaign.is_dir():
            self.skipTest("Oh Betty campaign missing")
        from ui.campaign_state import active_finish_for_decide, build_campaign_state
        from ui.screens.workspace import _resolve_decide_preview

        state = build_campaign_state(campaign)
        reel = next(
            (
                v
                for v in state.versions
                if v.template_id == "cinematic_multi_clip_reel"
            ),
            None,
        )
        if reel is None:
            self.skipTest("Reel version missing")
        active = active_finish_for_decide(reel)
        media = resolve_decide_media(reel, active)
        self.assertEqual(media.kind, "video")
        assert media.canonical is not None
        self.assertEqual(media.canonical.suffix.lower(), ".mp4")
        self.assertTrue(media.canonical.name.startswith("finished") or media.canonical.suffix == ".mp4")
        self.assertNotIn("/previews/", str(media.canonical).replace("\\", "/"))
        # Compatibility helper must match
        self.assertEqual(_resolve_decide_preview(reel, active), media.canonical)

    def test_oh_betty_package_includes_reel_mp4(self) -> None:
        campaign = ROOT / "outputs" / "2026-08-04_165657_campaign"
        if not campaign.is_dir():
            self.skipTest("Oh Betty campaign missing")
        import zipfile
        from unittest.mock import patch

        from ui.campaign_state import build_campaign_state
        from ui.export_service import PUBLISHING_MODE, create_export_package

        state = build_campaign_state(campaign)
        export_root = Path(tempfile.mkdtemp(prefix="betty_reel_pkg_"))
        try:
            with patch("ui.export_service.exports_dir", return_value=export_root):
                result = create_export_package(
                    state, mode=PUBLISHING_MODE, acknowledge_warnings=True
                )
            if not result.ok:
                self.skipTest(f"Package not creatable: {result.message}")
            assert result.path is not None
            with zipfile.ZipFile(result.path) as zf:
                names = zf.namelist()
                mp4s = [n for n in names if n.lower().endswith(".mp4")]
                self.assertTrue(mp4s, f"No MP4 in package: {names}")
                # Must not ship only the poster for the reel
                reel_related = [
                    n for n in names if "reel" in n.lower() or "cinematic" in n.lower()
                ]
                if reel_related:
                    self.assertTrue(
                        any(n.lower().endswith(".mp4") for n in reel_related)
                        or mp4s,
                    )
        finally:
            shutil.rmtree(export_root, ignore_errors=True)


class CompactPreviewComponentTests(unittest.TestCase):
    def test_video_path_uses_st_video_not_image(self) -> None:
        """compact_media_preview must call st.video for MP4."""
        from unittest.mock import patch

        from ui import components

        tmp = Path(tempfile.mkdtemp(prefix="betty_preview_comp_"))
        try:
            video = _write(tmp / "finished.mp4", b"vid")
            poster = _write(tmp / "preview.jpg", b"img")
            with patch.object(components, "st") as st:
                st.session_state = {}
                components.compact_media_preview(
                    video, key="t", poster=poster, allow_expand=False
                )
                st.video.assert_called_once_with(str(video))
                st.image.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_image_path_uses_st_image(self) -> None:
        from unittest.mock import patch

        from ui import components

        tmp = Path(tempfile.mkdtemp(prefix="betty_preview_img_"))
        try:
            image = _write(tmp / "pin.png", b"png")
            with patch.object(components, "st") as st:
                st.session_state = {}
                components.compact_media_preview(image, key="img", allow_expand=False)
                st.image.assert_called_once()
                st.video.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
