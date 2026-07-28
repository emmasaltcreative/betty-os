"""Reading and rewriting one field of a copy document.

A revision must change the field it was asked to change and nothing else. The
safest way to guarantee that is never to re-render the document: locate the
value's character span, splice the replacement in, and leave every other byte
alone. That is what `CopyDocument` does.

The documents involved are the ones BettyOS writes itself — the `caption.md`
beside a video render, and the markdown drafts from `renderers/copy.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VIDEO_CAPTIONS = "video_captions"
INSTAGRAM_CAPTION = "instagram_caption"
PINTEREST_METADATA = "pinterest_metadata"
EMAIL = "email"
GENERIC = "generic"

# Lines that open or close a document rather than belonging to its body. Both
# are anchored per line: the letter templates write a heading first, so a
# salutation is never at the start of the file.
_SIGNOFF = re.compile(r"^(with care|warmly|yours|— *betty|love,)", re.IGNORECASE | re.MULTILINE)
_SALUTATION = re.compile(r"^(dear\b|hello\b|hi\b)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def detect_kind(text: str) -> str:
    head = text[:400].lower()
    if "# captions" in head:
        return VIDEO_CAPTIONS
    if "pinterest pin description" in head:
        return PINTEREST_METADATA
    if "# instagram caption" in head:
        return INSTAGRAM_CAPTION
    if _SALUTATION.search(text) and _SIGNOFF.search(text):
        return EMAIL
    return GENERIC


# --- Locating values ---------------------------------------------------------

def _paragraphs(text: str, *, offset: int = 0) -> list[Span]:
    """Blank-line separated blocks, as spans into the original string."""
    spans: list[Span] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        chunk = match.group(0)
        if not chunk.strip():
            continue
        start = offset + match.start() + (len(chunk) - len(chunk.lstrip()))
        end = offset + match.end() - (len(chunk) - len(chunk.rstrip()))
        spans.append(Span(start, end))
    return spans


def _h1_span(text: str) -> Span | None:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    if not match:
        return None
    return Span(match.start(1), match.end(1))


def _section_span(text: str, heading: str) -> Span | None:
    """Body of a `## Heading` section, without its surrounding blank lines."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    body_start = match.end()
    following = re.search(r"^##\s+", text[body_start:], flags=re.MULTILINE)
    body_end = body_start + following.start() if following else len(text)
    body = text[body_start:body_end]
    lead = len(body) - len(body.lstrip("\n "))
    trail = len(body) - len(body.rstrip("\n "))
    return Span(body_start + lead, body_end - trail)


def _label_span(text: str, label: str) -> Span | None:
    """Value of a `**Label:**` field, inline or on the lines beneath it."""
    pattern = rf"^\*\*{re.escape(label)}:\*\*[ \t]*(.*)$"
    match = re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    inline = match.group(1).strip()
    if inline:
        return Span(match.start(1) + (len(match.group(1)) - len(match.group(1).lstrip())),
                    match.start(1) + len(match.group(1).rstrip()))
    # Block form: the value sits on the following lines.
    body_start = match.end() + 1
    following = re.search(r"^(\*\*[^*]+:\*\*|##\s+)", text[body_start:], flags=re.MULTILINE)
    body_end = body_start + following.start() if following else len(text)
    body = text[body_start:body_end]
    lead = len(body) - len(body.lstrip("\n "))
    trail = len(body) - len(body.rstrip("\n "))
    return Span(body_start + lead, body_end - trail)


def _body_spans(text: str) -> list[Span]:
    """Paragraphs that are prose, excluding headings, salutation and sign-off."""
    spans: list[Span] = []
    for span in _paragraphs(text):
        chunk = text[span.start : span.end]
        if chunk.lstrip().startswith("#"):
            continue
        if _SALUTATION.match(chunk.strip()) and len(chunk.strip()) < 40:
            continue
        if _SIGNOFF.match(chunk.strip()):
            continue
        spans.append(span)
    return spans


# --- The document ------------------------------------------------------------

@dataclass
class CopyDocument:
    path: Path
    text: str
    kind: str

    @classmethod
    def load(cls, path: Path) -> "CopyDocument":
        text = path.read_text(encoding="utf-8")
        return cls(path=path, text=text, kind=detect_kind(text))

    @classmethod
    def from_text(cls, text: str, *, path: Path | None = None) -> "CopyDocument":
        return cls(path=path or Path("untitled.md"), text=text, kind=detect_kind(text))

    # --- field lookup -------------------------------------------------------

    def span_for(self, field_key: str) -> Span | None:
        """Where this field's value sits, or None when the document has no such field.

        Each document kind knows only its own fields. An Instagram caption file
        has no email subject, and saying otherwise would let a revision write
        the wrong value into the wrong place.
        """
        finder = getattr(self, f"_find_{self.kind}", None)
        if finder is None:
            return self._find_generic(field_key)
        return finder(field_key)

    def _find_video_captions(self, field_key: str) -> Span | None:
        if field_key == "instagram_caption":
            return _section_span(self.text, "Instagram")
        if field_key in {"pinterest_caption", "pinterest_description"}:
            return _section_span(self.text, "Pinterest")
        return None

    def _find_instagram_caption(self, field_key: str) -> Span | None:
        if field_key != "instagram_caption":
            return None
        spans = _body_spans(self.text)
        if not spans:
            return None
        # The renderer writes the caption, then the CTA as its own last block.
        if len(spans) > 1:
            return Span(spans[0].start, spans[-2].end)
        return spans[0]

    def _find_pinterest_metadata(self, field_key: str) -> Span | None:
        label = {
            "pinterest_title": "Title",
            "pinterest_description": "Description",
            "pinterest_caption": "Description",
            "pinterest_cta": "CTA",
        }.get(field_key)
        return _label_span(self.text, label) if label else None

    def _find_email(self, field_key: str) -> Span | None:
        if field_key == "email_subject":
            return _h1_span(self.text)
        if field_key == "email_preview":
            return _label_span(self.text, "Preview text")
        if field_key not in {"email_body", "email_cta"}:
            return None
        spans = _body_spans(self.text)
        if not spans:
            return None
        if field_key == "email_cta":
            return spans[-1]
        return Span(spans[0].start, spans[-2].end) if len(spans) > 1 else spans[0]

    def _find_generic(self, field_key: str) -> Span | None:
        if field_key == "email_subject":
            return _h1_span(self.text)
        if field_key not in {"product_copy", "instagram_caption"}:
            return None
        spans = _body_spans(self.text)
        if not spans:
            return None
        return Span(spans[0].start, spans[-1].end)

    # --- read and write -----------------------------------------------------

    def read(self, field_key: str) -> str | None:
        span = self.span_for(field_key)
        if span is None:
            return None
        return self.text[span.start : span.end].strip()

    def replaced(self, field_key: str, value: str) -> str:
        """The whole document with one field replaced. Everything else is untouched."""
        span = self.span_for(field_key)
        cleaned = value.strip()
        if span is None:
            return self._inserted(field_key, cleaned)
        return self.text[: span.start] + cleaned + self.text[span.end :]

    def _inserted(self, field_key: str, value: str) -> str:
        """Add a field the document does not have yet, in the form the renderer uses."""
        if field_key == "email_preview":
            heading = _h1_span(self.text)
            if heading is not None:
                line_end = self.text.find("\n", heading.end)
                cut = len(self.text) if line_end < 0 else line_end + 1
                return f"{self.text[:cut]}\n**Preview text:** {value}\n{self.text[cut:]}"
        if field_key.startswith("pinterest") and self.kind == VIDEO_CAPTIONS:
            body = self.text if self.text.endswith("\n") else self.text + "\n"
            return f"{body}\n## Pinterest\n\n{value}\n"
        body = self.text if self.text.endswith("\n") else self.text + "\n"
        return f"{body}\n{value}\n"

    def fields_present(self) -> list[str]:
        """Fields this document actually holds, one entry per distinct value."""
        candidates = (
            "instagram_caption",
            "pinterest_title",
            "pinterest_description",
            "pinterest_caption",
            "pinterest_cta",
            "email_subject",
            "email_preview",
            "email_body",
            "email_cta",
            "product_copy",
        )
        found: list[str] = []
        claimed: set[tuple[int, int]] = set()
        for key in candidates:
            span = self.span_for(key)
            if span is None or not self.text[span.start : span.end].strip():
                continue
            marker = (span.start, span.end)
            if marker in claimed:
                continue
            claimed.add(marker)
            found.append(key)
        return found


def read_field(path: Path, field_key: str) -> str | None:
    if not path.is_file():
        return None
    return CopyDocument.load(path).read(field_key)
