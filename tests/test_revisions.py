"""Tests for the AI-assisted revision engine.

These cover the parts that must be right whether or not a model is reachable:
how a recommendation is read, how one field of a copy document is rewritten
without disturbing the rest, what the brand checks reject, and whether a
revision request survives being written and read back.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services import revision_store as store
from services import revision_types as rt
from services.copy_documents import CopyDocument
from services.revision_classifier import (
    Classification,
    classify_by_rules,
    fingerprint,
    proposed_change_by_rules,
)
from services.revision_validation import (
    NEEDS_ATTENTION,
    PASS,
    REJECTED,
    validate_option,
    validate_options,
)


def rec(**fields: object) -> dict[str, object]:
    base = {
        "recommendation_id": "rec_test",
        "title": "",
        "full_instruction": "",
        "expected_changes": "",
        "rationale": "",
        "recommendation_type": "revise_copy",
        "affected_asset": "Ritual Reel",
        "priority": "high",
        "status": "proposed",
    }
    base.update(fields)
    return base


class ClassifierRuleTests(unittest.TestCase):
    """A copy rewrite must never come back as human work."""

    def test_supporting_copy_is_a_copy_rewrite(self) -> None:
        type_key, field_key = classify_by_rules(
            rec(
                title="Replace on-screen supporting copy",
                full_instruction="Replace the supporting on-screen copy with a named moment.",
            )
        )
        self.assertEqual(type_key, "supporting_copy_rewrite")
        self.assertEqual(field_key, "overlay_supporting")

    def test_title_outranks_the_body(self) -> None:
        """A caption rewrite that mentions the CTA in passing is still a caption."""
        type_key, field_key = classify_by_rules(
            rec(
                title="Revise ritual reel caption to lead with emotional recognition",
                full_instruction=(
                    "Rewrite the caption so the first line names the feeling, then keep the "
                    "existing call to action at the end."
                ),
            )
        )
        self.assertEqual(type_key, "caption_rewrite")
        self.assertEqual(field_key, "instagram_caption")

    def test_email_subject_line(self) -> None:
        type_key, field_key = classify_by_rules(
            rec(title="Improve the subject line", recommendation_type="revise_copy")
        )
        self.assertEqual(type_key, "email_rewrite")
        self.assertEqual(field_key, "email_subject")

    def test_pinterest_description(self) -> None:
        type_key, field_key = classify_by_rules(
            rec(title="Rewrite the Pinterest description", recommendation_type="revise_copy")
        )
        self.assertEqual(type_key, "pinterest_metadata_rewrite")
        self.assertEqual(field_key, "pinterest_description")

    def test_new_footage_is_human_work(self) -> None:
        for title in (
            "Film new product footage",
            "Take a new lifestyle photograph",
            "Provide an unwatermarked logo",
            "Photograph the finished prototype",
        ):
            with self.subTest(title=title):
                type_key, _ = classify_by_rules(
                    rec(title=title, recommendation_type="manual_review")
                )
                entry = rt.revision_type(type_key)
                self.assertIsNotNone(entry, title)
                self.assertEqual(entry.natural_capability, rt.HUMAN_INPUT_REQUIRED, title)

    def test_render_changes(self) -> None:
        cases = {
            "Move the CTA from second 12 to second 9": "cta_timing_change",
            "Remove IMG_2549": "clip_remove",
            "Reorder the clips": "clip_reorder",
            "Change reel duration to 14 seconds": "duration_change",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                type_key, _ = classify_by_rules(
                    rec(title=title, recommendation_type="change_timing")
                )
                self.assertEqual(type_key, expected)

    def test_cta_seconds_read_the_destination_not_the_origin(self) -> None:
        change = proposed_change_by_rules(
            "cta_timing_change",
            rec(title="Move the CTA from second 12 to second 9"),
            None,
        )
        self.assertEqual(change, {"cta_appear_at_seconds": 9.0})

    def test_clip_to_remove_is_named(self) -> None:
        change = proposed_change_by_rules(
            "clip_remove", rec(title="Remove IMG_2549 from the reel"), None
        )
        self.assertEqual(change, {"remove_clips": ["IMG_2549"]})

    def test_fingerprint_follows_an_edit(self) -> None:
        one = rec(title="Shorten the caption")
        two = rec(title="Shorten the caption", full_instruction="Down to two lines.")
        self.assertNotEqual(fingerprint(one), fingerprint(two))
        self.assertEqual(fingerprint(one), fingerprint(rec(title="Shorten the caption")))


class CopyDocumentTests(unittest.TestCase):
    """One field changes; every other byte stays where it was."""

    CAPTIONS = (
        "# Captions\n\n"
        "## Instagram\n\n"
        "The hour you keep meaning to take.\n\n"
        "## Pinterest\n\n"
        "A reading hour you actually keep.\n"
    )

    def test_reads_each_section(self) -> None:
        document = CopyDocument.from_text(self.CAPTIONS)
        self.assertEqual(document.kind, "video_captions")
        self.assertEqual(document.read("instagram_caption"), "The hour you keep meaning to take.")
        self.assertEqual(
            document.read("pinterest_caption"), "A reading hour you actually keep."
        )

    def test_replacing_one_section_leaves_the_other(self) -> None:
        document = CopyDocument.from_text(self.CAPTIONS)
        revised = document.replaced("instagram_caption", "For the evenings that are yours again.")
        self.assertIn("For the evenings that are yours again.", revised)
        self.assertIn("A reading hour you actually keep.", revised)
        self.assertIn("## Pinterest", revised)
        self.assertNotIn("The hour you keep meaning to take.", revised)

    def test_a_caption_file_has_no_email_subject(self) -> None:
        document = CopyDocument.from_text(self.CAPTIONS)
        self.assertIsNone(document.span_for("email_subject"))
        self.assertNotIn("email_subject", document.fields_present())

    def test_email_fields(self) -> None:
        text = (
            "# The hour you keep meaning to take\n\n"
            "**Preview text:** A small return to the stories you keep saving.\n\n"
            "Dear reader,\n\n"
            "Some evenings pass without a single page turned.\n\n"
            "Join the waitlist.\n\n"
            "With care,\nBetty\n"
        )
        document = CopyDocument.from_text(text)
        self.assertEqual(document.kind, "email")
        self.assertEqual(document.read("email_subject"), "The hour you keep meaning to take")
        self.assertEqual(
            document.read("email_preview"),
            "A small return to the stories you keep saving.",
        )
        self.assertEqual(document.read("email_cta"), "Join the waitlist.")

        revised = document.replaced("email_subject", "An hour that is yours again")
        self.assertIn("# An hour that is yours again", revised)
        self.assertIn("**Preview text:** A small return", revised)
        self.assertIn("With care,", revised)

    def test_pinterest_metadata_labels(self) -> None:
        text = (
            "# Pinterest Pin Description\n\n"
            "**Title:** The Reading Hour\n\n"
            "**Description:** A linen journal for the hour you keep meaning to take.\n\n"
            "**CTA:** Join the waitlist.\n"
        )
        document = CopyDocument.from_text(text)
        self.assertEqual(document.read("pinterest_title"), "The Reading Hour")
        revised = document.replaced("pinterest_title", "An Hour That Is Yours")
        self.assertIn("**Title:** An Hour That Is Yours", revised)
        self.assertIn("**CTA:** Join the waitlist.", revised)


class ValidationTests(unittest.TestCase):
    def test_brand_aligned_wording_passes(self) -> None:
        verdict = validate_option(
            "For the part of you that misses getting lost in a book.",
            option_id="option_001",
            original_value="Make more time for reading.",
            max_words=14,
        )
        self.assertEqual(verdict.verdict, PASS, [i.message for i in verdict.issues])

    def test_over_the_word_limit_is_rejected(self) -> None:
        verdict = validate_option(
            "For the part of you that quietly misses the feeling of getting completely "
            "lost inside a book on a slow evening at home",
            option_id="option_001",
            original_value="Make more time for reading.",
            max_words=12,
        )
        self.assertEqual(verdict.verdict, REJECTED)
        self.assertTrue(any("word" in i.message.lower() for i in verdict.issues))

    def test_pressure_language_is_rejected(self) -> None:
        verdict = validate_option(
            "Don't miss out — buy now before it's gone!",
            option_id="option_001",
            original_value="Join the waitlist.",
        )
        self.assertEqual(verdict.verdict, REJECTED)

    def test_unchanged_wording_is_flagged(self) -> None:
        verdict = validate_option(
            "Make more time for reading.",
            option_id="option_001",
            original_value="Make more time for reading.",
        )
        self.assertIn(verdict.verdict, {NEEDS_ATTENTION, REJECTED})

    def test_duplicate_options_are_flagged(self) -> None:
        options = [
            {"option_id": "option_001", "text": "For evenings that feel more like yours again."},
            {"option_id": "option_002", "text": "For evenings that feel more like yours again."},
        ]
        verdicts = validate_options(options, original_value="Make more time for reading.")
        self.assertNotEqual(verdicts["option_002"].verdict, PASS)


def _classification() -> Classification:
    return Classification(
        recommendation_id="rec_test",
        capability=rt.AI_ASSISTED,
        revision_type="supporting_copy_rewrite",
        confidence=0.9,
        rationale="Wording BettyOS can propose from the Brand Guide.",
        target_field="overlay_supporting",
        supported_actions=["generate_options", "apply_selected_option", "rerender"],
        asset_id="cinematic_multi_clip_reel",
        asset_name="Ritual Reel",
        render_version_id="v1",
        original_value="Make more time for reading.",
        default_instruction="Rewrite the supporting on-screen copy.",
    )


class StoreTests(unittest.TestCase):
    """Every action writes to disk, so a restart loses nothing."""

    def test_request_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            request = store.new_request(
                campaign_dir=campaign,
                recommendation=rec(title="Replace on-screen supporting copy"),
                classification=_classification(),
            )
            self.assertEqual(request["revision_request_id"], "revreq_001")
            self.assertEqual(request["status"], store.PROPOSED)
            self.assertTrue(store.store_path(campaign).is_file())

            # A fresh read stands in for restarting the app.
            reloaded = store.get_request(campaign, "revreq_001")
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded["original_value"], "Make more time for reading.")
            self.assertEqual(
                reloaded["original_recommendation"]["title"],
                "Replace on-screen supporting copy",
            )

    def test_editing_the_instruction_keeps_the_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            store.new_request(
                campaign_dir=campaign,
                recommendation=rec(
                    title="Replace on-screen supporting copy",
                    full_instruction="Name the feeling first.",
                ),
                classification=_classification(),
            )
            store.update_request(campaign, "revreq_001", instruction="Name the evening instead.")
            saved = store.get_request(campaign, "revreq_001")
            self.assertEqual(saved["instruction"], "Name the evening instead.")
            self.assertEqual(
                saved["original_recommendation"]["full_instruction"], "Name the feeling first."
            )
            self.assertEqual(saved["default_instruction"], "Rewrite the supporting on-screen copy.")

    def test_options_and_selection_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            store.new_request(
                campaign_dir=campaign,
                recommendation=rec(),
                classification=_classification(),
            )
            store.record_options(
                campaign,
                "revreq_001",
                options=[
                    {
                        "option_id": "option_001",
                        "text": "For the part of you that misses getting lost in a book.",
                        "rationale": "Names the loss.",
                        "validation": {"verdict": PASS, "issues": []},
                    }
                ],
                constraints_used={"max_words": 12},
            )
            saved = store.get_request(campaign, "revreq_001")
            self.assertEqual(saved["status"], store.OPTIONS_READY)
            self.assertEqual(len(saved["generated_options"]), 1)

            store.update_request(
                campaign, "revreq_001", selected_option_id="option_001", status=store.SELECTED
            )
            chosen = store.get_request(campaign, "revreq_001")
            self.assertEqual(
                store.selected_value(chosen),
                "For the part of you that misses getting lost in a book.",
            )

            store.update_request(campaign, "revreq_001", edited_value="For evenings that are yours.")
            edited = store.get_request(campaign, "revreq_001")
            self.assertEqual(store.selected_value(edited), "For evenings that are yours.")

    def test_a_second_round_adds_options_beside_the_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            store.new_request(
                campaign_dir=campaign, recommendation=rec(), classification=_classification()
            )
            store.record_options(
                campaign,
                "revreq_001",
                options=[{"option_id": "option_001", "text": "One."}],
                constraints_used={},
            )
            store.record_options(
                campaign,
                "revreq_001",
                options=[{"option_id": "option_002", "text": "Two."}],
                constraints_used={},
            )
            saved = store.get_request(campaign, "revreq_001")
            self.assertEqual(store.option_texts(saved), ["One.", "Two."])
            self.assertEqual(saved["generation_count"], 2)
            self.assertEqual(store.next_option_index(saved), 3)

    def test_unknown_status_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            store.new_request(
                campaign_dir=campaign, recommendation=rec(), classification=_classification()
            )
            with self.assertRaises(ValueError):
                store.update_request(campaign, "revreq_001", status="halfway")

    def test_grouping_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "demo_campaign"
            campaign.mkdir()
            store.new_request(
                campaign_dir=campaign, recommendation=rec(), classification=_classification()
            )
            store.update_request(campaign, "revreq_001", status=store.SELECTED)
            groups = dict(store.grouped_requests(campaign))
            self.assertIn("Ready to Apply", groups)
            counts = store.counts(campaign)
            self.assertEqual(counts["ready_to_apply"], 1)
            self.assertEqual(counts["awaiting_decision"], 0)
            self.assertEqual(counts["needs_human"], 0)


class RendererSupportTests(unittest.TestCase):
    """What BettyOS claims it can do has to match what the renderers accept."""

    def test_reel_supports_on_screen_copy(self) -> None:
        support = rt.renderer_support(
            template_id="cinematic_multi_clip_reel",
            renderer_module="video",
            field_key="overlay_supporting",
            revision_type_key="supporting_copy_rewrite",
        )
        self.assertTrue(support.supported)
        self.assertTrue(support.requires_rerender)

    def test_no_renderer_accepts_a_font_size_change(self) -> None:
        support = rt.renderer_support(
            template_id="cinematic_multi_clip_reel",
            renderer_module="video",
            field_key="overlay_supporting",
            revision_type_key="font_size_change",
        )
        self.assertFalse(support.supported)
        self.assertTrue(support.reason)

    def test_a_still_image_has_no_cta_timing(self) -> None:
        support = rt.renderer_support(
            template_id="editorial_static_pin",
            renderer_module="static",
            field_key="cta_timing",
            revision_type_key="cta_timing_change",
        )
        self.assertFalse(support.supported)

    def test_every_revision_type_has_a_capability_and_label(self) -> None:
        for key in rt.ALL_TYPES:
            entry = rt.revision_type(key)
            self.assertIsNotNone(entry, key)
            self.assertIn(
                entry.natural_capability,
                {rt.READY_TO_APPLY, rt.AI_ASSISTED, rt.HUMAN_INPUT_REQUIRED},
                key,
            )
            self.assertTrue(rt.type_label(key), key)

    def test_human_requirements_say_what_is_needed(self) -> None:
        for key in rt.ALL_TYPES:
            entry = rt.revision_type(key)
            if entry.natural_capability != rt.HUMAN_INPUT_REQUIRED:
                continue
            requirement = rt.requirement_for(key)
            self.assertTrue(requirement.headline, key)
            self.assertTrue(requirement.specifics, key)
            self.assertTrue(requirement.unlocks, key)


if __name__ == "__main__":
    unittest.main()
