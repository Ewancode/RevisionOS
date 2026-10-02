"""SQLAlchemy models. Import every model module here so Alembic sees it."""

from app.models.ai import AIInteraction, AIUsage
from app.models.chat import Conversation, Message, PendingAction
from app.models.content import Document, DocumentPage
from app.models.identity import AuditLog, AuthSession, User, UserSettings
from app.models.retrieval import Chunk
from app.models.structure import AcademicYear, Module, Topic

__all__ = [
    "AIInteraction",
    "AIUsage",
    "AcademicYear",
    "AuditLog",
    "AuthSession",
    "Chunk",
    "Conversation",
    "Document",
    "DocumentPage",
    "Message",
    "Module",
    "PendingAction",
    "Topic",
    "User",
    "UserSettings",
]
