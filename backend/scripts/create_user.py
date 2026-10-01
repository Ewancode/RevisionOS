"""Create an account. Registration is closed; this is the only way in.

Usage: ``make create-user`` (or ``python -m scripts.create_user``).
The password is read without echo and never logged.
"""

import asyncio
import getpass
import sys

from app.core.config import get_config
from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.users import create_user


async def _create(email: str, display_name: str, password: str) -> int:
    engine = create_engine(get_settings().database_url.get_secret_value())
    try:
        async with create_session_factory(engine)() as db:
            user = await create_user(
                db,
                get_config().platform.auth,
                email=email,
                display_name=display_name,
                password=password,
            )
    except AppError as exc:
        print(f"Could not create account: {exc.message}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(f"Created account for {user.email}.")
    return 0


def main() -> int:
    email = input("Email: ").strip()
    display_name = input("Display name (used in greetings): ").strip()
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    return asyncio.run(_create(email, display_name, password))


if __name__ == "__main__":
    raise SystemExit(main())
