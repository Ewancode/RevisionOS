"""Coding practice: exercises whose code and tests run in your browser, the
submissions it reports, and the tutor's hint ladder (also for quiz answers)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.schemas.coding import (
    CodingConfigOut,
    ExerciseIn,
    ExerciseOut,
    ExerciseSummary,
    ExerciseUpdate,
    HintRequest,
    HintsOut,
    SubmissionIn,
    SubmissionOut,
)
from app.services.coding import CodingService

router = APIRouter(tags=["coding"])


def _coding(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> CodingService:
    return CodingService(
        db,
        user.id,
        client,
        config=config,
        jobs=request.app.state.jobs,
        claude=request.app.state.claude,
    )


Coding = Annotated[CodingService, Depends(_coding)]


@router.get("/coding/config", response_model=CodingConfigOut)
async def coding_config(coding: Coding) -> CodingConfigOut:
    """The pinned Python and R runtimes your browser loads, and run limits."""
    return coding.runtime_config()


@router.get("/coding/exercises", response_model=list[ExerciseSummary])
async def list_exercises(module_id: uuid.UUID, coding: Coding) -> list[ExerciseSummary]:
    return await coding.exercises(module_id)


@router.post("/coding/exercises", response_model=ExerciseOut, status_code=status.HTTP_201_CREATED)
async def create_exercise(body: ExerciseIn, coding: Coding) -> ExerciseOut:
    """An exercise you write yourself (Claude's come through drafts)."""
    return await coding.out(await coding.create(body))


@router.get("/coding/exercises/{exercise_id}", response_model=ExerciseOut)
async def get_exercise(exercise_id: uuid.UUID, coding: Coding) -> ExerciseOut:
    return await coding.out(await coding.get(exercise_id))


@router.patch("/coding/exercises/{exercise_id}", response_model=ExerciseOut)
async def update_exercise(
    exercise_id: uuid.UUID, body: ExerciseUpdate, coding: Coding
) -> ExerciseOut:
    return await coding.out(await coding.update(exercise_id, body))


@router.delete("/coding/exercises/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exercise(exercise_id: uuid.UUID, coding: Coding) -> None:
    await coding.delete(exercise_id)


@router.post("/coding/exercises/{exercise_id}/restore", response_model=ExerciseOut)
async def restore_exercise(exercise_id: uuid.UUID, coding: Coding) -> ExerciseOut:
    return await coding.out(await coding.restore(exercise_id))


@router.post(
    "/coding/exercises/{exercise_id}/submissions",
    response_model=SubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_code(exercise_id: uuid.UUID, body: SubmissionIn, coding: Coding) -> SubmissionOut:
    """Record a submission: your code and the test results your browser got."""
    return SubmissionOut.model_validate(await coding.submit(exercise_id, body))


@router.get("/coding/exercises/{exercise_id}/submissions", response_model=list[SubmissionOut])
async def list_submissions(exercise_id: uuid.UUID, coding: Coding) -> list[SubmissionOut]:
    return [SubmissionOut.model_validate(s) for s in await coding.submissions(exercise_id)]


@router.get("/coding/exercises/{exercise_id}/hints", response_model=HintsOut)
async def exercise_hints(exercise_id: uuid.UUID, coding: Coding) -> HintsOut:
    return await coding.exercise_hints(exercise_id)


@router.post(
    "/coding/exercises/{exercise_id}/hints",
    response_model=HintsOut,
    dependencies=[rate_limited("ai")],
)
async def next_exercise_hint(exercise_id: uuid.UUID, body: HintRequest, coding: Coding) -> HintsOut:
    """The next rung of the hint ladder. Off while a mock exam is open."""
    return await coding.exercise_hint(exercise_id, body)


@router.get("/attempts/{attempt_id}/responses/{question_id}/hints", response_model=HintsOut)
async def question_hints(attempt_id: uuid.UUID, question_id: uuid.UUID, coding: Coding) -> HintsOut:
    return await coding.question_hints(attempt_id, question_id)


@router.post(
    "/attempts/{attempt_id}/responses/{question_id}/hints",
    response_model=HintsOut,
    dependencies=[rate_limited("ai")],
)
async def next_question_hint(
    attempt_id: uuid.UUID, question_id: uuid.UUID, body: HintRequest, coding: Coding
) -> HintsOut:
    """The next hint for a question you are answering (practice quizzes only)."""
    return await coding.question_hint(attempt_id, question_id, body)
