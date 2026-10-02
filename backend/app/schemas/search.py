import uuid
from typing import Literal

from app.schemas.common import Output


class PassageOut(Output):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    module_id: uuid.UUID
    module_code: str
    page_no: int
    heading_path: str
    content: str
    source_tier: Literal["university", "own"]
    score: float
    matched: Literal["keyword", "meaning", "both"]


class NamedModule(Output):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    code: str
    title: str


class NamedTopic(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    title: str


class NamedDocument(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    original_filename: str


class SearchOut(Output):
    query: str
    # The scope actually searched; wider than requested when the requested
    # scope found too little.
    scope_used: Literal["topic", "module", "year", "all"]
    widened: bool
    passages: list[PassageOut]
    modules: list[NamedModule]
    topics: list[NamedTopic]
    documents: list[NamedDocument]
