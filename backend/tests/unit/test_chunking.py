"""Chunking rules (ARCHITECTURE.md section 7, step 3)."""

from app.core.config import get_config
from app.retrieval.chunking import chunk_document, split_blocks

CONFIG = get_config().retrieval.chunking
PARA = "Integration by parts follows from the product rule for derivatives. " * 3


def test_display_maths_spanning_blank_lines_is_one_block() -> None:
    md = "Before.\n\n$$\n\\begin{aligned}\na &= b\n\n&= c\n\\end{aligned}\n$$\n\nAfter."
    blocks = split_blocks(md)
    assert [b.kind for b in blocks] == ["text", "maths", "text"]
    assert "&= c" in blocks[1].text


def test_code_fences_keep_blank_lines() -> None:
    blocks = split_blocks("```python\nx = 1\n\ny = 2\n```")
    assert len(blocks) == 1 and blocks[0].kind == "code"


def test_headings_carry_across_pages_and_start_chunks() -> None:
    pages = [
        (1, "# Integration\n\n" + PARA + "\n\n## By parts\n\n" + PARA),
        (2, "Continued discussion of the method. " + PARA),
    ]
    chunks = chunk_document(pages, CONFIG)
    assert [c.heading_path for c in chunks] == [
        "Integration",
        "Integration › By parts",
        "Integration › By parts",
    ]
    assert [c.page_no for c in chunks] == [1, 1, 2]
    assert chunks[1].content.startswith("## By parts")


def test_theorems_and_proofs_start_new_chunks() -> None:
    md = (
        PARA
        + "\n\n**Theorem 3.1.** Every bounded monotone sequence converges.\n\n"
        + "*Proof.* Let $a_n$ be increasing and bounded above."
    )
    chunks = chunk_document([(1, md)], CONFIG)
    assert chunks[1].content.startswith("**Theorem 3.1.**")
    # A short theorem keeps its proof: they are retrieved together.
    assert "*Proof.*" in chunks[1].content


def test_a_long_section_ends_before_the_next_definition() -> None:
    md = "\n\n".join([PARA] * 3) + "\n\n**Definition 2.4.** A sequence is Cauchy if..."
    chunks = chunk_document([(1, md)], CONFIG)
    assert chunks[-1].content.startswith("**Definition 2.4.**")


def test_chunks_respect_the_size_cap_but_never_split_equations() -> None:
    long_equation = "$$\n" + " + ".join(f"a_{{{i}}} x^{{{i}}}" for i in range(400)) + "\n$$"
    md = "\n\n".join([PARA] * 12 + [long_equation])
    chunks = chunk_document([(1, md)], CONFIG)
    for chunk in chunks:
        if "$$" in chunk.content:
            assert chunk.content.count("$$") % 2 == 0  # equation whole
        else:
            assert chunk.token_estimate <= CONFIG.max_tokens
    assert sum("a_{399}" in c.content for c in chunks) == 1


def test_size_cuts_overlap_by_one_short_block() -> None:
    paragraphs = [f"Paragraph {i}. " + "word " * 35 for i in range(12)]
    chunks = chunk_document([(1, "\n\n".join(paragraphs))], CONFIG)
    assert len(chunks) > 1
    shared = [p for p in paragraphs if sum(p.strip() in c.content for c in chunks) > 1]
    assert shared  # at least one cut repeated its last block


def test_long_tables_split_between_rows_and_repeat_the_header() -> None:
    rows = "\n".join(f"| {i} | {i * i} |" for i in range(300))
    chunks = chunk_document([(1, "| n | square |\n| --- | --- |\n" + rows)], CONFIG)
    assert len(chunks) > 1
    assert all(c.content.startswith("| n | square |") for c in chunks)


def test_empty_and_heading_only_pages_produce_no_chunks() -> None:
    assert chunk_document([(1, ""), (2, "# Just a title")], CONFIG) == []
