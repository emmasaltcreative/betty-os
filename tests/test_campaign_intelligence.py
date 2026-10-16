"""Campaign intelligence and Production Brief tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.campaign_intelligence.calendar import evaluate_opportunities, holiday_date
from src.campaign_intelligence.downloads import confirm_readable_file, human_size
from src.campaign_intelligence.engine import (
    accept_plan_and_generate_brief,
    plan_campaign_intelligence,
    update_estimates_after_capture,
)
from src.campaign_intelligence.estimates import (
    estimate_deliverables,
    estimate_runway,
    forbid_performance_forecast,
    recommend_cadence,
    revise_runway_after_capture,
)
from src.campaign_intelligence.models import (
    CampaignInputs,
    CampaignRole,
    EvidenceKind,
    TimingRelation,
)
from src.campaign_intelligence.production_session import build_combined_session
from src.campaign_intelligence.recommendations import (
    build_alerts,
    build_portfolio_recommendations,
)
from src.campaign_intelligence.scheduling import (
    is_overdue,
    lead_time_days,
    work_back_schedule,
)
from src.campaign_intelligence.store import (
    load_intelligence,
    newest_brief,
    resolve_brief_file,
)

AS_OF = date(2026, 8, 4)


class HolidayAndCalendarTests(unittest.TestCase):
    def test_holiday_date_calculation_fixed_and_floating(self) -> None:
        self.assertEqual(holiday_date("valentines_day", 2026), date(2026, 2, 14))
        self.assertEqual(holiday_date("world_book_day", 2027), date(2027, 4, 23))
        self.assertEqual(holiday_date("thanksgiving", 2026), date(2026, 11, 26))
        self.assertEqual(holiday_date("black_friday", 2026), date(2026, 11, 27))
        self.assertEqual(holiday_date("mothers_day", 2026), date(2026, 5, 10))

    def test_event_relevance_filters_novelty_for_oh_betty(self) -> None:
        opps = evaluate_opportunities(
            inputs=CampaignInputs(
                business_objective="grow the waitlist", inventory_available=False
            ),
            brand_id="oh_betty_jaletti",
            as_of=AS_OF,
        )
        ids = {o.event_id for o in opps}
        self.assertNotIn("national_pizza_day", ids)
        self.assertNotIn("april_fools", ids)
        self.assertNotIn("super_bowl", ids)
        self.assertTrue(
            "fall_reading_season" in ids or "national_book_month" in ids
        )

    def test_user_created_milestone_dates(self) -> None:
        inputs = CampaignInputs(
            business_objective="grow the waitlist",
            target_milestone_date=date(2026, 10, 1),
            product_availability_date=date(2026, 11, 15),
        )
        opps = evaluate_opportunities(inputs=inputs, as_of=AS_OF)
        ids = {o.event_id for o in opps}
        self.assertIn("target_launch", ids)
        self.assertIn("product_availability", ids)
        launch = next(o for o in opps if o.event_id == "target_launch")
        self.assertEqual(launch.occurrence_date, date(2026, 10, 1))


class SchedulingTests(unittest.TestCase):
    def test_lead_time_and_work_back_scheduling(self) -> None:
        min_d, max_d, label, assumptions = lead_time_days("grow the waitlist")
        self.assertGreaterEqual(min_d, 14)
        self.assertGreaterEqual(max_d, min_d)
        self.assertTrue("waitlist" in label.lower() or "preorder" in label.lower())
        self.assertTrue(assumptions)

        milestone = date(2026, 11, 1)
        schedule = work_back_schedule(
            milestone, objective="grow the waitlist", as_of=AS_OF
        )
        self.assertEqual(schedule.milestone_date, milestone)
        self.assertIsNotNone(schedule.recommended_start)
        self.assertIsNotNone(schedule.latest_safe_start)
        assert schedule.recommended_start is not None
        assert schedule.latest_safe_start is not None
        self.assertLessEqual(schedule.recommended_start, schedule.latest_safe_start)
        self.assertIsNotNone(schedule.production_deadline)
        assert schedule.production_deadline is not None
        self.assertLessEqual(schedule.production_deadline, milestone)

    def test_overdue_campaign_risk(self) -> None:
        schedule = work_back_schedule(
            AS_OF - timedelta(days=5),
            objective="simple organic burst",
            explicit_key="simple_organic_burst",
            as_of=AS_OF,
        )
        self.assertTrue(is_overdue(schedule, as_of=AS_OF))


class PortfolioAndEstimateTests(unittest.TestCase):
    def test_primary_and_supporting_recommendations(self) -> None:
        inputs = CampaignInputs(
            business_objective="grow the waitlist",
            target_milestone_date=date(2026, 10, 15),
            filming_minutes_available=60,
            preferred_platforms=["Instagram", "Pinterest"],
            inventory_available=False,
        )
        opps = evaluate_opportunities(inputs=inputs, as_of=AS_OF)
        recs = build_portfolio_recommendations(
            inputs,
            campaign_name="Grow The Reading Hour waitlist",
            opportunities=opps,
            as_of=AS_OF,
        )
        self.assertTrue(recs)
        self.assertEqual(recs[0].role, CampaignRole.PRIMARY)
        self.assertIsNotNone(recs[0].timing.latest_safe_start)
        self.assertTrue(recs[0].reason)
        self.assertGreaterEqual(len(recs), 2)
        support = recs[1]
        self.assertEqual(support.relation, TimingRelation.TANDEM)
        self.assertGreater(support.estimated_additional_filming_minutes.max_days, 0)
        self.assertGreater(support.estimated_runway_days.max_days, 0)

    def test_combined_production_and_deliverable_ranges(self) -> None:
        inputs = CampaignInputs(
            business_objective="grow the waitlist",
            target_milestone_date=date(2026, 10, 15),
            filming_minutes_available=70,
            preferred_platforms=["Instagram", "Pinterest"],
        )
        recs = build_portfolio_recommendations(inputs, as_of=AS_OF)
        session = build_combined_session(recs, filming_minutes_available=70)
        self.assertGreaterEqual(len(session.campaign_names), 1)
        self.assertLessEqual(
            session.filming_minutes.min_days, session.filming_minutes.max_days
        )
        self.assertTrue(any(s.shared for s in session.shots))
        self.assertTrue(any(s.must_have for s in session.shots))

        deliverables = estimate_deliverables(
            piece_count=5,
            platforms=["Instagram", "Pinterest"],
            filming_minutes_available=70,
            must_have_shots=len([s for s in session.shots if s.must_have]),
        )
        self.assertLessEqual(
            deliverables.final_assets.min_days, deliverables.final_assets.max_days
        )
        self.assertGreaterEqual(deliverables.final_assets.min_days, 1)

    def test_runway_cadence_and_no_unsupported_forecast(self) -> None:
        deliverables = estimate_deliverables(
            piece_count=5,
            platforms=["Instagram", "Pinterest"],
            filming_minutes_available=60,
        )
        cadence = recommend_cadence(
            platforms=["Instagram", "Pinterest"],
            objective="grow the waitlist",
            asset_count_max=deliverables.final_assets.max_days,
            has_connected_performance=False,
        )
        self.assertTrue(cadence)
        self.assertIn("planning assumptions", cadence[0].evidence.summary.lower())
        self.assertNotEqual(cadence[0].evidence.kind, EvidenceKind.FORECAST)

        evidence = forbid_performance_forecast(False)
        self.assertEqual(evidence.kind, EvidenceKind.OPERATIONAL_ESTIMATE)

        runway = estimate_runway(
            deliverables=deliverables, cadence=cadence, phase="pre_shoot", as_of=AS_OF
        )
        self.assertLessEqual(runway.days.min_days, runway.days.max_days)
        self.assertEqual(runway.evidence.kind, EvidenceKind.OPERATIONAL_ESTIMATE)

    def test_alerts_include_risk_without_inventory(self) -> None:
        inputs = CampaignInputs(
            business_objective="grow the waitlist",
            target_milestone_date=date(2026, 10, 1),
            inventory_available=False,
        )
        opps = evaluate_opportunities(inputs=inputs, as_of=AS_OF)
        recs = build_portfolio_recommendations(inputs, opportunities=opps, as_of=AS_OF)
        alerts = build_alerts(
            inputs, opportunities=opps, recommendations=recs, as_of=AS_OF
        )
        types = {a.alert_type.value for a in alerts}
        self.assertTrue(types & {"deadline", "opportunity", "risk"})


class PersistenceAndBriefTests(unittest.TestCase):
    def test_post_capture_runway_update_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_dir = Path(tmp) / "2026-08-04_120000_campaign"
            campaign_dir.mkdir()
            inputs = CampaignInputs(
                business_objective="grow the waitlist",
                target_milestone_date=date(2026, 10, 15),
                filming_minutes_available=60,
                preferred_platforms=["Instagram", "Pinterest"],
                inventory_available=False,
            )
            intel = plan_campaign_intelligence(
                campaign_dir=campaign_dir,
                campaign_name="Reading Hour Waitlist",
                inputs=inputs,
                piece_count=5,
                as_of=AS_OF,
                persist=True,
            )
            pre = intel.current_runway("pre_shoot")
            self.assertIsNotNone(pre)
            assert pre is not None

            updated = update_estimates_after_capture(
                campaign_dir,
                usable_shots=2,
                planned_shots=5,
                quality_note="Lighting inconsistency reduced publishable lifestyle clips.",
            )
            self.assertGreaterEqual(len(updated.runway_history), 2)
            post = updated.current_runway("post_capture")
            self.assertIsNotNone(post)
            assert post is not None
            self.assertLessEqual(post.days.max_days, pre.days.max_days)
            self.assertTrue(
                "Lighting" in post.reason_for_change
                or "reduced" in post.reason_for_change.lower()
            )
            self.assertIsNotNone(updated.current_runway("pre_shoot"))

    def test_production_brief_pdf_download_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_dir = Path(tmp) / "2026-08-04_120000_campaign"
            campaign_dir.mkdir()
            inputs = CampaignInputs(
                business_objective="grow the waitlist",
                target_milestone_date=date(2026, 10, 15),
                product_availability_date=date(2026, 11, 20),
                filming_minutes_available=60,
                preferred_platforms=["Instagram", "Pinterest"],
                inventory_available=False,
            )
            plan_campaign_intelligence(
                campaign_dir=campaign_dir,
                campaign_name="The Reading Hour Waitlist",
                inputs=inputs,
                piece_count=5,
                as_of=AS_OF,
                persist=True,
            )
            result = accept_plan_and_generate_brief(campaign_dir)
            brief = result["brief"]
            self.assertTrue(brief["ok"])
            self.assertLessEqual(brief["page_count"], 5)
            self.assertGreaterEqual(brief["page_count"], 3)
            self.assertTrue(brief["filename"].endswith(".pdf"))
            self.assertIn("production-brief", brief["filename"])
            path = Path(brief["path"])
            ok, size_label = confirm_readable_file(path)
            self.assertTrue(ok)
            self.assertEqual(path.stat().st_size, len(brief["bytes"]))
            self.assertTrue(
                "B" in size_label or "KB" in size_label or "MB" in size_label
            )

            reloaded = load_intelligence(campaign_dir)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(reloaded.newest_brief_id, brief["brief_id"])
            self.assertEqual(reloaded.inputs.business_objective, "grow the waitlist")
            self.assertTrue(reloaded.portfolio_accepted)
            record = newest_brief(campaign_dir)
            self.assertIsNotNone(record)
            assert record is not None
            resolved = resolve_brief_file(campaign_dir, record)
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertTrue(resolved.is_file())

    def test_existing_campaign_compatibility_without_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "legacy_campaign"
            campaign.mkdir()
            self.assertIsNone(load_intelligence(campaign))
            self.assertIsNone(newest_brief(campaign))

    def test_human_size_and_revise_helper(self) -> None:
        self.assertEqual(human_size(500), "500 B")
        self.assertIn("KB", human_size(2048))
        deliverables = estimate_deliverables(piece_count=3, platforms=["Instagram"])
        cadence = recommend_cadence(platforms=["Instagram"], asset_count_max=4)
        pre = estimate_runway(
            deliverables=deliverables, cadence=cadence, phase="pre_shoot"
        )
        post = revise_runway_after_capture(pre, usable_shots=6, planned_shots=3)
        self.assertEqual(post.phase, "post_capture")
        self.assertGreaterEqual(post.days.min_days, pre.days.min_days)


if __name__ == "__main__":
    unittest.main()
