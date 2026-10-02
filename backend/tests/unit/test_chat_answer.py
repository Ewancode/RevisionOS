"""Assembling answers: citation checks, markers, provenance, fallback echo."""

import uuid
from types import SimpleNamespace

from app.ai.chat import CITE_MARKER, Answer, echo_content, verify
from app.ai.tools import Source, source_id
from tests.fakes import cite, text


def _source(page: int, tier: str = "university", doc: uuid.UUID | None = None) -> Source:
    doc = doc or uuid.uuid4()
    return Source(
        source=source_id(doc, page),
        title=f"Notes.pdf — page {page}",
        document_id=doc,
        filename="Notes.pdf",
        page_no=page,
        source_tier=tier,
        module_code="MATH101",
        heading_path="Chapter 1",
    )


def test_markers_follow_the_cited_text_and_number_pages_once() -> None:
    doc = uuid.uuid4()
    sources = [_source(4, doc=doc), _source(9, "own", doc=doc), _source(4, doc=doc)]
    answer = Answer(max_quote=10)
    answer.add_text_block(text("First claim.\n\n", cite(0, sources[0].source, "x" * 50)), sources)
    answer.add_text_block(
        text("Second", cite(1, sources[1].source), cite(2, sources[2].source)), sources
    )

    assert answer.content == ("First claim. [[1]](#cite-1)\n\nSecond [[2]](#cite-2)[[1]](#cite-1)")
    assert [(c["n"], c["page_no"]) for c in answer.citations] == [(1, 4), (2, 9)]
    assert answer.citations[0]["quote"] == "x" * 10
    assert answer.provenance == ["own", "university"]
    assert CITE_MARKER.sub("", answer.content) == "First claim.\n\nSecond"


def test_an_answer_without_verified_citations_is_general_knowledge() -> None:
    answer = Answer(max_quote=10)
    answer.add_text_block(text("From memory."), [])
    assert answer.provenance == ["general"]


def test_verify_requires_matching_position_and_source() -> None:
    sources = [_source(1), _source(2)]
    assert verify(cite(1, sources[1].source), sources) == sources[1]
    assert verify(cite(0, sources[1].source), sources) is None  # wrong position
    assert verify(cite(2, sources[1].source), sources) is None  # out of range
    assert verify(cite(-1, sources[1].source), sources) is None
    other_kind = SimpleNamespace(
        type="page_location", search_result_index=0, source=sources[0].source
    )
    assert verify(other_kind, sources) is None


def test_rounds_of_the_loop_become_paragraphs() -> None:
    answer = Answer(max_quote=10)
    answer.add_text_block(text("Let me check."), [])
    answer.separate_rounds()
    answer.add_text_block(text("Found it."), [])
    assert answer.content == "Let me check.\n\nFound it."


def test_echo_is_unchanged_without_a_fallback() -> None:
    blocks = [SimpleNamespace(type="thinking"), text("a"), SimpleNamespace(type="tool_use")]
    assert echo_content(blocks) == blocks


def test_echo_after_a_fallback_keeps_only_text_before_the_marker() -> None:
    thinking, partial = SimpleNamespace(type="thinking"), text("partial")
    marker, after_text = SimpleNamespace(type="fallback"), text("rest")
    after_tool = SimpleNamespace(type="tool_use")
    blocks = [thinking, partial, SimpleNamespace(type="tool_use"), marker, after_text, after_tool]
    assert echo_content(blocks) == [partial, marker, after_text, after_tool]
