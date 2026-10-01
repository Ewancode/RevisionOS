"""SQLAlchemy models. Import every model module here so Alembic sees it."""

from app.models.identity import AuditLog, AuthSession, User, UserSettings
from app.models.structure import AcademicYear, Module, Topic

__all__ = [
    "AcademicYear",
    "AuditLog",
    "AuthSession",
    "Module",
    "Topic",
    "User",
    "UserSettings",
]
