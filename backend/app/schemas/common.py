from typing import Annotated, ClassVar, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, model_validator


def _lower(value: str) -> str:
    return value.lower()


class Input(BaseModel):
    """Base for request bodies: unknown fields are an error, not ignored."""

    model_config = ConfigDict(extra="forbid")


class Patch(Input):
    """Partial update. An omitted field is left unchanged; an explicit null
    clears an optional field and is rejected for a required one."""

    required_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_null_for_required(self) -> Self:
        for name in self.model_fields_set & self.required_fields:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        return self.model_dump(exclude_unset=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _text(max_length: int) -> object:
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


Text40 = Annotated[str, _text(40)]
Text60 = Annotated[str, _text(60)]
Text80 = Annotated[str, _text(80)]
Text200 = Annotated[str, _text(200)]

HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$"), AfterValidator(_lower)]
