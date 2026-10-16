"""Configurable strategy rules and brand calendar rules."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from src.common import BRANDS_DIR, DEFAULT_BRAND_ID, PRODUCTION_DIR
from src.persistence import atomic_write_json, load_json

STRATEGY_RULES_PATH = PRODUCTION_DIR / "strategy_rules.json"
USER_STRATEGY_OVERRIDES_PATH = PRODUCTION_DIR / "strategy_rules.user.json"


def load_strategy_rules() -> dict[str, Any]:
    base = load_json(STRATEGY_RULES_PATH, default={}) or {}
    overrides = load_json(USER_STRATEGY_OVERRIDES_PATH, default={}) or {}
    merged = deepcopy(base)
    _deep_merge(merged, overrides)
    return merged


def save_strategy_overrides(overrides: dict[str, Any]) -> Path:
    """Persist user overrides only — never rewrite shipped defaults."""
    return atomic_write_json(USER_STRATEGY_OVERRIDES_PATH, overrides)


def load_calendar_rules(brand_id: str = DEFAULT_BRAND_ID) -> dict[str, Any]:
    path = BRANDS_DIR / brand_id / "calendar_rules.json"
    return load_json(path, default={}) or {}


def lead_time_rule(key: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = rules or load_strategy_rules()
    lead_times = rules.get("lead_times") or {}
    return dict(lead_times.get(key) or {})


def preferred_cadence(
    platform: str, rules: dict[str, Any] | None = None
) -> tuple[int, int]:
    rules = rules or load_strategy_rules()
    freq = (rules.get("preferred_posting_frequency") or {}).get(platform) or {}
    return int(freq.get("min_per_week") or 1), int(freq.get("max_per_week") or 2)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
