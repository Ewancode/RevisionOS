"""Turn a validated file into page-level Markdown (ARCHITECTURE.md section 7).

Each extractor returns one ExtractedPage per page / slide / sheet / file,
flagging the pages whose content must be read from an image by Claude.
"""

from pathlib import Path

from app.core.config import IngestionConfig
from app.ingestion.extract.common import ExtractedPage, VisionReason
from app.ingestion.extract.office import extract_docx, extract_pptx
from app.ingestion.extract.pdf import extract_pdf, render_pdf_page
from app.ingestion.extract.tabular import extract_csv, extract_xlsx
from app.ingestion.validation import IMAGE_KINDS, Kind


def extract(path: Path, kind: Kind, config: IngestionConfig) -> list[ExtractedPage]:
    if kind is Kind.PDF:
        return extract_pdf(path, config)
    if kind is Kind.DOCX:
        return extract_docx(path, config)
    if kind is Kind.PPTX:
        return extract_pptx(path, config)
    if kind is Kind.XLSX:
        return extract_xlsx(path, config)
    if kind is Kind.CSV:
        return extract_csv(path, config)
    if kind in (Kind.TEXT, Kind.MARKDOWN):
        text = path.read_text(encoding="utf-8-sig")
        return [ExtractedPage(1, text.strip(), 0.0, None)]
    if kind in IMAGE_KINDS:
        # Photos and screenshots have no text layer: the image is the content.
        return [ExtractedPage(1, "", 1.0, VisionReason.IMAGE)]
    raise ValueError(f"no extractor for {kind}")


__all__ = ["ExtractedPage", "VisionReason", "extract", "render_pdf_page"]
