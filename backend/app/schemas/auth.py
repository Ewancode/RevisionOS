import uuid
from typing import ClassVar, Literal

from pydantic import Field

from app.schemas.common import HexColour, Input, Output, Patch, Text80


class LoginRequest(Input):
    # Length limits only; the real checks happen against the stored hash.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(Input):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class UserOut(Output):
    id: uuid.UUID
    email: str
    display_name: str


class SettingsOut(Output):
    theme: Literal["light", "dark", "system"]
    accent_colour: str


class SessionOut(Output):
    user: UserOut
    settings: SettingsOut


class SettingsUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset(
        {"display_name", "theme", "accent_colour"}
    )

    display_name: Text80 | None = None
    theme: Literal["light", "dark", "system"] | None = None
    accent_colour: HexColour | None = None
