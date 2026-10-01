"""Text extraction and maths-damage detection on generated files."""

import io
from pathlib import Path

from PIL import Image

from app.core.config import get_config
from app.ingestion.extract import VisionReason, extract, render_pdf_page
from app.ingestion.maths_damage import Span, measure, measure_text
from app.ingestion.validation import Kind
from tests import factories

CONFIG = get_config().platform.ingestion
DAMAGE = CONFIG.maths_damage


# --- maths damage --------------------------------------------------------------


def test_prose_scores_low() -> None:
    assert measure_text(factories.PROSE, DAMAGE).score < DAMAGE.threshold


def test_equation_debris_scores_high() -> None:
    report = measure_text("\n".join(["Vectors", *factories.DEBRIS]), DAMAGE)
    assert report.score >= DAMAGE.threshold
    assert report.signals["orphan_lines"] > 0.5


def test_maths_fonts_raise_the_score() -> None:
    plain = measure([[Span("the sum of x over i", "Helvetica")]], DAMAGE)
    maths = measure([[Span("the sum of x over i", "CMMI10")]], DAMAGE)
    assert maths.score > plain.score
    assert maths.score >= DAMAGE.threshold


def test_broken_glyphs_alone_cross_the_threshold() -> None:
    text = factories.PROSE + " \ue000\ue001\ufffd"
    assert measure_text(text, DAMAGE).score >= DAMAGE.threshold


def test_empty_page_scores_zero() -> None:
    assert measure_text("   \n", DAMAGE).score == 0.0


# --- PDF -----------------------------------------------------------------------


def test_pdf_prose_becomes_markdown_with_headings(tmp_path: Path) -> None:
    path = factories.pdf(tmp_path / "a.pdf", [factories.PROSE], heading="Integration by Parts")
    [page] = extract(path, Kind.PDF, CONFIG)
    assert page.markdown.startswith("# Integration by Parts")
    assert "product rule for derivatives" in page.markdown
    assert page.vision_reason is None


def test_damaged_maths_page_is_sent_to_vision(tmp_path: Path) -> None:
    prose, maths = extract(factories.damaged_maths_pdf(tmp_path / "a.pdf"), Kind.PDF, CONFIG)
    assert prose.vision_reason is None
    assert maths.vision_reason is VisionReason.MATHS_DAMAGE
    assert maths.damage >= DAMAGE.threshold


def test_scanned_page_is_sent_to_vision_but_blank_page_is_not(tmp_path: Path) -> None:
    scanned, blank = extract(factories.scanned_pdf(tmp_path / "a.pdf"), Kind.PDF, CONFIG)
    assert scanned.vision_reason is VisionReason.SCANNED
    assert blank.vision_reason is None
    assert blank.markdown == ""


def test_rendered_pages_respect_the_size_cap(tmp_path: Path) -> None:
    path = factories.pdf(tmp_path / "a.pdf")
    png = render_pdf_page(path, 1, dpi=300, max_long_edge=800)
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG"
        assert max(image.size) <= 800


# --- Office --------------------------------------------------------------------


def test_word_equations_become_latex(tmp_path: Path) -> None:
    source = (
        "# Calculus\n\nThe area is $\\int_0^1 x^2\\,dx = \\frac{1}{3}$.\n\n"
        "$$\\int u\\,dv = uv - \\int v\\,du$$\n"
    )
    [page] = extract(factories.docx(tmp_path / "a.docx", source), Kind.DOCX, CONFIG)
    assert "# Calculus" in page.markdown
    # Plain dollar maths only: the renderer cannot read GitHub's $`...`$ form.
    assert "\\frac{1}{3}$" in page.markdown
    assert "$$\\int u" in page.markdown  # display maths stays display
    assert "$`" not in page.markdown
    assert "```math" not in page.markdown


def test_slides_keep_titles_bullets_tables_and_notes(tmp_path: Path) -> None:
    first, second = extract(factories.pptx(tmp_path / "a.pptx"), Kind.PPTX, CONFIG)
    assert first.markdown.startswith("## Eigenvalues")
    assert "- Definition" in first.markdown
    assert "  - Av = λv for non-zero v" in first.markdown
    assert "**Speaker notes:** Stress the non-zero condition." in first.markdown
    assert "| term | rate |" in second.markdown
    assert first.vision_reason is None


def test_spreadsheets_are_summarised(tmp_path: Path) -> None:
    [sheet] = extract(factories.xlsx(tmp_path / "a.xlsx"), Kind.XLSX, CONFIG)
    assert sheet.markdown.startswith("## Sheet: Prices")
    assert "4 rows × 2 columns" in sheet.markdown
    assert "| price | 4 | 99 | 102.25 | 100.688 |" in sheet.markdown


def test_csv_is_summarised(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_text("ticker;return\nAAA;0.05\nBBB;-0.02\n", encoding="utf-8")
    [page] = extract(path, Kind.CSV, CONFIG)
    assert "2 rows × 2 columns" in page.markdown
    assert "| AAA | 0.05 |" in page.markdown


def test_images_always_go_to_vision(tmp_path: Path) -> None:
    [page] = extract(tmp_path / "unused.png", Kind.PNG, CONFIG)
    assert page.vision_reason is VisionReason.IMAGE


# --- table detection ------------------------------------------------------------


def test_real_tables_are_kept() -> None:
    from app.ingestion.extract.pdf import plausible_table

    rows = [["term", "rate"], ["1y", "4.5%"], ["2y", "4.7%"]]
    assert plausible_table(rows, CONFIG.table_min_fill)


def test_graph_gridlines_and_sparse_boxes_are_not_tables() -> None:
    from app.ingestion.extract.pdf import plausible_table

    # Tick labels stacked in one cell.
    axis: list[list[str | None]] = [["8\n6\n4\n2", "x"], ["0", "y"]]
    sparse: list[list[str | None]] = [
        ["Theorem 3.2", None, None],
        [None, None, None],
        [None, "N", None],
    ]
    single_row: list[list[str | None]] = [["a", "b", "c"]]
    cases: list[list[list[str | None]]] = [axis, sparse, single_row]
    for rows in cases:
        assert not plausible_table(rows, CONFIG.table_min_fill)


def test_clean_text_keeps_whitespace_and_drops_controls() -> None:
    from app.ingestion.text import clean_text

    raw = "a" + chr(0) + "b" + chr(0x1B) + "c" + chr(0x7F) + "\td\ne\rf"
    assert clean_text(raw) == "abc\td\ne\rf"
