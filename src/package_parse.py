"""Content-package parsing helpers shared by create and review flows."""

from __future__ import annotations

import re


def list_content_pieces(package_text: str) -> list[dict[str, str]]:
    """Parse content-package piece headings into ordered records."""
    heading_re = re.compile(
        r"^###\s+Piece\s+#?(?P<num>\d+)\s*[—\-–:-]\s*(?P<title>.+?)\s*$",
        flags=re.MULTILINE,
    )
    matches = list(heading_re.finditer(package_text))
    pieces: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(package_text)
        trailing = re.search(
            r"\n## (?:Priority Order|Missing Assets)\b",
            package_text[start:end],
        )
        if trailing:
            end = start + trailing.start()
        title = match.group("title").strip()
        title = re.sub(r"^\*+|\*+$", "", title).strip()
        title = title.strip("\"'")
        pieces.append(
            {
                "number": match.group("num"),
                "title": title,
                "heading": match.group(0).strip(),
                "body": package_text[start:end],
            }
        )
    return pieces


def find_piece_body(
    package_text: str,
    *,
    title_regex: str,
    preferred_numbers: tuple[str, ...] = (),
) -> str:
    pieces = list_content_pieces(package_text)
    title_re = re.compile(title_regex, flags=re.IGNORECASE)
    for number in preferred_numbers:
        for piece in pieces:
            if piece["number"] == number and title_re.search(piece["title"]):
                return piece["body"]
    for piece in pieces:
        if title_re.search(piece["title"]):
            return piece["body"]
    for number in preferred_numbers:
        for piece in pieces:
            if piece["number"] == number:
                return piece["body"]
    raise RuntimeError(f"Could not find a matching content piece ({title_regex}).")


def clean_blockquote_caption(raw: str) -> str:
    lines: list[str] = []
    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            stripped = stripped[1:].strip()
        lines.append(stripped)
    return "\n".join(lines).strip()


def extract_campaign_goal(package_text: str) -> str | None:
    """Pull campaign goal from a content package when present."""
    match = re.search(
        r"\*\*Goal\*\*\s*\n([^\n*]+(?:\n(?!\*\*)[^\n]+)*)",
        package_text,
        flags=re.IGNORECASE,
    )
    if match:
        return " ".join(match.group(1).split())
    match = re.search(
        r"(?im)^(?:\*\*)?Goal(?:\*\*)?\s*[:\-]\s*(.+)$",
        package_text,
    )
    if match:
        return match.group(1).strip()
    return None


def extract_piece4_captions(package_text: str) -> tuple[str, str]:
    """Return (instagram_caption, pinterest_caption) for the Page Turn Loop piece."""
    try:
        section = find_piece_body(
            package_text,
            title_regex=r"page[\s\-]?turn\s+loop",
            preferred_numbers=("4",),
        )
    except RuntimeError as exc:
        raise RuntimeError("Could not find Piece #4 in the latest content package.") from exc

    ig = re.search(
        r"\*\*Caption \(Instagram\):\*\*\s*(.*?)(?=\n\*\*Caption \(Pinterest\):\*\*|\n\*\*CTA:|\Z)",
        section,
        flags=re.DOTALL | re.IGNORECASE,
    )
    pin = re.search(
        r"\*\*Caption \(Pinterest\):\*\*\s*(.*?)(?=\n\*\*CTA:|\n\*\*Suggested|\Z)",
        section,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not ig or not pin:
        raise RuntimeError("Could not find Instagram/Pinterest captions for Piece #4.")

    return clean_blockquote_caption(ig.group(1)), clean_blockquote_caption(pin.group(1))


def extract_piece2_instagram_caption(package_text: str) -> str:
    """Return the Instagram caption from The Ritual Reel piece."""
    try:
        section = find_piece_body(
            package_text,
            title_regex=r"ritual\s+reel",
            preferred_numbers=("2",),
        )
    except RuntimeError as exc:
        raise RuntimeError("Could not find Piece #2 in the latest content package.") from exc

    caption = re.search(
        r"\*\*Caption:\*\*\s*(.*?)(?=\n\*\*CTA:|\n\*\*Suggested|\Z)",
        section,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not caption:
        raise RuntimeError("Could not find Instagram caption for Piece #2.")
    return clean_blockquote_caption(caption.group(1))
