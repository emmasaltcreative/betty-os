"""Illustration versions flow through the existing Review and Approvals screens."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests.test_illustration_workflow import FakeProvider, WorkflowTestCase


class ReviewBridgeTests(WorkflowTestCase):
    def setUp(self) -> None:
        super().setUp()
        # The learning engine writes approval events, preferences and
        # performance records under brands/<id>/studio/, which is tracked in
        # git. Redirect it at a temp dir so tests never mutate repo state.
        self._studio_dir = Path(self._tmp.name) / "brand_studio"
        self._studio_dir.mkdir(parents=True, exist_ok=True)
        patcher = mock.patch(
            "studio.learning.brand_studio_dir", return_value=self._studio_dir
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _campaign(self) -> Path:
        campaign = Path(self._tmp.name) / "outputs" / "2026-11-08_120000_campaign"
        campaign.mkdir(parents=True, exist_ok=True)
        return campaign

    def _exported_version(self):
        from illustration import service

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        return service.export_version(version.version_id)

    def test_send_to_review_publishes_real_files(self) -> None:
        from illustration import review_bridge

        version = self._exported_version()
        campaign = self._campaign()
        result = review_bridge.send_to_review(version.version_id, campaign)

        self.assertTrue(result["ok"])
        self.assertTrue(result["published"])
        for path in result["published"]:
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 1024)
            self.assertTrue(str(path).startswith(str(campaign)))

    def test_private_original_is_copied_not_moved(self) -> None:
        from illustration import review_bridge, versions

        version = self._exported_version()
        originals = {
            kind: versions.resolve(stored)
            for kind, stored in version.export_paths.items()
        }
        review_bridge.send_to_review(version.version_id, self._campaign())
        for path in originals.values():
            self.assertTrue(path.is_file(), "the private original must stay in place")

    def test_review_registers_in_the_campaign_approvals_store(self) -> None:
        from src.templates.approvals_store import load_campaign_approvals
        from illustration import review_bridge

        version = self._exported_version()
        campaign = self._campaign()
        review_bridge.send_to_review(version.version_id, campaign)

        approvals = load_campaign_approvals(campaign)
        rows = [i for i in approvals["items"] if i["asset_id"] == version.version_id]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "awaiting_review")
        self.assertEqual(rows[0]["item_type"], "illustration")

    def test_cannot_send_an_unexported_version_to_review(self) -> None:
        from illustration import service, review_bridge

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        with self.assertRaises(review_bridge.ReviewBridgeError):
            review_bridge.send_to_review(version.version_id, self._campaign())

    def test_approval_updates_store_and_records_a_learning_event(self) -> None:
        from src.templates.approvals_store import load_campaign_approvals
        from illustration import review_bridge

        version = self._exported_version()
        campaign = self._campaign()
        review_bridge.send_to_review(version.version_id, campaign)
        result = review_bridge.set_approval(
            version.version_id, "approved", campaign_dir=campaign
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["event"].approval_status, "approved")
        rows = [
            i for i in load_campaign_approvals(campaign)["items"]
            if i["asset_id"] == version.version_id
        ]
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(
            result["version"].status, "approved_for_editorial_use"
        )

    def test_accuracy_claim_is_refused_without_a_verified_product(self) -> None:
        from illustration import review_bridge

        version = self._exported_version()
        campaign = self._campaign()
        result = review_bridge.set_approval(
            version.version_id, "approved", campaign_dir=campaign,
            product_accurate=True,
        )
        self.assertTrue(result["accuracy_refused"])
        self.assertEqual(
            result["accuracy_status"], "requires_product_verification"
        )

    def test_needs_revision_sends_it_back(self) -> None:
        from illustration import review_bridge

        version = self._exported_version()
        campaign = self._campaign()
        review_bridge.send_to_review(version.version_id, campaign)
        result = review_bridge.set_approval(
            version.version_id, "needs_revision", campaign_dir=campaign,
            note="eyes need correcting",
        )
        self.assertEqual(result["version"].status, "needs_accuracy_review")

    def test_review_queue_surfaces_what_needs_a_human(self) -> None:
        from illustration import review_bridge

        version = self._exported_version()
        queue = review_bridge.review_queue()
        row = next(r for r in queue if r["version_id"] == version.version_id)

        self.assertTrue(row["exported"])
        self.assertIn(
            "Label geometry confirmed against the real bottle",
            row["needs_attention"],
        )

    def test_approval_works_without_a_campaign(self) -> None:
        from illustration import review_bridge

        version = self._exported_version()
        result = review_bridge.set_approval(version.version_id, "approved")
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"].status, "approved_for_editorial_use")


if __name__ == "__main__":
    unittest.main()
