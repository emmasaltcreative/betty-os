"""Restrained em-dash usage — detection, rewrite, and intentional retention."""

from __future__ import annotations

import unittest

from services.em_dash import (
    choose_simpler_join,
    contains_em_dash,
    evaluate_em_dashes,
    rationale_justifies_em_dash,
    rewrite_em_dashes,
)
from services.revision_validation import NEEDS_ATTENTION, validate_option


class EmDashRewriteTests(unittest.TestCase):
    def test_unnecessary_em_dash_removed(self) -> None:
        report = evaluate_em_dashes("Soft light — an open page.")
        self.assertTrue(report.needs_attention)
        self.assertGreaterEqual(report.rewritten_count, 1)
        self.assertFalse(contains_em_dash(report.rewritten))
        self.assertNotIn("—", report.rewritten)

    def test_sentence_split_used_instead(self) -> None:
        rewritten = rewrite_em_dashes("Stillness — soft light on an open page.")
        self.assertEqual(rewritten, "Stillness. Soft light on an open page.")

    def test_colon_used_for_clarification(self) -> None:
        rewritten = rewrite_em_dashes(
            "Join for one reason — early access to First Edition."
        )
        self.assertEqual(
            rewritten, "Join for one reason: early access to First Edition."
        )
        self.assertEqual(
            choose_simpler_join("Join for one reason", "early access to First Edition."),
            "Join for one reason: early access to First Edition.",
        )

    def test_approved_intentional_em_dash_retained(self) -> None:
        rationale = "Keeps hook visibility and reading rhythm in this short line."
        self.assertTrue(rationale_justifies_em_dash(rationale))
        report = evaluate_em_dashes(
            "The hour that is yours — keep it.",
            rationale=rationale,
        )
        self.assertIn("—", report.rewritten)
        self.assertEqual(report.rewritten_count, 0)
        self.assertGreaterEqual(report.retained_count, 1)

    def test_historical_approved_copy_unchanged(self) -> None:
        original = "A quiet reading hour — already yours."
        report = evaluate_em_dashes(original, preserve=True)
        self.assertEqual(report.rewritten, original)
        self.assertTrue(report.needs_attention)
        self.assertEqual(report.rewritten_count, 0)

    def test_quoted_material_preserved(self) -> None:
        original = 'She whispered “wait — then turn the page.”'
        report = evaluate_em_dashes(original)
        self.assertEqual(report.rewritten, original)
        self.assertEqual(report.rewritten_count, 0)

    def test_validation_marks_needs_attention_and_rewrites(self) -> None:
        verdict = validate_option("Soft light — an open page.")
        self.assertEqual(verdict.verdict, NEEDS_ATTENTION)
        self.assertTrue(any(i.check == "em_dash" for i in verdict.issues))
        self.assertIsNotNone(verdict.rewritten_text)
        self.assertNotIn("—", verdict.rewritten_text or "")


if __name__ == "__main__":
    unittest.main()
