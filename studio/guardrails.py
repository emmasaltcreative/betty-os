"""Oh Betty Jaletti production guardrails for Studio metadata."""

from __future__ import annotations

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.models import utc_now_iso
from studio.paths import guardrails_path

OBJ_GUARDRAILS = [
    "The Heirloom Book Cover has a continuous shell.",
    "Do not add a sewn spine seam.",
    "Do not create a permanent sharp spine crease.",
    "Preserve the jade exterior color.",
    "Preserve the cream poplin lining.",
    "Preserve the fixed inward flaps.",
    "Preserve the left bookmark-pocket flap.",
    "Preserve the right-side elastic placement.",
    "Preserve the woven-label placement.",
    "Do not add decorative front-cover ornamentation.",
    "Do not invent products or accessories.",
    "Do not change product proportions materially.",
    "Do not misrepresent material texture or construction.",
]


def ensure_guardrails(brand_id: str = DEFAULT_BRAND_ID) -> dict:
    path = guardrails_path(brand_id)
    data = load_json(path, default=None)
    if isinstance(data, dict) and data.get("rules"):
        return data
    payload = {
        "brand_id": brand_id,
        "product": "Heirloom Book Cover — The Reading Hour",
        "verification": "Not Automatically Verified",
        "note": (
            "These rules guide human review and future semantic validation. "
            "Studio does not claim visual verification of product construction."
        ),
        "rules": list(OBJ_GUARDRAILS),
        "updated_at": utc_now_iso(),
    }
    atomic_write_json(path, payload)
    return payload


def list_guardrails(brand_id: str = DEFAULT_BRAND_ID) -> list[str]:
    data = ensure_guardrails(brand_id)
    return list(data.get("rules") or [])
