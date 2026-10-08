"""The question bank, flashcards, quizzes, mock exams and marking
(SPEC 21-29 and 36)."""

import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.api.uploads import receive_to_file
from app.practice.answers import Difficulty, QuestionType
from app.schemas.practice import (
    ActiveExam,
    AttemptListItem,
    AttemptOut,
    AttemptStarted,
    FlashcardCreate,
    FlashcardOut,
    FlashcardUpdate,
    PhotoTranscription,
    QuestionOut,
    QuestionUpdate,
    QuizCreate,
    QuizOut,
    ResponseSave,
    ScoreOverride,
)
from app.services.bank import BankFilters, FlashcardService, QuestionService
from app.services.quizzes import QuizService

router = APIRouter(tags=["practice"])


def _questions(db: DbSession, user: CurrentUser, client: Client, config: Config) -> QuestionService:
    return QuestionService(db, user.id, client, config=config)


def _flashcards(
    request: Request, db: DbSession, user: CurrentUser, client: Client
) -> FlashcardService:
    return FlashcardService(db, user.id, client, embedder=request.app.state.embedder)


def _quizzes(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> QuizService:
    state = request.app.state
    return QuizService(
        db,
        user.id,
        client,
        config=config,
        jobs=state.jobs,
        storage=state.storage,
        claude=state.claude,
    )


Questions = Annotated[QuestionService, Depends(_questions)]
Flashcards = Annotated[FlashcardService, Depends(_flashcards)]
Quizzes = Annotated[QuizService, Depends(_quizzes)]


# --- question bank -------------------------------------------------------------------------


@router.get("/questions", response_model=list[QuestionOut])
async def question_bank(
    module_id: uuid.UUID,
    questions: Questions,
    topic_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    difficulty: Annotated[list[Difficulty] | None, Query()] = None,
    type: Annotated[list[QuestionType] | None, Query()] = None,
    result: Literal["any", "unattempted", "wrong", "right"] = "any",
    origin: Literal["user", "claude"] | None = None,
    status_: Annotated[Literal["active", "retired"], Query(alias="status")] = "active",
) -> list[QuestionOut]:
    """A module's questions with your latest result on each, filtered."""
    return await questions.bank(
        module_id,
        BankFilters(
            topic_ids=topic_id,
            difficulties=difficulty,
            types=type,
            result=result,
            origin=origin,
            status=status_,
        ),
    )


@router.patch("/questions/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: uuid.UUID, body: QuestionUpdate, questions: Questions
) -> QuestionOut:
    """Move to a topic, relabel the difficulty, or retire (and un-retire) it.
    Questions are retired rather than deleted, so your attempts keep meaning."""
    return QuestionOut.model_validate(await questions.update(question_id, body))


# --- flashcards ------------------------------------------------------------------------------


@router.get("/flashcards", response_model=list[FlashcardOut])
async def list_flashcards(
    module_id: uuid.UUID, flashcards: Flashcards, topic_id: uuid.UUID | None = None
) -> list[FlashcardOut]:
    return [FlashcardOut.model_validate(c) for c in await flashcards.list(module_id, topic_id)]


@router.post("/flashcards", response_model=FlashcardOut, status_code=status.HTTP_201_CREATED)
async def create_flashcard(body: FlashcardCreate, flashcards: Flashcards) -> FlashcardOut:
    return FlashcardOut.model_validate(await flashcards.create(body))


@router.patch("/flashcards/{card_id}", response_model=FlashcardOut)
async def update_flashcard(
    card_id: uuid.UUID, body: FlashcardUpdate, flashcards: Flashcards
) -> FlashcardOut:
    return FlashcardOut.model_validate(await flashcards.update(card_id, body))


@router.delete("/flashcards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flashcard(card_id: uuid.UUID, flashcards: Flashcards) -> None:
    await flashcards.delete(card_id)


@router.post("/flashcards/{card_id}/restore", response_model=FlashcardOut)
async def restore_flashcard(
    card_id: uuid.UUID, flashcards: Flashcards, config: Config
) -> FlashcardOut:
    retention = timedelta(days=config.platform.trash.retention_days)
    return FlashcardOut.model_validate(await flashcards.restore(card_id, retention))


# --- quizzes and attempts ----------------------------------------------------------------------


@router.post("/quizzes", response_model=AttemptStarted, status_code=status.HTTP_201_CREATED)
async def create_quiz(body: QuizCreate, quizzes: Quizzes) -> AttemptStarted:
    """Build a practice quiz or mock exam from the bank and start it."""
    quiz, attempt = await quizzes.create(body)
    return AttemptStarted(quiz=QuizOut.model_validate(quiz), attempt_id=attempt.id)


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptStarted,
    status_code=status.HTTP_201_CREATED,
)
async def retake_quiz(quiz_id: uuid.UUID, quizzes: Quizzes) -> AttemptStarted:
    attempt = await quizzes.start(quiz_id)
    view = await quizzes.view(attempt.id)
    return AttemptStarted(quiz=view.quiz, attempt_id=attempt.id)


@router.get("/attempts", response_model=list[AttemptListItem])
async def list_attempts(
    quizzes: Quizzes, module_id: uuid.UUID | None = None
) -> list[AttemptListItem]:
    """Your quizzes and mock exams in a module, newest first (all of them,
    including daily quizzes, without a module)."""
    return await quizzes.history(module_id)


@router.get("/attempts/active-exam", response_model=ActiveExam | None)
async def get_active_exam(quizzes: Quizzes) -> ActiveExam | None:
    """The mock exam you have open (with its deadline), or null. The app
    shows its timer on every page while one is open."""
    return await quizzes.active_exam()


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
async def get_attempt(attempt_id: uuid.UUID, quizzes: Quizzes) -> AttemptOut:
    """The quiz as you answer it (no answers shown), or your results once
    submitted. An exam past its deadline is submitted automatically."""
    return await quizzes.view(attempt_id)


@router.put(
    "/attempts/{attempt_id}/responses/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def save_response(
    attempt_id: uuid.UUID, question_id: uuid.UUID, body: ResponseSave, quizzes: Quizzes
) -> None:
    await quizzes.save_response(attempt_id, question_id, body)


@router.post(
    "/attempts/{attempt_id}/responses/{question_id}/photo",
    response_model=PhotoTranscription,
    dependencies=[rate_limited("ai")],
)
async def upload_photo(
    attempt_id: uuid.UUID,
    question_id: uuid.UUID,
    request: Request,
    quizzes: Quizzes,
    config: Config,
    filename: Annotated[str, Query(min_length=1, max_length=200)],
) -> PhotoTranscription:
    """A photo of your handwritten working (raw request body). Returns
    Claude's transcription for you to check and edit into your answer."""
    ext = Path(filename).suffix.lower().lstrip(".")
    limit = config.platform.uploads.max_megabytes.image * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="revision-os-photo-") as tmp:
        path = Path(tmp) / "photo"
        await receive_to_file(request, limit, path)
        result = await quizzes.photo(attempt_id, question_id, path, ext)
    return PhotoTranscription(
        markdown=result.markdown, confidence=result.confidence, notes=result.notes
    )


@router.post(
    "/attempts/{attempt_id}/submit", response_model=AttemptOut, dependencies=[rate_limited("ai")]
)
async def submit_attempt(attempt_id: uuid.UUID, quizzes: Quizzes) -> AttemptOut:
    """Submit the whole quiz. Exact marks appear at once; Claude's marks and
    explanations follow (status "marking", then "marked")."""
    await quizzes.submit(attempt_id)
    return await quizzes.view(attempt_id)


@router.post(
    "/answers/{answer_id}/dispute", response_model=AttemptOut, dependencies=[rate_limited("ai")]
)
async def dispute_mark(answer_id: uuid.UUID, quizzes: Quizzes) -> AttemptOut:
    """Re-mark a Claude-marked answer with the stronger model."""
    answer = await quizzes.dispute(answer_id)
    return await quizzes.view(answer.quiz_attempt_id)


@router.post("/answers/{answer_id}/override", response_model=AttemptOut)
async def override_mark(answer_id: uuid.UUID, body: ScoreOverride, quizzes: Quizzes) -> AttemptOut:
    """Set the mark yourself (the original is kept for the record)."""
    answer = await quizzes.override(answer_id, body.score)
    return await quizzes.view(answer.quiz_attempt_id)
