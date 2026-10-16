"""Minimal DOCX writer using only the standard library.

DOCX is a ZIP of XML parts. This avoids requiring python-docx for campaign
copy deliverables while remaining editable in Word / Pages / Google Docs.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape


def build_docx(
    paragraphs: list[str],
    *,
    title: str = "Document",
    logo_png: bytes | None = None,
) -> bytes:
    """Return DOCX bytes for a simple multi-paragraph document.

    When ``logo_png`` is provided, the active brand mark is embedded at the top
    without stretching (EMU sizing preserves a square-ish mark).
    """
    body_parts: list[str] = []
    relationships: list[str] = []
    media_parts: list[tuple[str, bytes]] = []

    if logo_png:
        # 1 inch ≈ 914400 EMUs. Keep mark restrained (~0.7").
        cx = 640080  # ~0.7"
        cy = 640080
        body_parts.append(
            "<w:p>"
            "<w:r>"
            '<w:drawing>'
            '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
            f'distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/>'
            '<wp:docPr id="1" name="BrandMark"/>'
            "<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
            "<pic:pic>"
            "<pic:nvPicPr><pic:cNvPr id=\"0\" name=\"logo.png\"/><pic:cNvPicPr/></pic:nvPicPr>"
            '<pic:blipFill><a:blip r:embed="rIdImage1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/>"
            f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
            "</w:r></w:p>"
        )
        relationships.append(
            '<Relationship Id="rIdImage1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/logo.png"/>'
        )
        media_parts.append(("word/media/logo.png", logo_png))

    body_parts.append(
        "<w:p>"
        "<w:pPr><w:pStyle w:val=\"Title\"/></w:pPr>"
        f"<w:r><w:t>{escape(title)}</w:t></w:r>"
        "</w:p>"
    )
    for text in paragraphs:
        if text.startswith("# "):
            body_parts.append(
                "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>"
                f"<w:r><w:t>{escape(text[2:].strip())}</w:t></w:r></w:p>"
            )
        elif text.startswith("## "):
            body_parts.append(
                "<w:p><w:pPr><w:pStyle w:val=\"Heading2\"/></w:pPr>"
                f"<w:r><w:t>{escape(text[3:].strip())}</w:t></w:r></w:p>"
            )
        elif not text.strip():
            body_parts.append("<w:p/>")
        else:
            body_parts.append(
                f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
            )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{''.join(body_parts)}<w:sectPr/></w:body></w:document>"
    )

    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>',
    ]
    if logo_png:
        defaults.append('<Default Extension="png" ContentType="image/png"/>')

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + "".join(defaults)
        + "</Types>"
    )
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(relationships)
        + "</Relationships>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document_xml)
        if relationships:
            archive.writestr("word/_rels/document.xml.rels", doc_rels)
        for name, payload in media_parts:
            archive.writestr(name, payload)
    return buffer.getvalue()
