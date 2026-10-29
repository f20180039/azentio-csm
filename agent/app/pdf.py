"""Text-layer extraction with hidden-text detection."""
from dataclasses import dataclass, field

import fitz  # PyMuPDF

NEAR_WHITE = 0xF0  # every RGB channel at or above this counts as white-on-white
MIN_FONT_PT = 2.0


@dataclass
class HiddenSpan:
    page: int
    text: str
    reason: str  # white_text | tiny_font | off_page


@dataclass
class ParsedPdf:
    page_count: int
    pages: list[dict] = field(default_factory=list)  # visible text only: [{"page", "text"}]
    hidden: list[HiddenSpan] = field(default_factory=list)
    # Fonts of each visible line, index-aligned with the lines of pages[i]["text"]; edited digits often switch font.
    line_fonts: list[list[list[str]]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class PdfError(ValueError):
    pass


def _is_near_white(color: int) -> bool:
    r, g, b = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    return min(r, g, b) >= NEAR_WHITE


def _hidden_reason(span: dict, page_rect: fitz.Rect) -> str | None:
    if _is_near_white(span["color"]):
        return "white_text"
    if span["size"] < MIN_FONT_PT:
        return "tiny_font"
    if not fitz.Rect(span["bbox"]).intersects(page_rect):
        return "off_page"
    return None


def parse(data: bytes, max_pages: int) -> ParsedPdf:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several types for corrupt input
        raise PdfError(f"not a readable PDF: {exc}") from exc
    with doc:
        if doc.page_count > max_pages:
            raise PdfError(f"PDF has {doc.page_count} pages; the limit is {max_pages}")
        result = ParsedPdf(page_count=doc.page_count, meta=_meta(doc))
        for index, page in enumerate(doc, start=1):
            lines: list[str] = []
            fonts: list[list[str]] = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    visible: list[str] = []
                    line_fonts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            visible.append(text)
                            continue
                        reason = _hidden_reason(span, page.rect)
                        if reason:
                            result.hidden.append(HiddenSpan(index, text.strip(), reason))
                        else:
                            visible.append(text)
                            if span["font"] not in line_fonts:
                                line_fonts.append(span["font"])
                    joined = "".join(visible).strip()
                    if joined:
                        lines.append(joined)
                        fonts.append(line_fonts)
            result.pages.append({"page": index, "text": "\n".join(lines)})
            result.line_fonts.append(fonts)
        return result


def _meta(doc: fitz.Document) -> dict:
    """Document properties that edit detection reads. Each incremental save adds a version; counting
    startxref instead would misread a linearized ("fast web view") file as edited."""
    m = doc.metadata or {}
    return {
        "producer": m.get("producer") or None,
        "creator": m.get("creator") or None,
        "created_at": m.get("creationDate") or None,
        "modified_at": m.get("modDate") or None,
        "incremental_updates": max(0, doc.version_count - 1),
        "fonts": sorted({f[3] for i in range(doc.page_count) for f in doc.get_page_fonts(i)}),
    }
