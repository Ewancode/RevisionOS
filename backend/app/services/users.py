"""Account creation (registration is closed: `make create-user` only) and settings."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AuthConfig
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import User, UserSettings
from app.repositories.identity import UserRepository
from app.schemas.auth import SettingsUpdate
from app.services.auth import validate_new_password


async def create_user(
    db: AsyncSession, config: AuthConfig, *, email: str, display_name: str, password: str
) -> User:
    email = email.strip().lower()
    if "@" not in email or len(email) > 320:
        raise AppError("invalid_email", "That does not look like an email address.", 422)
    display_name = display_name.strip()
    if not 1 <= len(display_name) <= 80:
        raise AppError("invalid_display_name", "Display name must be 1-80 characters.", 422)
    validate_new_password(password, config)
    if await UserRepository(db).by_email(email) is not None:
        raise AppError("email_taken", "An account with that email already exists.", 409)

    user = User(
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        settings=UserSettings(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_settings(db: AsyncSession, user: User, body: SettingsUpdate) -> User:
    changes = body.changes()
    if "display_name" in changes:
        user.display_name = str(changes.pop("display_name"))
    for field, value in changes.items():
        setattr(user.settings, field, value)
    await db.commit()
    await db.refresh(user)
    return user
