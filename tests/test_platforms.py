"""Regression tests for canonical platform normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.platforms import (
    PLATFORM_OPTIONS,
    canonical_platform,
    clear_unknown_platform_diagnostics,
    multiselect_platform_defaults,
    normalize_platforms,
    unknown_platform_diagnostics,
)


class PlatformVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_unknown_platform_diagnostics()

    def test_lowercase_stored_values(self) -> None:
        result = normalize_platforms(["instagram", "pinterest", "tiktok", "email"])
        self.assertEqual(
            result.selected, ["Instagram", "Pinterest", "TikTok", "Email"]
        )
        self.assertEqual(result.unknown, [])

    def test_display_case_stored_values(self) -> None:
        result = normalize_platforms(["Instagram", "Pinterest", "YouTube Shorts"])
        self.assertEqual(result.selected, ["Instagram", "Pinterest", "YouTube Shorts"])

    def test_legacy_aliases(self) -> None:
        cases = {
            "instagram_reels": "Instagram",
            "reels": "Instagram",
            "Instagram Reels (9:16)": "Instagram",
            "Instagram Feed (4:5)": "Instagram",
            "Pinterest (2:3)": "Pinterest",
            "tik tok": "TikTok",
            "youtube_shorts": "YouTube Shorts",
            "waitlist": "Waitlist",
        }
        for raw, expected in cases.items():
            self.assertEqual(canonical_platform(raw), expected, msg=raw)

        result = normalize_platforms(list(cases.keys()))
        self.assertEqual(
            result.selected,
            ["Instagram", "Pinterest", "TikTok", "YouTube Shorts", "Waitlist"],
        )
        self.assertEqual(result.unknown, [])

    def test_unknown_stored_values_are_excluded_and_recorded(self) -> None:
        result = normalize_platforms(
            ["Instagram", "Myspace", "BeReal"],
            source="test.unknown",
        )
        self.assertEqual(result.selected, ["Instagram"])
        self.assertEqual(result.unknown, ["Myspace", "BeReal"])
        diagnostics = unknown_platform_diagnostics()
        values = {entry["value"] for entry in diagnostics}
        self.assertIn("Myspace", values)
        self.assertIn("BeReal", values)
        self.assertTrue(all(entry["source"] == "test.unknown" for entry in diagnostics))

    def test_empty_platform_list_uses_fallback_for_multiselect(self) -> None:
        defaults = multiselect_platform_defaults(
            [],
            fallback=("Instagram", "Pinterest"),
            source="test.empty",
        )
        self.assertEqual(defaults, ["Instagram", "Pinterest"])
        self.assertTrue(set(defaults).issubset(set(PLATFORM_OPTIONS)))

    def test_multiple_valid_platforms(self) -> None:
        defaults = multiselect_platform_defaults(
            ["pinterest", "Email", "tiktok"],
            source="test.multi",
        )
        self.assertEqual(defaults, ["Pinterest", "Email", "TikTok"])

    def test_existing_campaign_geometry_labels(self) -> None:
        """Live Oh Betty piece platforms must map into widget options."""
        stored = [
            "Instagram Feed (4:5)",
            "Instagram Reels (9:16)",
            "Pinterest (2:3)",
        ]
        defaults = multiselect_platform_defaults(stored, source="test.ob")
        self.assertEqual(defaults, ["Instagram", "Pinterest"])
        self.assertTrue(all(item in PLATFORM_OPTIONS for item in defaults))
        self.assertEqual(unknown_platform_diagnostics(), [])

    def test_never_returns_invalid_default(self) -> None:
        result = normalize_platforms(
            ["instagram", "Unknown Channel", "Pinterest (2:3)"],
            source="test.guard",
        )
        for item in result.selected:
            self.assertIn(item, PLATFORM_OPTIONS)

    def test_candidate_priority_preserves_valid_session_over_empty_state(self) -> None:
        defaults = multiselect_platform_defaults(
            [],
            ["tiktok", "email"],
            fallback=("Instagram",),
            source="test.priority",
        )
        self.assertEqual(defaults, ["TikTok", "Email"])

    def test_historical_unknowns_remain_in_result(self) -> None:
        raw = ["Instagram Reels (9:16)", "Legacy Blog", "pinterest"]
        result = normalize_platforms(raw, source="test.history")
        self.assertEqual(result.selected, ["Instagram", "Pinterest"])
        self.assertEqual(result.unknown, ["Legacy Blog"])
        # Caller can keep unknown strings alongside normalized selections.
        recovered = result.selected + result.unknown
        self.assertIn("Legacy Blog", recovered)


if __name__ == "__main__":
    unittest.main()
