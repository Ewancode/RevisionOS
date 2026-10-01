import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.errors import AppError
from app.services.users import create_user
from tests.support import PASSWORD

pytestmark = pytest.mark.db


async def test_create_user_normalises_and_creates_settings(db: AsyncSession) -> None:
    user = await create_user(
        db,
        get_config().platform.auth,
        email="  Ewan@Example.COM ",
        display_name=" Ewan ",
        password=PASSWORD,
    )
    assert user.email == "ewan@example.com"
    assert user.display_name == "Ewan"
    assert user.settings.theme == "system"
    assert PASSWORD not in user.password_hash


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [
        ("not-an-email", PASSWORD, "invalid_email"),
        ("x@example.com", "short", "password_too_short"),
        ("EWAN@example.com", PASSWORD, "email_taken"),
    ],
)
async def test_create_user_rejections(
    db: AsyncSession, email: str, password: str, code: str
) -> None:
    config = get_config().platform.auth
    await create_user(db, config, email="ewan@example.com", display_name="E", password=PASSWORD)
    with pytest.raises(AppError) as exc_info:
        await create_user(db, config, email=email, display_name="E", password=password)
    assert exc_info.value.code == code
