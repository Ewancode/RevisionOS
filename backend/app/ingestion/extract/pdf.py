"""PDF pages to Markdown with PyMuPDF, plus page rendering for vision and previews."""

import logging
import re
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pymupdf

from app.core.config import IngestionConfig
from app.ingestion.extract.common import ExtractedPage, VisionReason
from app.ingestion.maths_damage import Span, measure

logger = logging.getLogger(__name__)

# Heading levels by font size relative to the page's body text. These are
# layout heuristics for Markdown structure, not tunable behaviour.
_H1, _H2, _H3 = 1.6, 1.35, 1.2
_NUMBER = re.compile(r"[−-]?\d+(\.\d+)?")
_LIST_ITEM = re.compile(r"^(\d{1,3}[.)]|[a-z][.)]|[•▪◦–*-])\s")


def _body_size(blocks: list[dict[str, Any]]) -> float:
    sizes: list[float] = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line["spans"]:
                sizes.extend([span["size"]] * len(span["text"].strip()))
    return statistics.median(sizes) if sizes else 10.0


def _heading_prefix(size: float, body: float) -> str:
    ratio = size / body if body else 1.0
    if ratio >= _H1:
        return "# "
    if ratio >= _H2:
        return "## "
    if ratio >= _H3:
        return "### "
    return ""


def _mostly_inside(bbox: tuple[float, float, float, float], areas: list[pymupdf.Rect]) -> bool:
    """True if at least half the block lies inside one of `areas` (a table)."""
    rect = pymupdf.Rect(bbox)
    for area in areas:
        overlap = rect & area
        if not overlap.is_empty and overlap.get_area() >= 0.5 * rect.get_area():
            return True
    return False


def _starts_list_item(text: str) -> bool:
    return bool(_LIST_ITEM.match(text))


def plausible_table(rows: Sequence[Sequence[object]], min_fill: float) -> bool:
    """Is a detected table a real table?

    PyMuPDF's detector also fires on graph gridlines (cells holding axis
    tick labels such as "8\n6\n4") and on boxed theorems. Real tables have
    at least two rows and columns, are mostly filled, and no cell is a stack
    of bare numbers.
    """
    if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
        return False
    cells = [c for row in rows for c in row]
    texts = [str(c).strip() for c in cells if c is not None and str(c).strip()]
    if len(texts) < min_fill * len(cells):
        return False
    return not any(
        "\n" in t
        and all(_NUMBER.fullmatch(part.strip()) for part in t.splitlines() if part.strip())
        for t in texts
    )


def _page_markdown(page: pymupdf.Page, table_min_fill: float) -> tuple[str, list[list[Span]], int]:
    """Markdown for one page, its lines of spans (for damage scoring), and
    the number of non-space characters."""
    # Real tables become Markdown tables; their area is then skipped as prose.
    # Anything rejected or failing to convert stays on the prose path, so no
    # text is lost.
    tables: list[tuple[float, pymupdf.Rect, str]] = []
    try:
        found = list(page.find_tables().tables)
    except Exception:  # table detection is best-effort
        found = []
    for table in found:
        try:
            if not plausible_table(table.extract(), table_min_fill):
                continue
            tables.append((table.bbox[1], pymupdf.Rect(table.bbox), table.to_markdown().strip()))
        except Exception:
            logger.debug("table to markdown failed", exc_info=True)
    table_areas = [area for _, area, _ in tables]

    data = page.get_text("dict", sort=True)
    blocks = [b for b in data["blocks"] if b.get("type") == 0]
    body = _body_size(blocks)

    parts: list[tuple[float, str]] = []
    lines_for_score: list[list[Span]] = []
    chars = 0
    for block in blocks:
        block_lines = block.get("lines", [])
        for line in block_lines:
            lines_for_score.append([Span(s["text"], s["font"]) for s in line["spans"]])
            chars += sum(not c.isspace() for s in line["spans"] for c in s["text"])
        if _mostly_inside(block["bbox"], table_areas):
            continue
        texts = ["".join(s["text"] for s in line["spans"]).strip() for line in block_lines]
        texts = [t for t in texts if t]
        if not texts:
            continue
        largest = max(s["size"] for line in block_lines for s in line["spans"])
        prefix = _heading_prefix(largest, body) if len(texts) <= 2 else ""
        if prefix:
            parts.append((block["bbox"][1], prefix + " ".join(texts)))
        else:
            # Keep list items on their own lines; join wrapped prose.
            joined: list[str] = []
            for text in texts:
                if joined and not _starts_list_item(text):
                    joined[-1] += " " + text
                else:
                    joined.append(text)
            parts.append((block["bbox"][1], "\n".join(joined)))

    parts.extend((top, markdown) for top, _, markdown in tables)

    parts.sort(key=lambda p: p[0])
    return "\n\n".join(text for _, text in parts), lines_for_score, chars


def extract_pdf(path: Path, config: IngestionConfig) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            markdown, lines, chars = _page_markdown(page, config.table_min_fill)
            report = measure(lines, config.maths_damage)
            reason: VisionReason | None = None
            if report.score >= config.maths_damage.threshold:
                reason = VisionReason.MATHS_DAMAGE
            elif chars < config.scanned_page_min_chars and (
                page.get_images() or page.get_drawings()
            ):
                # Little or no text layer but something drawn: a scan, photo or
                # diagram. A page with neither is genuinely blank.
                reason = VisionReason.SCANNED
            pages.append(ExtractedPage(index, markdown, report.score, reason))
    return pages


def render_pdf_page(path: Path, page_no: int, dpi: int, max_long_edge: int | None = None) -> bytes:
    """PNG of one page at `dpi`, scaled down so its long edge fits."""
    with pymupdf.open(path) as doc:
        page = doc[page_no - 1]
        zoom = dpi / 72
        if max_long_edge:
            longest = max(page.rect.width, page.rect.height) * zoom
            if longest > max_long_edge:
                zoom *= max_long_edge / longest
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return bytes(pixmap.tobytes("png"))
