import uuid
from datetime import date, datetime
from typing import Annotated, ClassVar, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from app.schemas.common import HexColour, Input, Output, Patch, Text40, Text60, Text200


def _upper(value: str) -> str:
    return value.upper()


ModuleCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=20),
    AfterValidator(_upper),
    StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9 _-]*$"),
]
Credits = Annotated[int, Field(ge=0, le=120)]
Importance = Annotated[int, Field(ge=1, le=5)]
ModuleStatus = Literal["active", "archived"]


# --- academic years ---------------------------------------------------------


class YearCreate(Input):
    label: Text40
    start_date: date
    end_date: date
    is_current: bool = False

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class YearUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"label", "start_date", "end_date"})

    label: Text40 | None = None
    start_date: date | None = None
    end_date: date | None = None


class YearOut(Output):
    id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    is_current: bool


# --- modules -----------------------------------------------------------------


class ModuleCreate(Input):
    academic_year_id: uuid.UUID
    code: ModuleCode
    title: Text200
    subject_tag: Text60 | None = None
    credits: Credits | None = None
    colour: HexColour | None = None


class ModuleUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"code", "title", "status"})

    code: ModuleCode | None = None
    title: Text200 | None = None
    subject_tag: Text60 | None = None
    credits: Credits | None = None
    colour: HexColour | None = None
    status: ModuleStatus | None = None


class ModuleOut(Output):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    code: str
    title: str
    subject_tag: str | None
    credits: int | None
    colour: str | None
    status: ModuleStatus


# --- topics ------------------------------------------------------------------


class TopicCreate(Input):
    title: Text200
    parent_id: uuid.UUID | None = None
    importance: Importance = 3


class TopicUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"title", "importance"})

    title: Text200 | None = None
    importance: Importance | None = None


class TopicMove(Input):
    parent_id: uuid.UUID | None
    # Index among the new siblings; past the end means "last".
    position: Annotated[int, Field(ge=0)]


class TopicOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    position: int
    importance: int


class TopicNode(TopicOut):
    children: list["TopicNode"] = Field(default_factory=list)


# --- trash -------------------------------------------------------------------


class TrashedModule(Output):
    id: uuid.UUID
    code: str
    title: str
    deleted_at: datetime


class TrashedTopic(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    title: str
    deleted_at: datetime


class TrashedDocument(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    original_filename: str
    deleted_at: datetime


class TrashedMaterial(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    title: str
    deleted_at: datetime


class TrashedFlashcard(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    front_md: str
    deleted_at: datetime


class TrashOut(Output):
    retention_days: int
    modules: list[TrashedModule]
    topics: list[TrashedTopic]
    documents: list[TrashedDocument]
    materials: list[TrashedMaterial]
    flashcards: list[TrashedFlashcard]
