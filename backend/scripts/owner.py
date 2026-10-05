"""The account the local evaluation scripts act for: the one real account.

Accounts on the reserved ``.test`` domain (local test accounts, e.g. the
perf or UI-check ones) are not the owner and are ignored.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def owner(db: AsyncSession) -> User | None:
    users = (await db.scalars(select(User).where(~User.email.endswith(".test")))).all()
    return users[0] if len(users) == 1 else None
