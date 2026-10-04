"""Coding practice for one user (SPEC 37, 38, 69): exercises, submissions
whose tests ran in the browser, and the tutor's hint ladder for exercises and
for answers in a practice quiz."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.coding import tutor
from app.coding.validation import check_exercise
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import (
    CodingExercise,
    CodingSubmission,
    Question,
    QuestionAttempt,
    QuizAttempt,
    TutorHint,
)
from app.schemas.coding import (
    CodingConfigOut,
    ExerciseIn,
    ExerciseOut,
    ExerciseSummary,
    ExerciseUpdate,
    HintOut,
    HintRequest,
    HintsOut,
    Progress,
    RuntimeOut,
    SubmissionIn,
    TestOut,
)
from app.services.common import ClientInfo, ScopedService, not_found
from app.services.quizzes import ensure_no_exam
from app.workers.queue import JobQueue


def _invalid(problems: Sequence[str]) -> AppError:
    return AppError("invalid_exercise", " ".join(problems), 422)


class CodingService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        config: AppConfig,
        jobs: JobQueue,
        claude: ClaudeClient | None = None,
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config
        self.jobs = jobs
        self.claude = claude

    def runtime_config(self) -> CodingConfigOut:
        coding = self.config.coding
        return CodingConfigOut(
            runtimes={
                "python": RuntimeOut.model_validate(coding.runtimes.python),
                "r": RuntimeOut.model_validate(coding.runtimes.r),
            },
            run_timeout_seconds=coding.limits.run_timeout_seconds,
            first_run_timeout_seconds=coding.limits.first_run_timeout_seconds,
            max_output_chars=coding.limits.max_output_chars,
        )

    # --- exercises ------------------------------------------------------------------------

    async def get(self, exercise_id: uuid.UUID, *, deleted: bool = False) -> CodingExercise:
        exercise = await self.db.scalar(
            select(CodingExercise).where(
                CodingExercise.id == exercise_id,
                CodingExercise.user_id == self.user_id,
                CodingExercise.deleted_at.is_not(None)
                if deleted
                else CodingExercise.deleted_at.is_(None),
            )
        )
        if exercise is None:
            raise not_found("exercise")
        return exercise

    async def _progress(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int | None]]:
        rows = await self.db.execute(
            select(
                CodingSubmission.exercise_id,
                func.count(),
                func.max(CodingSubmission.passed),
            )
            .where(CodingSubmission.user_id == self.user_id, CodingSubmission.exercise_id.in_(ids))
            .group_by(CodingSubmission.exercise_id)
        )
        return {exercise: (n, best) for exercise, n, best in rows.all()}

    @staticmethod
    def _summary(e: CodingExercise, progress: tuple[int, int | None]) -> dict[str, Any]:
        submissions, best = progress
        total = len(e.tests)
        return {
            "id": e.id,
            "module_id": e.module_id,
            "topic_id": e.topic_id,
            "language": e.language,
            "title": e.title,
            "difficulty": e.difficulty,
            "origin": e.origin,
            "assessed": e.assessed,
            "progress": Progress(
                submissions=submissions,
                best_passed=best,
                total=total,
                solved=best is not None and best == total,
            ),
            "created_at": e.created_at,
        }

    async def exercises(self, module_id: uuid.UUID) -> list[ExerciseSummary]:
        await self.placement(module_id, None)
        rows = (
            await self.db.scalars(
                select(CodingExercise)
                .where(
                    CodingExercise.user_id == self.user_id,
                    CodingExercise.module_id == module_id,
                    CodingExercise.deleted_at.is_(None),
                )
                .order_by(CodingExercise.created_at.desc())
            )
        ).all()
        progress = await self._progress([e.id for e in rows])
        return [
            ExerciseSummary.model_validate(self._summary(e, progress.get(e.id, (0, None))))
            for e in rows
        ]

    async def out(self, exercise: CodingExercise) -> ExerciseOut:
        progress = await self._progress([exercise.id])
        latest = await self.db.scalar(
            select(CodingSubmission.code)
            .where(CodingSubmission.exercise_id == exercise.id)
            .order_by(CodingSubmission.created_at.desc())
            .limit(1)
        )
        return ExerciseOut.model_validate(
            {
                **self._summary(exercise, progress.get(exercise.id, (0, None))),
                "prompt_md": exercise.prompt_md,
                "starter_code": exercise.starter_code,
                "tests": [TestOut.model_validate(t) for t in exercise.tests],
                "packages": exercise.packages,
                "sources": exercise.sources,
                "latest_code": latest,
            }
        )

    def _check(self, fields: dict[str, Any]) -> None:
        checked = check_exercise(fields, 0, self.config.coding.limits)
        if not checked.valid:
            raise _invalid(checked.problems)

    async def create(
        self,
        body: ExerciseIn,
        *,
        origin: str = "user",
        sources: list[dict[str, Any]] | None = None,
        commit: bool = True,
    ) -> CodingExercise:
        """`commit=False` when saving a draft, which commits everything at once."""
        await self.placement(body.module_id, body.topic_id)
        fields = body.model_dump(mode="json")
        self._check(fields)
        exercise = CodingExercise(
            id=uuid.uuid4(),
            user_id=self.user_id,
            module_id=body.module_id,
            topic_id=body.topic_id,
            language=body.language,
            title=body.title,
            prompt_md=body.prompt_md,
            starter_code=body.starter_code,
            solution_code=body.solution_code,
            tests=fields["tests"],
            packages=body.packages,
            difficulty=body.difficulty,
            assessed=body.assessed,
            origin=origin,
            sources=sources or [],
        )
        self.db.add(exercise)
        if commit:
            await self.db.commit()
            await self.db.refresh(exercise)
        else:
            await self.db.flush()
        return exercise

    async def update(self, exercise_id: uuid.UUID, body: ExerciseUpdate) -> CodingExercise:
        exercise = await self.get(exercise_id)
        changes = body.model_dump(mode="json", exclude_unset=True)
        if "topic_id" in changes:
            await self.placement(exercise.module_id, body.topic_id)
        merged = {
            "language": exercise.language,
            "title": exercise.title,
            "prompt_md": exercise.prompt_md,
            "starter_code": exercise.starter_code,
            "solution_code": exercise.solution_code,
            "tests": exercise.tests,
            "packages": exercise.packages,
            "difficulty": exercise.difficulty,
            **changes,
        }
        self._check(merged)
        for key, value in changes.items():
            setattr(exercise, key, uuid.UUID(value) if key == "topic_id" and value else value)
        await self.db.commit()
        await self.db.refresh(exercise)
        return exercise

    async def delete(self, exercise_id: uuid.UUID) -> None:
        exercise = await self.get(exercise_id)
        exercise.deleted_at = utcnow()
        self._record("delete", "coding_exercise", exercise.id, title=exercise.title)
        await self.db.commit()

    async def restore(self, exercise_id: uuid.UUID) -> CodingExercise:
        exercise = await self.get(exercise_id, deleted=True)
        exercise.deleted_at = None
        self._record("restore", "coding_exercise", exercise.id)
        await self.db.commit()
        await self.db.refresh(exercise)
        return exercise

    # --- submissions --------------------------------------------------------------------------

    async def submit(self, exercise_id: uuid.UUID, body: SubmissionIn) -> CodingSubmission:
        """Store what your browser ran. The results must name the exercise's
        tests, in order, so a submission cannot claim to pass tests that
        do not exist."""
        exercise = await self.get(exercise_id)
        expected = [t["name"] for t in exercise.tests]
        if [r.name for r in body.results] != expected:
            raise AppError(
                "results_mismatch",
                "The results do not match this exercise's tests. Run the tests again.",
                422,
            )
        submission = CodingSubmission(
            id=uuid.uuid4(),
            user_id=self.user_id,
            exercise_id=exercise.id,
            code=body.code,
            results=[r.model_dump() for r in body.results],
            passed=sum(1 for r in body.results if r.passed),
            total=len(expected),
            error=body.error,
            runtime_ms=body.runtime_ms,
        )
        self.db.add(submission)
        await self.db.commit()
        await self.db.refresh(submission)
        return submission

    async def submissions(self, exercise_id: uuid.UUID) -> Sequence[CodingSubmission]:
        exercise = await self.get(exercise_id)
        return (
            await self.db.scalars(
                select(CodingSubmission)
                .where(CodingSubmission.exercise_id == exercise.id)
                .order_by(CodingSubmission.created_at.desc())
                .limit(20)
            )
        ).all()

    # --- the hint ladder ------------------------------------------------------------------------

    @staticmethod
    def _hints_out(rows: Sequence[TutorHint], state: tutor.Ladder) -> HintsOut:
        return HintsOut(
            hints=[
                HintOut(
                    level=h.level,
                    label=tutor.LEVELS[h.level],
                    content_md=h.content_md,
                    created_at=h.created_at,
                )
                for h in rows
            ],
            next_level=state.next_level,
            next_label=tutor.LEVELS[state.next_level] if state.next_level else None,
            top=state.top,
            locked_reason=state.locked_reason,
        )

    async def _given(self, **target: uuid.UUID) -> list[TutorHint]:
        column, value = next(iter(target.items()))
        return list(
            (
                await self.db.scalars(
                    select(TutorHint)
                    .where(TutorHint.user_id == self.user_id, getattr(TutorHint, column) == value)
                    .order_by(TutorHint.level)
                )
            ).all()
        )

    async def _exercise_state(
        self, exercise: CodingExercise
    ) -> tuple[list[TutorHint], tutor.Ladder]:
        given = await self._given(exercise_id=exercise.id)
        submitted = bool(
            await self.db.scalar(
                select(func.count())
                .select_from(CodingSubmission)
                .where(CodingSubmission.exercise_id == exercise.id)
            )
        )
        state = tutor.ladder(
            [h.level for h in given], kind="coding", submitted=submitted, assessed=exercise.assessed
        )
        return given, state

    async def exercise_hints(self, exercise_id: uuid.UUID) -> HintsOut:
        exercise = await self.get(exercise_id)
        return self._hints_out(*await self._exercise_state(exercise))

    def _require_claude(self) -> ClaudeClient:
        if self.claude is None:
            raise AppError("ai_not_configured", "Claude is not configured.", 503)
        return self.claude

    async def _save_hint(self, hint: TutorHint) -> None:
        self.db.add(hint)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            # Two clicks at once: the other request already gave this rung.
            await self.db.rollback()
            raise AppError(
                "hint_taken", "That hint was just given. Reload to see it.", 409
            ) from exc

    async def exercise_hint(self, exercise_id: uuid.UUID, body: HintRequest) -> HintsOut:
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        exercise = await self.get(exercise_id)
        given, state = await self._exercise_state(exercise)
        level = state.next_level
        if level is None:
            raise AppError("no_more_hints", state.locked_reason or "You have had every hint.", 409)
        if level > tutor.LAST_AI_LEVEL:
            content, interaction = (
                tutor.solution_text(exercise.language, exercise.solution_code),
                None,
            )
        else:
            problem = tutor.Problem(
                kind="coding",
                title=exercise.title,
                text_md=exercise.prompt_md,
                work=body.work,
                language=exercise.language,
                visible_tests=[t["code"] for t in exercise.tests if not t.get("hidden")],
                results=body.results,
            )
            content, interaction = await tutor.ask(
                self.db,
                self._require_claude(),
                self.config,
                user_id=self.user_id,
                module_id=exercise.module_id,
                problem=problem,
                level=level,
                previous=[(h.level, h.content_md) for h in given],
            )
        await self._save_hint(
            TutorHint(
                user_id=self.user_id,
                exercise_id=exercise.id,
                level=level,
                content_md=content,
                ai_interaction_id=interaction,
            )
        )
        return await self.exercise_hints(exercise.id)

    async def _answer(
        self, attempt_id: uuid.UUID, question_id: uuid.UUID
    ) -> tuple[QuizAttempt, QuestionAttempt, Question]:
        row = (
            await self.db.execute(
                select(QuizAttempt, QuestionAttempt, Question)
                .join(QuestionAttempt, QuestionAttempt.quiz_attempt_id == QuizAttempt.id)
                .join(Question, Question.id == QuestionAttempt.question_id)
                .where(
                    QuizAttempt.id == attempt_id,
                    QuizAttempt.user_id == self.user_id,
                    QuestionAttempt.question_id == question_id,
                )
            )
        ).first()
        if row is None:
            raise not_found("attempt")
        attempt, answer, question = row
        return attempt, answer, question

    async def question_hints(self, attempt_id: uuid.UUID, question_id: uuid.UUID) -> HintsOut:
        _, answer, _ = await self._answer(attempt_id, question_id)
        given = await self._given(question_attempt_id=answer.id)
        return self._hints_out(given, tutor.ladder([h.level for h in given], kind="question"))

    async def question_hint(
        self, attempt_id: uuid.UUID, question_id: uuid.UUID, body: HintRequest
    ) -> HintsOut:
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        attempt, answer, question = await self._answer(attempt_id, question_id)
        if attempt.status != "in_progress":
            raise AppError(
                "attempt_submitted",
                "Hints are for while you work. The worked solution is in your results.",
                409,
            )
        given = await self._given(question_attempt_id=answer.id)
        state = tutor.ladder([h.level for h in given], kind="question")
        if state.next_level is None:
            raise AppError("no_more_hints", state.locked_reason or "You have had every hint.", 409)
        options = (
            question.answer_spec.get("options") if question.type == "multiple_choice" else None
        )
        text = question.stem_md + (
            "\n\nOptions:\n" + "\n".join(f"- {o}" for o in options) if options else ""
        )
        content, interaction = await tutor.ask(
            self.db,
            self._require_claude(),
            self.config,
            user_id=self.user_id,
            module_id=question.module_id,
            problem=tutor.Problem(kind="question", title="Question", text_md=text, work=body.work),
            level=state.next_level,
            previous=[(h.level, h.content_md) for h in given],
        )
        await self.db.execute(
            update(QuestionAttempt)
            .where(QuestionAttempt.id == answer.id)
            .values(hints_used=QuestionAttempt.hints_used + 1)
        )
        await self._save_hint(
            TutorHint(
                user_id=self.user_id,
                question_attempt_id=answer.id,
                level=state.next_level,
                content_md=content,
                ai_interaction_id=interaction,
            )
        )
        return await self.question_hints(attempt_id, question_id)
