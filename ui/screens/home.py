"""Home — compatibility shim. Prefer Today."""

from __future__ import annotations

from ui.campaign_state import CampaignState
from ui.screens import today


def render(state: CampaignState) -> None:
    today.render(state)
