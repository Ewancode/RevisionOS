"""SQLAlchemy models. Import every model module here so Alembic sees it."""

from app.models.ai import AIInteraction, AIUsage
from app.models.chat import Conversation, Message, PendingAction
from app.models.coding import CodingExercise, CodingSubmission, TutorHint
from app.models.content import Document, DocumentPage
from app.models.identity import AuditLog, AuthSession, User, UserSettings
from app.models.learning import FlashcardReview, LearningProfileSnapshot, TopicMastery
from app.models.planner import (
    AvailabilityOverride,
    AvailabilityRule,
    Exam,
    ExamTopic,
    Notification,
    RevisionPlan,
    StudySession,
)
from app.models.practice import (
    Draft,
    Flashcard,
    Material,
    MaterialVersion,
    Question,
    QuestionAttempt,
    Quiz,
    QuizAttempt,
    QuizItem,
)
from app.models.retrieval import Chunk
from app.models.structure import AcademicYear, Module, Topic

__all__ = [
    "AIInteraction",
    "AIUsage",
    "AcademicYear",
    "AuditLog",
    "AuthSession",
    "AvailabilityOverride",
    "AvailabilityRule",
    "Chunk",
    "CodingExercise",
    "CodingSubmission",
    "Conversation",
    "Document",
    "DocumentPage",
    "Draft",
    "Exam",
    "ExamTopic",
    "Flashcard",
    "FlashcardReview",
    "LearningProfileSnapshot",
    "Material",
    "MaterialVersion",
    "Message",
    "Module",
    "Notification",
    "PendingAction",
    "Question",
    "QuestionAttempt",
    "Quiz",
    "QuizAttempt",
    "QuizItem",
    "RevisionPlan",
    "StudySession",
    "Topic",
    "TopicMastery",
    "TutorHint",
    "User",
    "UserSettings",
]
