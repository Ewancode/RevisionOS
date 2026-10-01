import uuid
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from app.schemas.common import Input, Output, Patch

SourceTier = Literal["university", "own"]
MaterialKind = Literal["lecture", "problem_sheet", "solutions", "past_paper", "notes", "other"]
Week = Annotated[int, Field(ge=0, le=60)]
# A page of Markdown; generous, but bounded.
PageMarkdown = Annotated[str, Field(max_length=200_000)]


class DocumentOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    original_filename: str
    mime: str
    size_bytes: int
    source_tier: SourceTier
    material_kind: MaterialKind
    week: int | None
    status: Literal["queued", "processing", "ready", "failed"]
    stage: str
    progress: int
    error_code: str | None
    page_count: int | None
    created_at: datetime


class DocumentProgress(Output):
    status: Literal["queued", "processing", "ready", "failed"]
    stage: str
    progress: int
    error_code: str | None


class DocumentUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"source_tier", "material_kind"})

    topic_id: uuid.UUID | None = None
    source_tier: SourceTier | None = None
    material_kind: MaterialKind | None = None
    week: Week | None = None


class PageOut(Output):
    page_no: int
    markdown: str
    extraction_method: Literal["text", "vision", "corrected", "unreadable"]
    maths_damage_score: float
    needs_review: bool
    review_note: str | None


class PageCorrection(Input):
    markdown: PageMarkdown


class BudgetOut(Output):
    currency: str
    spent_today: float
    spent_this_month: float
    daily_cap: float
    monthly_cap: float
    warning: bool
    exhausted: bool
    configured: bool
