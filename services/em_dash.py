"""Restrained em-dash usage for BettyOS-generated copy.

Default: do not use em dashes. Prefer periods, commas, colons, parentheses,
or separate sentences. An em dash may stay only when a stated rationale shows
it materially improves hook visibility, reading rhythm, emotional emphasis,
scanability, or conversion clarity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

EM_DASH = "\u2014"  # —

_INTENTIONAL_CUES = re.compile(
    r"\b("
    r"hook|visibility|rhythm|emphasis|scanab|scannab|conversion|"
    r"emotional|short[- ]form|pause|beat|contrast|punch|growth"
    r")\b",
    re.IGNORECASE,
)

_QUOTED_SPAN = re.compile(r"(“[^”]*”|\"[^\"]*\"|'[^']*')")

# Numeric / technical ranges that legitimately use a dash character.
_TECHNICAL_RANGE = re.compile(r"(?i)(?<![A-Za-z])\d+\s*[\u2013\u2014-]\s*\d+(?![A-Za-z])")

_DASH_TOKEN = re.compile(r"\s*—\s*|---")

_CLARIFY_LEFT = re.compile(
    r"(?i)\b(reason|note|detail|idea|truth|rule|point|meaning|definition)\b\.?$"
)


@dataclass
class EmDashHit:
    start: int
    end: int
    left: str
    right: str
    in_quotes: bool = False
    technical: bool = False
    necessary: bool = False
    reason: str = ""


@dataclass
class EmDashReport:
    original: str
    rewritten: str
    hits: list[EmDashHit] = field(default_factory=list)
    rewritten_count: int = 0
    retained_count: int = 0
    needs_attention: bool = False
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "rewritten": self.rewritten,
            "rewritten_count": self.rewritten_count,
            "retained_count": self.retained_count,
            "needs_attention": self.needs_attention,
            "messages": list(self.messages),
            "hits": [
                {
                    "start": h.start,
                    "end": h.end,
                    "necessary": h.necessary,
                    "reason": h.reason,
                    "in_quotes": h.in_quotes,
                    "technical": h.technical,
                }
                for h in self.hits
            ],
        }


def contains_em_dash(text: str) -> bool:
    if not text:
        return False
    return EM_DASH in text or "---" in text


def rationale_justifies_em_dash(rationale: str | None) -> bool:
    if not rationale or not rationale.strip():
        return False
    return bool(_INTENTIONAL_CUES.search(rationale))


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _QUOTED_SPAN.finditer(text)]


def _technical_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _TECHNICAL_RANGE.finditer(text)]


def _in_spans(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in spans)


def find_em_dashes(text: str) -> list[EmDashHit]:
    """Locate decorative em dashes (and --- stand-ins), noting quoted/technical."""
    if not text:
        return []
    quoted = _quoted_spans(text)
    technical = _technical_spans(text)
    hits: list[EmDashHit] = []
    for match in _DASH_TOKEN.finditer(text):
        start, end = match.start(), match.end()
        in_quotes = _in_spans(start, quoted)
        is_technical = _in_spans(start, technical)
        hits.append(
            EmDashHit(
                start=start,
                end=end,
                left=text[max(0, start - 48) : start].rstrip(),
                right=text[end : end + 48].lstrip(),
                in_quotes=in_quotes,
                technical=is_technical,
                necessary=in_quotes or is_technical,
                reason=(
                    "Quoted material preserved."
                    if in_quotes
                    else "Technical range preserved."
                    if is_technical
                    else "Unnecessary em dash; prefer simpler punctuation."
                ),
            )
        )
    return hits


def _capitalize_sentence(text: str) -> str:
    if not text:
        return text
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1 :]
    return text


def choose_simpler_join(left: str, right: str) -> str:
    """Join two sides that an em dash previously connected."""
    left_t = left.rstrip()
    right_t = right.lstrip()
    if not right_t:
        return left_t
    if not left_t:
        return right_t

    # Clarification after a labeled left side → colon
    if _CLARIFY_LEFT.search(left_t.rstrip(".,:;")) or re.search(
        r"(?i)\bfor (one|this|that)\b.+$", left_t
    ):
        return f"{left_t}: {right_t[0].lower() + right_t[1:] if right_t[0:1].isupper() and len(right_t) > 1 else right_t}"

    # Default for prose clauses → sentence split
    if left_t[-1:] in ".!?":
        return f"{left_t} {_capitalize_sentence(right_t)}"
    return f"{left_t}. {_capitalize_sentence(right_t)}"


def evaluate_em_dashes(
    text: str,
    *,
    rationale: str | None = None,
    preserve: bool = False,
    product_names: list[str] | None = None,
) -> EmDashReport:
    """Detect and rewrite unnecessary em dashes.

    preserve=True keeps historical / approved copy unchanged (detection only).
    A justifying rationale may retain a single intentional dash; multiple dashes
    in short copy are always rewritten.
    """
    original = text or ""
    hits = find_em_dashes(original)
    report = EmDashReport(original=original, rewritten=original, hits=hits)
    if not hits:
        return report

    protected = [n for n in (product_names or []) if n and contains_em_dash(n)]

    def _in_product(hit: EmDashHit) -> bool:
        for name in protected:
            idx = original.find(name)
            if idx >= 0 and idx <= hit.start < idx + len(name):
                return True
        return False

    for hit in hits:
        if _in_product(hit):
            hit.necessary = True
            hit.reason = "Product name preserved."

    short_copy = len(original.split()) <= 40
    allow_intentional = rationale_justifies_em_dash(rationale)
    candidates = [h for h in hits if not h.necessary]

    if preserve:
        if candidates:
            report.needs_attention = True
            report.messages.append(
                "Em dash present in approved historical copy; left unchanged."
            )
        report.retained_count = len(hits)
        return report

    if allow_intentional and candidates:
        if short_copy and len(candidates) > 1:
            report.messages.append(
                "Multiple em dashes in short copy; simplified punctuation applied."
            )
        else:
            candidates[0].necessary = True
            candidates[0].reason = (
                "Intentional em dash retained: rationale cites visibility, rhythm, "
                "or growth benefit."
            )
            candidates = candidates[1:]

    if not candidates:
        report.retained_count = sum(1 for h in hits if h.necessary or h.in_quotes or h.technical)
        return report

    report.needs_attention = True
    report.messages.append(
        "Unnecessary em dash marked Needs Attention and rewritten with simpler punctuation."
    )

    pieces: list[str] = []
    cursor = 0
    rewritten = 0
    retained = 0
    for hit in hits:
        pieces.append(original[cursor : hit.start])
        if hit.necessary or hit.in_quotes or hit.technical:
            pieces.append(original[hit.start : hit.end])
            retained += 1
        else:
            pieces.append("\0EM\0")
            rewritten += 1
        cursor = hit.end
    pieces.append(original[cursor:])

    merged = "".join(pieces)
    while "\0EM\0" in merged:
        left, _, rest = merged.partition("\0EM\0")
        merged = choose_simpler_join(left, rest)

    merged = re.sub(r"[ \t]{2,}", " ", merged)
    merged = re.sub(r" +\n", "\n", merged)
    merged = re.sub(r"\.\s*\.", ".", merged).strip()

    report.rewritten = merged
    report.rewritten_count = rewritten
    report.retained_count = retained
    return report


def rewrite_em_dashes(
    text: str,
    *,
    rationale: str | None = None,
    preserve: bool = False,
    product_names: list[str] | None = None,
) -> str:
    return evaluate_em_dashes(
        text,
        rationale=rationale,
        preserve=preserve,
        product_names=product_names,
    ).rewritten


EM_DASH_RULE_SUMMARY = (
    "Do not use em dashes by default. Prefer periods, commas, colons, parentheses, "
    "or separate sentences. An em dash may be used only when it materially improves "
    "hook visibility, reading rhythm, emotional emphasis, scanability, or conversion "
    "clarity, and the rationale must state that benefit. Never use multiple em dashes "
    "in one short piece of copy."
)
