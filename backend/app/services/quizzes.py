"""Quizzes, mock exams and attempts (SPEC 25-26 and 36; ARCHITECTURE.md
sections 9-10).

You answer every question, then submit the whole quiz before seeing any
result. Rule-markable answers are marked on submission; the rest, and the
explanations of wrong answers, follow from the worker.

A mock exam runs in exam mode: it has a deadline the server enforces (late
answers are refused and the attempt is submitted automatically), and while it
is open the server refuses AI help (the assistant and generation). Hiding
buttons is not the safeguard; the server is.
"""

import random
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.ai.transcription import Transcription, prepare_image, transcribe_page
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.ingestion.validation import IMAGE_KINDS, validate_upload
from app.models import Question, QuestionAttempt, Quiz, QuizAttempt, QuizItem, Topic
from app.practice import marking
from app.practice.answers import (
    correct_answer_text,
    load_response,
    load_spec,
    mark_by_rule,
    public_view,
)
from app.schemas.practice import (
    AttemptItem,
    AttemptListItem,
    AttemptOut,
    AttemptSummary,
    Breakdown,
    QuizCreate,
    QuizOut,
    ResponseSave,
)
from app.services.bank import BankFilters, QuestionService
from app.services.common import ClientInfo, ScopedService, not_found
from app.storage.base import StorageBackend, answer_image_key
from app.workers.queue import JobQueue

PHOTO_TYPES = frozenset({"numerical", "expression", "short_answer", "explanation", "derivation"})


# --- exam mode ---------------------------------------------------------------------------


async def active_exam(db: AsyncSession, user_id: uuid.UUID) -> QuizAttempt | None:
    return await db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user_id,
            QuizAttempt.mode == "exam",
            QuizAttempt.status == "in_progress",
        )
    )


def _expired(attempt: QuizAttempt, config: AppConfig) -> bool:
    if attempt.deadline is None:
        return False
    grace = timedelta(seconds=config.practice.quizzes.exam_grace_seconds)
    return utcnow() > attempt.deadline + grace


async def ensure_no_exam(
    db: AsyncSession, user_id: uuid.UUID, config: AppConfig, jobs: JobQueue
) -> None:
    """Refuse AI help while an exam is open (a timed-out one is submitted)."""
    attempt = await active_exam(db, user_id)
    if attempt is None:
        return
    if _expired(attempt, config):
        await submit_attempt(db, config, jobs, attempt)
        return
    raise AppError(
        "exam_in_progress", "AI help is off while a mock exam is open. Submit it first.", 423
    )


async def submit_attempt(
    db: AsyncSession, config: AppConfig, jobs: JobQueue, attempt: QuizAttempt
) -> None:
    """Mark what the rules can now; queue Claude for the rest."""
    answers = (
        await db.scalars(
            select(QuestionAttempt).where(QuestionAttempt.quiz_attempt_id == attempt.id)
        )
    ).all()
    questions = {
        q.id: q
        for q in await db.scalars(
            select(Question).where(Question.id.in_([a.question_id for a in answers]))
        )
    }
    now = utcnow()
    needs_claude = False
    for answer in answers:
        mark = mark_by_rule(
            load_spec(questions[answer.question_id].answer_spec),
            answer.response,
            config.practice.marking,
        )
        if mark.needs_ai:
            needs_claude = True
            continue
        answer.score, answer.marked_by, answer.marked_at = mark.score, mark.marked_by, now
        answer.feedback = {"summary": mark.feedback} if mark.feedback else None
        if mark.score < config.practice.marking.correct_at and answer.response is not None:
            needs_claude = True  # to explain the mistake
    attempt.submitted_at, attempt.status = now, "marking"
    if not needs_claude:
        marking.finish(attempt, list(answers))
    await db.commit()
    if needs_claude:
        await jobs.enqueue("mark_attempt", str(attempt.id), job_id=f"mark:{attempt.id}")


# --- the service -------------------------------------------------------------------------


def _interleave(questions: Sequence[Question], rng: random.Random) -> list[Question]:
    """Shuffle, then alternate between topics so one topic is not bunched."""
    by_topic: dict[uuid.UUID | None, list[Question]] = defaultdict(list)
    for question in rng.sample(list(questions), len(questions)):
        by_topic[question.topic_id].append(question)
    groups = list(by_topic.values())
    ordered: list[Question] = []
    while any(groups):
        for group in groups:
            if group:
                ordered.append(group.pop())
    return ordered


class QuizService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        config: AppConfig,
        jobs: JobQueue,
        storage: StorageBackend | None = None,
        claude: ClaudeClient | None = None,
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config
        self.jobs = jobs
        self.storage = storage
        self.claude = claude
        self.rng = random.Random()  # noqa: S311 - question order, not security

    # --- building and starting ----------------------------------------------------------

    async def _choose(self, body: QuizCreate) -> list[Question]:
        limits = self.config.practice.quizzes
        if body.question_ids:
            rows = (
                await self.db.scalars(
                    select(Question).where(
                        Question.id.in_(body.question_ids),
                        Question.user_id == self.user_id,
                        Question.module_id == body.module_id,
                        Question.status == "active",
                    )
                )
            ).all()
            by_id = {q.id: q for q in rows}
            if len(by_id) != len(set(body.question_ids)):
                raise not_found("question")
            return [by_id[i] for i in dict.fromkeys(body.question_ids)][: limits.max_questions]
        bank = await QuestionService(self.db, self.user_id, self.client, config=self.config).bank(
            body.module_id,
            BankFilters(
                topic_ids=body.topic_ids,
                difficulties=body.difficulties,
                types=body.types,
                result=body.result,
            ),
        )
        ids = [q.id for q in bank]
        if not ids:
            return []
        pool = (await self.db.scalars(select(Question).where(Question.id.in_(ids)))).all()
        count = min(body.count or limits.default_questions, limits.max_questions)
        chosen = self.rng.sample(list(pool), min(count, len(pool)))
        return _interleave(chosen, self.rng)

    async def create(self, body: QuizCreate) -> tuple[Quiz, QuizAttempt]:
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        module = await self.placement(body.module_id, None)
        limits = self.config.practice.quizzes
        if body.count is not None and body.count > limits.max_questions:
            raise AppError(
                "too_many_questions", f"Quizzes hold at most {limits.max_questions}.", 422
            )
        minutes = None
        if body.kind == "mock":
            minutes = body.time_limit_minutes or limits.mock_default_minutes
            if minutes > limits.max_minutes:
                raise AppError("too_long", f"Exams last at most {limits.max_minutes} minutes.", 422)
        questions = await self._choose(body)
        if not questions:
            raise AppError(
                "no_questions", "No questions match. Generate some, or loosen the filters.", 422
            )
        default_title = "Mock exam" if body.kind == "mock" else "Practice quiz"
        quiz = Quiz(
            id=uuid.uuid4(),
            user_id=self.user_id,
            module_id=module.id,
            kind=body.kind,
            title=body.title or f"{module.code} {default_title.lower()}",
            time_limit_minutes=minutes,
            config=body.model_dump(mode="json", exclude={"module_id", "title", "kind"}),
        )
        self.db.add(quiz)
        await self.db.flush()
        for position, question in enumerate(questions):
            self.db.add(
                QuizItem(
                    quiz_id=quiz.id,
                    position=position,
                    user_id=self.user_id,
                    question_id=question.id,
                )
            )
        await self.db.flush()
        attempt = await self._start(quiz)
        return quiz, attempt

    async def _quiz(self, quiz_id: uuid.UUID) -> Quiz:
        quiz = await self.db.scalar(
            select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == self.user_id)
        )
        if quiz is None:
            raise not_found("quiz")
        return quiz

    async def start(self, quiz_id: uuid.UUID) -> QuizAttempt:
        """Take a quiz again."""
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        return await self._start(await self._quiz(quiz_id))

    async def _start(self, quiz: Quiz) -> QuizAttempt:
        now = utcnow()
        exam = quiz.kind == "mock"
        attempt = QuizAttempt(
            id=uuid.uuid4(),
            user_id=self.user_id,
            quiz_id=quiz.id,
            mode="exam" if exam else "normal",
            status="in_progress",
            started_at=now,
            deadline=now + timedelta(minutes=quiz.time_limit_minutes)
            if exam and quiz.time_limit_minutes
            else None,
        )
        self.db.add(attempt)
        await self.db.flush()
        items = (
            await self.db.scalars(
                select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.position)
            )
        ).all()
        for item in items:
            self.db.add(
                QuestionAttempt(
                    id=uuid.uuid4(),
                    user_id=self.user_id,
                    quiz_attempt_id=attempt.id,
                    question_id=item.question_id,
                )
            )
        await self.db.commit()
        return attempt

    async def history(self, module_id: uuid.UUID) -> list[AttemptListItem]:
        await self.placement(module_id, None)
        count = (
            select(func.count())
            .where(QuizItem.quiz_id == Quiz.id)
            .correlate(Quiz)
            .scalar_subquery()
        )
        rows = (
            await self.db.execute(
                select(QuizAttempt, Quiz, count)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(QuizAttempt.user_id == self.user_id, Quiz.module_id == module_id)
                .order_by(QuizAttempt.started_at.desc())
            )
        ).all()
        return [
            AttemptListItem(
                id=attempt.id,
                quiz_id=quiz.id,
                title=quiz.title,
                kind=quiz.kind,
                mode=attempt.mode,
                status=attempt.status,
                started_at=attempt.started_at,
                submitted_at=attempt.submitted_at,
                score=attempt.score,
                questions=questions,
            )
            for attempt, quiz, questions in rows
        ]

    # --- answering ------------------------------------------------------------------------

    async def attempt(self, attempt_id: uuid.UUID) -> QuizAttempt:
        attempt = await self.db.scalar(
            select(QuizAttempt).where(
                QuizAttempt.id == attempt_id, QuizAttempt.user_id == self.user_id
            )
        )
        if attempt is None:
            raise not_found("attempt")
        if attempt.status == "in_progress" and _expired(attempt, self.config):
            await submit_attempt(self.db, self.config, self.jobs, attempt)
        return attempt

    async def _answer(
        self, attempt: QuizAttempt, question_id: uuid.UUID
    ) -> tuple[QuestionAttempt, Question]:
        if attempt.status != "in_progress":
            raise AppError("attempt_closed", "This quiz has been submitted.", 409)
        row = (
            await self.db.execute(
                select(QuestionAttempt, Question)
                .join(Question, Question.id == QuestionAttempt.question_id)
                .where(
                    QuestionAttempt.quiz_attempt_id == attempt.id,
                    QuestionAttempt.question_id == question_id,
                )
            )
        ).first()
        if row is None:
            raise not_found("question")
        return row[0], row[1]

    async def save_response(
        self, attempt_id: uuid.UUID, question_id: uuid.UUID, body: ResponseSave
    ) -> None:
        attempt = await self.attempt(attempt_id)
        if attempt.status != "in_progress":
            raise AppError("time_up", "Time is up: this exam has been submitted.", 409)
        answer, question = await self._answer(attempt, question_id)
        if body.response is None:
            answer.response = None
        else:
            try:
                answer.response = load_response(question.type, body.response).model_dump(
                    mode="json"
                )
            except ValidationError as exc:
                raise AppError(
                    "bad_response", "That answer is not in the expected form.", 422
                ) from exc
        if body.time_ms is not None:
            answer.time_ms = body.time_ms
        if body.self_confidence is not None:
            answer.self_confidence = body.self_confidence
        await self.db.commit()

    async def photo(
        self, attempt_id: uuid.UUID, question_id: uuid.UUID, path: Path, ext: str
    ) -> Transcription:
        """Store a photo of your working and transcribe it for you to check.
        Transcription is marking input, not help, so it works in exams too."""
        if self.storage is None or self.claude is None:
            raise RuntimeError("photo needs storage and Claude")
        attempt = await self.attempt(attempt_id)
        answer, question = await self._answer(attempt, question_id)
        if question.type not in PHOTO_TYPES:
            raise AppError("no_photo", "This question takes a choice, not working.", 422)
        checked = validate_upload(path, ext, self.config.platform.uploads)
        if checked.kind not in IMAGE_KINDS:
            raise AppError("not_an_image", "Upload a photo (JPEG, PNG, HEIC or WebP).", 422)
        data = checked.path.read_bytes()
        key = answer_image_key(self.user_id, attempt.id, question.id, checked.kind.value)
        await self.storage.put_bytes(key, data)
        answer.response_image_key = key
        await self.db.commit()
        image = prepare_image(data, self.config.platform.ingestion.vision_max_long_edge_px)
        return await transcribe_page(
            self.claude,
            self.db,
            user_id=self.user_id,
            document_id=None,
            module_id=question.module_id,
            image=image,
            page_no=1,
            filename="the student's handwritten working",
        )

    async def submit(self, attempt_id: uuid.UUID) -> QuizAttempt:
        attempt = await self.attempt(attempt_id)
        if attempt.status != "in_progress":
            raise AppError("attempt_closed", "This quiz has already been submitted.", 409)
        await submit_attempt(self.db, self.config, self.jobs, attempt)
        return attempt

    # --- after marking -----------------------------------------------------------------------

    async def _marked_answer(
        self, answer_id: uuid.UUID
    ) -> tuple[QuestionAttempt, Question, QuizAttempt]:
        row = (
            await self.db.execute(
                select(QuestionAttempt, Question, QuizAttempt)
                .join(Question, Question.id == QuestionAttempt.question_id)
                .join(QuizAttempt, QuizAttempt.id == QuestionAttempt.quiz_attempt_id)
                .where(QuestionAttempt.id == answer_id, QuestionAttempt.user_id == self.user_id)
            )
        ).first()
        if row is None:
            raise not_found("answer")
        answer, question, attempt = row
        if attempt.status != "marked":
            raise AppError("not_marked", "Wait until the quiz has been marked.", 409)
        return answer, question, attempt

    async def _rescore(self, attempt: QuizAttempt) -> None:
        scores = (
            await self.db.scalars(
                select(QuestionAttempt.score).where(
                    QuestionAttempt.quiz_attempt_id == attempt.id,
                    QuestionAttempt.score.is_not(None),
                )
            )
        ).all()
        values = [s for s in scores if s is not None]
        attempt.score = sum(values) / len(values) if values else None

    async def dispute(self, answer_id: uuid.UUID) -> QuestionAttempt:
        """Re-mark a Claude-marked answer on the stronger model."""
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        if self.claude is None:
            raise RuntimeError("dispute needs Claude")
        answer, question, attempt = await self._marked_answer(answer_id)
        if answer.marked_by in ("rule", "sympy"):
            raise AppError(
                "rule_marked",
                "This answer was marked exactly, not by Claude. You can override the mark.",
                409,
            )
        before = answer.score
        await marking.mark_one(self.db, self.claude, self.config, answer, question, escalate=True)
        if answer.original_score is None:
            answer.original_score = before
        await self._rescore(attempt)
        await self.db.commit()
        return answer

    async def override(self, answer_id: uuid.UUID, score: float) -> QuestionAttempt:
        answer, _, attempt = await self._marked_answer(answer_id)
        if answer.original_score is None:
            answer.original_score = answer.score
        answer.score, answer.marked_by, answer.marking_confidence = score, "override", None
        answer.marked_at = utcnow()
        await self._rescore(attempt)
        await self.db.commit()
        return answer

    # --- the view ------------------------------------------------------------------------------

    async def view(self, attempt_id: uuid.UUID) -> AttemptOut:
        attempt = await self.attempt(attempt_id)
        quiz = await self._quiz(attempt.quiz_id)
        rows = (
            await self.db.execute(
                select(QuizItem.position, QuestionAttempt, Question)
                .join(QuestionAttempt, QuestionAttempt.question_id == QuizItem.question_id)
                .join(Question, Question.id == QuizItem.question_id)
                .where(QuizItem.quiz_id == quiz.id, QuestionAttempt.quiz_attempt_id == attempt.id)
                .order_by(QuizItem.position)
            )
        ).all()
        done = attempt.status != "in_progress"
        items = []
        for position, answer, question in rows:
            spec = load_spec(question.answer_spec)
            item: dict[str, Any] = {
                "position": position,
                "question_id": question.id,
                "type": question.type,
                "difficulty": question.difficulty,
                "topic_id": question.topic_id,
                "stem_md": question.stem_md,
                "view": public_view(spec),
                "response": answer.response,
                "time_ms": answer.time_ms,
                "self_confidence": answer.self_confidence,
                "has_photo": answer.response_image_key is not None,
            }
            if done:
                item |= {
                    "question_attempt_id": answer.id,
                    "score": answer.score,
                    "marked_by": answer.marked_by,
                    "marking_confidence": answer.marking_confidence,
                    "feedback": answer.feedback,
                    "mistake_category": answer.mistake_category,
                    "correct_answer": correct_answer_text(spec),
                    "solution_md": question.solution_md,
                    "sources": question.sources,
                }
            items.append(AttemptItem.model_validate(item))
        summary = await self._summary(attempt, rows) if done else None
        return AttemptOut(
            id=attempt.id,
            quiz=QuizOut.model_validate(quiz),
            mode=attempt.mode,
            status=attempt.status,
            started_at=attempt.started_at,
            deadline=attempt.deadline,
            submitted_at=attempt.submitted_at,
            items=items,
            summary=summary,
        )

    async def _summary(self, attempt: QuizAttempt, rows: Sequence[Any]) -> AttemptSummary:
        limits = self.config.practice
        correct_at = limits.marking.correct_at
        topic_ids = {question.topic_id for _, _, question in rows if question.topic_id}
        titles = {
            t.id: t.title
            for t in await self.db.scalars(select(Topic).where(Topic.id.in_(topic_ids)))
        }
        scores = [answer.score for _, answer, _ in rows]
        marked = [s for s in scores if s is not None]

        def breakdown(key_of: Any, label_of: Any) -> list[Breakdown]:
            groups: dict[str, list[float | None]] = defaultdict(list)
            labels: dict[str, str] = {}
            for _, answer, question in rows:
                key = key_of(question)
                groups[key].append(answer.score)
                labels[key] = label_of(question)
            out = []
            for key, values in groups.items():
                done = [v for v in values if v is not None]
                out.append(
                    Breakdown(
                        key=key,
                        label=labels[key],
                        questions=len(values),
                        score=sum(done) / len(done) if done else 0.0,
                    )
                )
            return sorted(out, key=lambda b: b.score)

        order = ["easy", "medium", "hard", "exam"]
        by_difficulty = sorted(
            breakdown(lambda q: q.difficulty, lambda q: q.difficulty.capitalize()),
            key=lambda b: order.index(b.key),
        )
        by_topic = breakdown(
            lambda q: str(q.topic_id) if q.topic_id else "none",
            lambda q: titles.get(q.topic_id, "No topic") if q.topic_id else "No topic",
        )
        weak = [
            b.label
            for b in by_topic
            if b.score < limits.quizzes.weak_area_below and b.key != "none"
        ]
        wrong = sum(1 for s in marked if s < correct_at)
        unmarked = len(scores) - len(marked)
        steps = []
        if wrong:
            steps.append(f"Retry the {wrong} question{'s' if wrong != 1 else ''} you got wrong.")
        for b in by_topic:
            if b.score < limits.quizzes.weak_area_below and b.key != "none":
                steps.append(f"Revise {b.label}: you scored {round(b.score * 100)}% on it.")
        if unmarked and attempt.status == "marked":
            steps.append(
                f"Mark the {unmarked} unmarked answer{'s' if unmarked != 1 else ''} yourself."
            )
        if marked and not wrong and not unmarked:
            steps.append("Everything right: try harder questions next time.")
        taken = (
            int((attempt.submitted_at - attempt.started_at).total_seconds())
            if attempt.submitted_at
            else None
        )
        return AttemptSummary(
            questions=len(rows),
            answered=sum(1 for _, answer, _ in rows if answer.response is not None),
            correct=sum(1 for s in marked if s >= correct_at),
            partial=sum(1 for s in marked if 0 < s < correct_at),
            incorrect=sum(1 for s in marked if s == 0),
            unmarked=unmarked,
            score=attempt.score,
            time_taken_seconds=taken,
            by_difficulty=by_difficulty,
            by_topic=by_topic,
            weak_areas=weak,
            next_steps=steps,
        )
