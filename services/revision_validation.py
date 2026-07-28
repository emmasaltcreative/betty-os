"""Brand safety and quality checks on generated copy.

Every option is checked before a person is shown it, and again after they edit
it. An option that fails a hard check cannot be applied — the interface can
offer to edit it, and the edit is re-checked, but there is no path that puts
rejected copy into a render.

The hard rules come from the Brand Guide's own prohibitions (voice.md) and from
the standing rule that BettyOS never invents a product claim. The soft rules are
the ones a person should look at but may reasonably keep.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PASS = "pass"
NEEDS_ATTENTION = "needs_attention"
REJECTED = "rejected"

VERDICT_LABELS: dict[str, str] = {
    PASS: "Pass",
    NEEDS_ATTENTION: "Needs Attention",
    REJECTED: "Rejected by Validation",
}

# Phrases the Brand Guide names as off-brand, and pressure language it forbids.
BRAND_PROHIBITED: tuple[str, ...] = (
    "elevate your routine",
    "self-care essentials",
    "must-have",
    "must have",
    "cozy season",
    "vibes",
    "game-changer",
    "game changer",
    "don't miss out",
    "dont miss out",
    "do not miss out",
    "you need this",
    "only a few left",
    "last chance",
    "act now",
    "limited time",
    "while supplies last",
    "final hours",
    "selling fast",
    "buy now",
    "hurry",
)

# Softer clichés: worth a second look, not an automatic refusal.
GENERIC_PHRASING: tuple[str, ...] = (
    "curated collection",
    "everyday luxury",
    "little luxuries",
    "treat yourself",
    "level up",
    "transform your",
    "unlock",
    "iconic",
    "obsessed",
    "the perfect",
    "look no further",
    "at the end of the day",
    "in today's world",
    "now more than ever",
    "join us on this journey",
)

# Founder-update register the voice guide rejects.
FOUNDER_REGISTER: tuple[str, ...] = (
    "we're so excited",
    "we are so excited",
    "excited to announce",
    "thrilled to",
    "behind the scenes",
    "launch day",
    "big news",
    "sneak peek",
    "is a literary lifestyle brand",
)

# Claims BettyOS is not allowed to originate.
_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bhand[\s-]?(made|sewn|poured|bound|stitched|packed)\b", "a manufacturing claim"),
    (r"\bartisan(al)?\b", "an artisanal claim"),
    (r"\bsmall[\s-]batch\b", "a production claim"),
    (r"\bsustainably (sourced|made)\b|\beco[\s-]friendly\b", "a sustainability claim"),
    (r"\b(award[\s-]winning|best[\s-]?selling|number one|#1)\b", "a performance claim"),
    (r"\bguaranteed\b|\bclinically\b|\bproven to\b", "an assurance claim"),
    (r"\bfree shipping\b|\bship(s|ping)? worldwide\b", "a fulfilment claim"),
    (r"\$\s?\d|\b\d+\s?%\s?off\b|\b\d+\s?% (more|less)\b", "a price or discount claim"),
    (r"\blimited edition of \d+\b|\bonly \d+ (copies|units|available)\b", "a quantity claim"),
    (r"\bmade in [A-Z][a-z]+\b", "an origin claim"),
)

# Betty never makes or ships anything in the first person.
_PERSONAL_LABOUR = re.compile(
    r"\b(i|we)\s+(sew|sewed|pour|poured|pack|packed|ship|shipped|stitch|stitched|bind|bound|"
    r"hand[\s-]?make|hand[\s-]?made)\b",
    re.IGNORECASE,
)

_IMPERATIVE_PRESSURE = re.compile(
    r"\b(buy|shop|order|grab|claim|secure|get)\s+(it|yours|now|today)\b", re.IGNORECASE
)

_ACRONYMS = {"CTA", "PDF", "UK", "US", "AM", "PM", "OK"}


@dataclass
class Issue:
    check: str
    message: str
    severity: str  # REJECTED | NEEDS_ATTENTION

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "message": self.message, "severity": self.severity}


@dataclass
class Verdict:
    option_id: str
    verdict: str
    issues: list[Issue] = field(default_factory=list)

    @property
    def label(self) -> str:
        return VERDICT_LABELS.get(self.verdict, self.verdict)

    @property
    def can_apply(self) -> bool:
        return self.verdict != REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "verdict": self.verdict,
            "label": self.label,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verdict":
        return cls(
            option_id=str(data.get("option_id") or ""),
            verdict=str(data.get("verdict") or PASS),
            issues=[
                Issue(
                    check=str(raw.get("check") or ""),
                    message=str(raw.get("message") or ""),
                    severity=str(raw.get("severity") or NEEDS_ATTENTION),
                )
                for raw in data.get("issues") or []
                if isinstance(raw, dict)
            ],
        )


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _word_count(text: str) -> int:
    return len([word for word in re.split(r"\s+", text.strip()) if word])


def _shouty_words(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"\b[A-Z]{4,}\b", text)
        if word not in _ACRONYMS
    ]


def validate_option(
    text: str,
    *,
    option_id: str = "option_001",
    original_value: str = "",
    other_options: list[str] | None = None,
    max_words: int | None = None,
    max_chars: int | None = None,
    platform: str = "",
    brand_guide: str = "",
) -> Verdict:
    """Check one option. Hard failures reject it; soft ones ask for a look."""
    issues: list[Issue] = []
    cleaned = text.strip()
    lower = cleaned.lower()

    if not cleaned:
        issues.append(Issue("empty", "This option has no text.", REJECTED))
        return Verdict(option_id, REJECTED, issues)

    for phrase in BRAND_PROHIBITED:
        if phrase in lower:
            issues.append(
                Issue(
                    "prohibited_phrase",
                    f"“{phrase}” is language the Brand Guide rules out.",
                    REJECTED,
                )
            )

    for pattern, description in _CLAIM_PATTERNS:
        if re.search(pattern, cleaned, flags=re.IGNORECASE):
            issues.append(
                Issue(
                    "unsupported_claim",
                    f"This makes {description} the Brand Guide does not support.",
                    REJECTED,
                )
            )

    if _PERSONAL_LABOUR.search(cleaned):
        issues.append(
            Issue(
                "betty_voice",
                "Betty does not sew, pour, pack or ship in the first person.",
                REJECTED,
            )
        )

    if max_words:
        count = _word_count(cleaned)
        if count > int(max_words):
            issues.append(
                Issue(
                    "word_count",
                    f"{count} words, and the limit for this field is {int(max_words)}.",
                    REJECTED,
                )
            )

    if max_chars and len(cleaned) > int(max_chars):
        issues.append(
            Issue(
                "platform_limit",
                f"{len(cleaned)} characters, and {platform or 'this field'} allows "
                f"{int(max_chars)}.",
                REJECTED,
            )
        )

    normalised = _normalise(cleaned)
    if original_value and normalised == _normalise(original_value):
        issues.append(
            Issue("duplicate", "This is the copy that is already there.", REJECTED)
        )
    for other in other_options or []:
        if other.strip() and _normalise(other) == normalised:
            issues.append(
                Issue("duplicate", "This repeats another option word for word.", REJECTED)
            )
            break

    if _IMPERATIVE_PRESSURE.search(cleaned):
        issues.append(
            Issue(
                "cta_pressure",
                "This instructs rather than invites. The Brand Guide asks for an invitation.",
                REJECTED,
            )
        )
    if cleaned.count("!") > 1:
        issues.append(
            Issue("cta_pressure", "More than one exclamation mark reads as pressure.", NEEDS_ATTENTION)
        )
    shouty = _shouty_words(cleaned)
    if shouty:
        issues.append(
            Issue(
                "cta_pressure",
                "Capitalised for emphasis: " + ", ".join(shouty[:3]) + ".",
                NEEDS_ATTENTION,
            )
        )

    for phrase in GENERIC_PHRASING:
        if phrase in lower:
            issues.append(
                Issue("generic_phrasing", f"“{phrase}” is filler phrasing.", NEEDS_ATTENTION)
            )
    for phrase in FOUNDER_REGISTER:
        if phrase in lower:
            issues.append(
                Issue(
                    "betty_voice",
                    f"“{phrase}” is founder-update register, not a note to a friend.",
                    NEEDS_ATTENTION,
                )
            )

    if brand_guide:
        issues.extend(_brand_guide_issues(cleaned, brand_guide))

    if any(issue.severity == REJECTED for issue in issues):
        return Verdict(option_id, REJECTED, issues)
    if issues:
        return Verdict(option_id, NEEDS_ATTENTION, issues)
    return Verdict(option_id, PASS, issues)


_AVOID_CONTEXT = re.compile(r"avoid|do not|don[’']t|never|\bno\b|\bnot\b", re.IGNORECASE)
_CONTRAST = re.compile(r"\bnot\b", re.IGNORECASE)
_QUOTED = re.compile(r"[“\"']([^”\"']{4,60})[”\"']")


def forbidden_quotes(brand_guide: str) -> set[str]:
    """Phrases the Brand Guide itself quotes as language to avoid.

    Reading these from the guide rather than hard-coding them means editing the
    guide changes the checks, which is the point of having a guide.

    The guide often contrasts good phrasing with bad on one line — *invite, don't
    command: "if you'd like," not "you need this"* — so a bare "not" is treated as
    the turn: only the quotes after it are the ones to avoid. Getting this wrong
    would reject Betty's own approved wording.
    """
    forbidden: set[str] = set()
    for line in brand_guide.splitlines():
        if not _AVOID_CONTEXT.search(line):
            continue
        turns = list(_CONTRAST.finditer(line))
        after_turn = [m for m in _QUOTED.finditer(line) if turns and m.start() > turns[-1].end()]
        for match in after_turn or _QUOTED.finditer(line):
            phrase = match.group(1).strip().lower().strip(" .,;:—-")
            if len(phrase.split()) >= 2:
                forbidden.add(phrase)
    return forbidden


def _brand_guide_issues(text: str, brand_guide: str) -> list[Issue]:
    lower = text.lower()
    return [
        Issue(
            "brand_guide",
            f"“{phrase}” is language the Brand Guide asks writers to avoid.",
            NEEDS_ATTENTION,
        )
        for phrase in sorted(forbidden_quotes(brand_guide))
        if phrase in lower and phrase not in BRAND_PROHIBITED
    ]


def validate_options(
    options: list[dict[str, Any]],
    *,
    original_value: str = "",
    max_words: int | None = None,
    max_chars: int | None = None,
    platform: str = "",
    brand_guide: str = "",
) -> dict[str, Verdict]:
    """Check every option, including against each other for duplicates."""
    texts = [str(option.get("text") or "") for option in options]
    verdicts: dict[str, Verdict] = {}
    for index, option in enumerate(options):
        option_id = str(option.get("option_id") or f"option_{index + 1:03d}")
        others = [text for position, text in enumerate(texts) if position != index]
        verdicts[option_id] = validate_option(
            str(option.get("text") or ""),
            option_id=option_id,
            original_value=original_value,
            other_options=others,
            max_words=max_words,
            max_chars=max_chars,
            platform=platform,
            brand_guide=brand_guide,
        )
    return verdicts


def summarise(verdicts: dict[str, Verdict]) -> str:
    """One line describing a set of verdicts."""
    if not verdicts:
        return "Nothing to check."
    counts = {PASS: 0, NEEDS_ATTENTION: 0, REJECTED: 0}
    for verdict in verdicts.values():
        counts[verdict.verdict] = counts.get(verdict.verdict, 0) + 1
    parts = [
        f"{counts[PASS]} passed",
        f"{counts[NEEDS_ATTENTION]} need attention",
        f"{counts[REJECTED]} rejected",
    ]
    return ", ".join(part for part in parts if not part.startswith("0 "))
