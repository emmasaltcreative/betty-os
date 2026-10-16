"""Decide revision workflow + brand compliance regression tests."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.brand_compliance import (
    campaign_brand_consistency,
    campaign_has_blocking_brand_failure,
    evaluate_brand_compliance,
)
from services.decide_revision import (
    RevisionJob,
    RevisionPlan,
    active_job_for_version,
    classify_revision_feedback,
    execute_revision_job,
    load_job,
    recover_stale_jobs,
    save_job,
    start_revision_job,
)
from studio.auto_edit import parse_revision_request
from ui.campaign_state import RenderVersion, active_finish_for_decide


def _write_render_settings(folder: Path, hook: str = "You've been doing this your whole life.") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    settings = {
        "production": {
            "template": {
                "hook": {"lines": [hook]},
                "supporting": {"lines": ["The reading hour. You already know what it is."]},
                "cta": {"text": "Join the waitlist"},
                "footer": {"lines": ["Oh Betty Jaletti"]},
                "sources": [],
                "target_duration_seconds": 15.0,
            }
        },
        "clips": [],
        "resolved": {"cta_appear_at_seconds": 10.0},
    }
    (folder / "render_settings.json").write_text(json.dumps(settings), encoding="utf-8")


class ClassifyRevisionTests(unittest.TestCase):
    def test_verbiage_is_copy(self) -> None:
        self.assertEqual(classify_revision_feedback("I don't like the verbiage"), "copy")

    def test_parse_revision_request_includes_verbiage(self) -> None:
        structured = parse_revision_request("I don't like the verbiage")
        self.assertIn("adjust_copy_rerender", structured["intents"])
        self.assertIn("adjust_copy_rerender", structured["requires_rerender"])


class RevisionJobLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="betty_rev_"))
        self.campaign = self.tmp / "campaign"
        self.campaign.mkdir()
        self.render = self.campaign / "cinematic_multi_clip_reel"
        _write_render_settings(self.render)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_click_creates_idempotent_job_and_plan(self) -> None:
        job = start_revision_job(
            campaign_dir=self.campaign,
            version_key="cinematic_multi_clip_reel|-|v1",
            finish_version_id="finish_v001",
            feedback="I don't like the verbiage",
            render_folder=self.render,
            campaign_goal="Reading Hour Waitlist",
        )
        self.assertEqual(job.status, "awaiting_plan_confirmation")
        self.assertEqual(job.plan.category, "copy")
        self.assertEqual(job.plan.original_copy, "You've been doing this your whole life.")
        self.assertTrue(job.plan.proposed_copy)
        self.assertNotEqual(job.plan.proposed_copy, job.plan.original_copy)
        self.assertTrue((self.campaign / "revision_jobs" / f"{job.job_id}.json").is_file())

        again = start_revision_job(
            campaign_dir=self.campaign,
            version_key="cinematic_multi_clip_reel|-|v1",
            finish_version_id="finish_v001",
            feedback="I don't like the verbiage",
            render_folder=self.render,
            campaign_goal="Reading Hour Waitlist",
        )
        self.assertEqual(again.job_id, job.job_id)

    def test_job_survives_reload_like_streamlit_rerun(self) -> None:
        job = start_revision_job(
            campaign_dir=self.campaign,
            version_key="cinematic_multi_clip_reel|-|v1",
            finish_version_id="finish_v001",
            feedback="I don't like the verbiage",
            render_folder=self.render,
            campaign_goal="Reading Hour Waitlist",
        )
        reloaded = load_job(self.campaign, job.job_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.feedback, "I don't like the verbiage")
        self.assertEqual(reloaded.status, "awaiting_plan_confirmation")
        active = active_job_for_version(self.campaign, "cinematic_multi_clip_reel|-|v1")
        self.assertEqual(active.job_id, job.job_id)

    def test_failed_revision_exits_processing_state(self) -> None:
        job = RevisionJob(
            job_id="rev_fail",
            campaign_id=self.campaign.name,
            version_key="cinematic_multi_clip_reel|-|v1",
            finish_version_id="finish_v001",
            feedback="I don't like the verbiage",
            status="awaiting_plan_confirmation",
            phase_label="Reviewing the revision plan",
            plan=RevisionPlan(
                category="copy",
                summary_lines=["Rewrite hook"],
                original_copy="A",
                proposed_copy="B",
            ),
        )
        save_job(self.campaign, job)
        version = MagicMock()
        version.folder = self.render
        version.version = 1
        version.piece_id = None
        version.template_id = "cinematic_multi_clip_reel"
        version.key = "cinematic_multi_clip_reel|-|v1"
        version.kind = "video"
        with patch(
            "services.decide_revision._rebuild_reel_with_hook",
            side_effect=RuntimeError("render exploded"),
        ):
            updated = execute_revision_job(
                campaign_dir=self.campaign,
                job=job,
                version=version,
                active=MagicMock(finish_version_id="finish_v001"),
            )
        self.assertEqual(updated.status, "failed")
        self.assertFalse(updated.is_active)
        self.assertIn("render exploded", updated.error)

    def test_stale_jobs_recover_safely(self) -> None:
        job = RevisionJob(
            job_id="rev_stale",
            campaign_id=self.campaign.name,
            version_key="k",
            finish_version_id="finish_v001",
            feedback="stuck",
            status="rebuilding",
            phase_label="Rebuilding the reel",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        )
        path = self.campaign / "revision_jobs" / "rev_stale.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write directly so save_job does not refresh updated_at to now.
        path.write_text(json.dumps(job.as_dict()), encoding="utf-8")
        recovered = recover_stale_jobs(self.campaign, max_age_seconds=60)
        self.assertEqual(len(recovered), 1)
        reloaded = load_job(self.campaign, "rev_stale")
        self.assertEqual(reloaded.status, "failed")
        self.assertFalse(reloaded.is_active)

    def test_execute_creates_new_immutable_finish_and_keeps_focus(self) -> None:
        job = start_revision_job(
            campaign_dir=self.campaign,
            version_key="cinematic_multi_clip_reel|-|v1",
            finish_version_id="finish_v001",
            feedback="I don't like the verbiage",
            render_folder=self.render,
            campaign_goal="Reading Hour Waitlist",
        )
        fake_mp4 = self.render / "cinematic_multi_clip_reel_v2.mp4"
        fake_mp4.write_bytes(b"\x00\x00ftyp")
        finish = MagicMock()
        finish.finish_version_id = "finish_v004"
        finish.approval_status = "awaiting_review"
        finish.status = "ready_for_review"
        finish.media_type = "video"
        finish.output_files = ["outputs/finished.mp4"]
        finish.preview_files = []
        version = MagicMock()
        version.folder = self.render
        version.version = 1
        version.piece_id = None
        version.template_id = "cinematic_multi_clip_reel"
        version.key = "cinematic_multi_clip_reel|-|v1"
        version.kind = "video"

        out_dir = self.render / "studio" / "finish_v004" / "outputs"
        out_dir.mkdir(parents=True)
        (out_dir / "finished.mp4").write_bytes(b"\x00\x00ftyp")

        with (
            patch(
                "services.decide_revision._rebuild_reel_with_hook",
                return_value=fake_mp4,
            ),
            patch(
                "studio.service.generate_best_edit",
                return_value={"ok": True, "record": finish},
            ),
            patch("studio.service.send_to_review", return_value={"ok": True}),
        ):
            updated = execute_revision_job(
                campaign_dir=self.campaign,
                job=job,
                version=version,
                active=MagicMock(finish_version_id="finish_v001"),
                campaign_goal="Reading Hour Waitlist",
            )
        self.assertEqual(updated.status, "ready")
        self.assertEqual(updated.new_finish_version_id, "finish_v004")
        self.assertEqual(updated.new_render_version, 2)
        self.assertEqual(updated.new_version_key, "cinematic_multi_clip_reel|-|v2")
        self.assertNotEqual(updated.new_finish_version_id, "finish_v001")
        self.assertFalse(updated.brand_check.get("blocking"))


class ActiveFinishPreferenceTests(unittest.TestCase):
    def test_awaiting_revision_beats_older_approved(self) -> None:
        version = MagicMock()
        version.folder = Path("/tmp")
        version.version = 1
        approved = MagicMock()
        approved.finish_version_id = "finish_v001"
        approved.status = "ready_for_review"
        approved.approval_status = "approved"
        approved.updated_at = "2026-01-01"
        revision = MagicMock()
        revision.finish_version_id = "finish_v004"
        revision.status = "ready_for_review"
        revision.approval_status = "awaiting_review"
        revision.updated_at = "2026-08-01"
        with patch(
            "ui.campaign_state.finish_records_for_version",
            return_value=[approved, revision],
        ):
            active = active_finish_for_decide(version)
        self.assertEqual(active.finish_version_id, "finish_v004")

    def test_preferred_finish_id_wins(self) -> None:
        version = MagicMock()
        version.folder = Path("/tmp")
        version.version = 1
        a = MagicMock(finish_version_id="finish_v001", status="ready_for_review", approval_status="approved", updated_at="a")
        b = MagicMock(finish_version_id="finish_v002", status="ready_for_review", approval_status="awaiting_review", updated_at="b")
        with patch("ui.campaign_state.finish_records_for_version", return_value=[a, b]):
            active = active_finish_for_decide(version, preferred_finish_id="finish_v001")
        self.assertEqual(active.finish_version_id, "finish_v001")


class BrandComplianceTests(unittest.TestCase):
    def test_brand_guide_required(self) -> None:
        with patch(
            "services.brand_compliance.load_brand_guide",
            return_value=("", False, []),
        ):
            report = evaluate_brand_compliance(copy_text="Hello", require_brand_guide=True)
        self.assertTrue(report.blocking)

    def test_pass_warning_blocker(self) -> None:
        report = evaluate_brand_compliance(
            copy_text="The reading hour was already yours.",
            media_path=None,
            expects_video=False,
        )
        self.assertIn(report.overall, {"pass", "warning", "blocking"})

        blocked = evaluate_brand_compliance(
            copy_text="Elevate your routine with this must-have.",
            media_path=None,
            expects_video=False,
        )
        self.assertTrue(blocked.blocking)

        video_missing = evaluate_brand_compliance(
            copy_text="Quiet recognition.",
            media_path=None,
            expects_video=True,
        )
        self.assertTrue(video_missing.blocking)

    def test_campaign_blocking_disables_ready(self) -> None:
        version = MagicMock()
        version.is_latest = True
        version.kind = "video"
        version.primary_path = None
        version.display_name = "Reel"
        version.caption = ""
        version.template_id = "cinematic_multi_clip_reel"
        state = MagicMock()
        state.versions = [version]
        summary = campaign_brand_consistency(state)
        self.assertTrue(summary["blocking"])
        self.assertTrue(campaign_has_blocking_brand_failure(state))


class ExportUsesApprovedOnlyTests(unittest.TestCase):
    def test_package_uses_approved_not_unapproved_candidate(self) -> None:
        from ui.campaign_state import approved_finish_records_for_version

        version = MagicMock()
        version.folder = Path("/tmp")
        version.version = 1
        approved = MagicMock(finish_version_id="finish_v001", approval_status="approved")
        candidate = MagicMock(finish_version_id="finish_v004", approval_status="awaiting_review")
        with patch(
            "ui.campaign_state.finish_records_for_version",
            return_value=[approved, candidate],
        ):
            records = approved_finish_records_for_version(version)
        ids = [r.finish_version_id for r in records]
        self.assertEqual(ids, ["finish_v001"])
        self.assertNotIn("finish_v004", ids)


class StuckRevisionUiRegressionTests(unittest.TestCase):
    def test_workspace_no_longer_uses_indefinite_addressing_message(self) -> None:
        source = (ROOT / "ui" / "screens" / "workspace.py").read_text(encoding="utf-8")
        self.assertNotIn("I’m addressing your feedback", source)
        self.assertIn("Interpreting your feedback", source)
        self.assertIn("Revision ready", source)
        self.assertIn("Brand Check", source)
        self.assertIn("decide_revision", source)


if __name__ == "__main__":
    unittest.main()
