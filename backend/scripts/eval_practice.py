"""Check question generation and marking against the real Claude API (local
only; costs money).

Usage: ``make eval-practice`` (or ``python -m scripts.eval_practice --yes``).

1. Generates questions for a module (one cheap-route draft, one exam-route
   draft) and reports how many passed the app's checks first time, after
   the repair round, and why any failed.
2. Builds a quiz from the valid questions and answers it twice: once with
   the correct answers, once with wrong ones. Both attempts are marked by the
   real pipeline (rules, SymPy and Claude). Right answers should score high
   and wrong ones low, for every answer type.

Everything it creates is removed afterwards; the AI usage stays recorded.
Without ``--yes`` it only prints the estimated cost.
"""

import argparse
import asyncio
import sys
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select

from app.ai.client import create_client
from app.core.config import get_config
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.models import AIUsage, Draft, Module, Question, QuestionAttempt, Quiz, User
from app.practice.answers import (
    AnswerSpec,
    DerivationSpec,
    ExplanationSpec,
    ExpressionSpec,
    MultipleChoiceSpec,
    NumericalSpec,
    ShortAnswerSpec,
    TrueFalseSpec,
    load_spec,
)
from app.practice.generation import run_draft
from app.practice.marking import mark_attempt
from app.retrieval.embeddings import create_provider
from app.schemas.practice import DraftSave, GenerateRequest, QuizCreate
from app.services.common import ClientInfo
from app.services.drafts import DraftService
from app.services.quizzes import QuizService, submit_attempt

ESTIMATE = 0.60  # GBP, worst case for the default run
RIGHT_AT_LEAST, WRONG_AT_MOST = 0.75, 0.25


class Jobs:
    """Collects jobs instead of queueing them; this script runs them itself."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        self.jobs.append((function, args))


def right_answer(spec: AnswerSpec) -> dict[str, Any]:
    if isinstance(spec, MultipleChoiceSpec):
        return {"choice": spec.correct}
    if isinstance(spec, TrueFalseSpec):
        return {"answer": spec.answer}
    if isinstance(spec, NumericalSpec):
        return {"value": repr(spec.value), "unit": spec.unit}
    if isinstance(spec, ExpressionSpec):
        return {"expression": spec.answer}
    if isinstance(spec, ShortAnswerSpec):
        return {"text": spec.accepted[0]}
    if isinstance(spec, ExplanationSpec | DerivationSpec):
        return {"text": spec.model_answer}
    raise TypeError(spec)


def wrong_answer(spec: AnswerSpec) -> dict[str, Any]:
    if isinstance(spec, MultipleChoiceSpec):
        return {"choice": (spec.correct + 1) % len(spec.options)}
    if isinstance(spec, TrueFalseSpec):
        return {"answer": not spec.answer}
    if isinstance(spec, NumericalSpec):
        return {"value": repr(spec.value * 1.5 + 1), "unit": spec.unit}
    if isinstance(spec, ExpressionSpec):
        return {"expression": f"({spec.answer}) + 1"}
    if isinstance(spec, ShortAnswerSpec):
        return {"text": "the mean value theorem for integrals"}
    return {"text": "I am not sure. It follows from the definitions."}


async def main(module_code: str | None, count: int) -> int:
    settings, config = get_settings(), get_config()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    if not key:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url.get_secret_value())
    sessions = create_session_factory(engine)
    embedder = create_provider(config.retrieval.embeddings, settings.model_cache_dir)
    claude = create_client(key, config.ai)
    jobs = Jobs()
    client = ClientInfo(None, "eval_practice")
    created_questions: list[uuid.UUID] = []
    created_quiz: uuid.UUID | None = None
    drafts: list[uuid.UUID] = []
    failures = 0
    try:
        async with sessions() as db:
            [user] = (await db.scalars(select(User))).all()
            stmt = select(Module).where(Module.user_id == user.id, Module.deleted_at.is_(None))
            if module_code:
                stmt = stmt.where(Module.code == module_code.upper())
            module = (await db.scalars(stmt.order_by(Module.code))).first()
            if module is None:
                print("No such module.", file=sys.stderr)
                return 2
            started = await db.scalar(select(AIUsage.id).order_by(AIUsage.id.desc()).limit(1)) or 0

            # 1. Generation.
            service = DraftService(db, user.id, client, config=config, jobs=jobs)
            requests = [
                {"difficulty": "mixed", "count": count},  # cheap route
                {
                    "difficulty": "exam",
                    "count": max(2, count // 2),
                    "types": ["numerical", "expression", "explanation", "derivation"],
                },
            ]
            totals: defaultdict[str, int] = defaultdict(int)
            for extra in requests:
                draft = await service.create(
                    GenerateRequest(module_id=module.id, kind="questions", **extra)
                )
                drafts.append(draft.id)
                await run_draft(db, claude, embedder, config, draft.id)
                await db.refresh(draft)
                if draft.status != "ready" or draft.payload is None:
                    print(f"generation failed: {draft.error_code}")
                    failures += 1
                    continue
                items = draft.payload["items"]
                totals["generated"] += len(items)
                totals["valid"] += sum(1 for i in items if i["valid"])
                totals["repaired"] += sum(1 for i in items if i.get("repaired"))
                totals["first_time"] += sum(
                    1 for i in items if i["valid"] and not i.get("repaired")
                )
                for item in items:
                    if not item["valid"]:
                        print(f"  rejected ({item.get('type')}): {'; '.join(item['problems'])}")
                before = set((await db.scalars(select(Question.id))).all())
                await service.save(draft.id, DraftSave())
                created_questions += [
                    q for q in (await db.scalars(select(Question.id))).all() if q not in before
                ]
            print(
                f"Generated {totals['generated']}: {totals['first_time']} valid first time, "
                f"{totals['repaired']} fixed by the repair round, "
                f"{totals['valid']} valid in all "
                f"({totals['valid'] / max(1, totals['generated']):.0%})."
            )
            if not created_questions:
                return 1

            # 2. Marking, with right answers then wrong ones.
            quizzes = QuizService(db, user.id, client, config=config, jobs=jobs)
            quiz, first = await quizzes.create(
                QuizCreate(module_id=module.id, question_ids=created_questions)
            )
            created_quiz = quiz.id
            second = await quizzes.start(quiz.id)
            questions = {
                q.id: q
                for q in await db.scalars(
                    select(Question).where(Question.id.in_(created_questions))
                )
            }
            results: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
            scores: dict[str, dict[uuid.UUID, float | None]] = {}
            feedback: dict[str, dict[uuid.UUID, Any]] = {}
            for name, attempt, answer in (
                ("right", first, right_answer),
                ("wrong", second, wrong_answer),
            ):
                rows = (
                    await db.scalars(
                        select(QuestionAttempt).where(QuestionAttempt.quiz_attempt_id == attempt.id)
                    )
                ).all()
                for row in rows:
                    row.response = answer(load_spec(questions[row.question_id].answer_spec))
                await db.commit()
                await submit_attempt(db, config, jobs, attempt)
                for job, args in jobs.jobs:
                    if job == "mark_attempt":
                        await mark_attempt(db, claude, config, uuid.UUID(args[0]))
                jobs.jobs.clear()
                rows = (
                    await db.scalars(
                        select(QuestionAttempt).where(QuestionAttempt.quiz_attempt_id == attempt.id)
                    )
                ).all()
                for row in rows:
                    await db.refresh(row)
                scores[name] = {row.question_id: row.score for row in rows}
                feedback[name] = {row.question_id: row.feedback for row in rows}
            for qid, question in questions.items():
                right, wrong = scores["right"][qid], scores["wrong"][qid]
                results[question.type].append((right, wrong))
                expected = (right or 0) >= RIGHT_AT_LEAST and (
                    wrong if wrong is not None else 1
                ) <= WRONG_AT_MOST
                if not expected:
                    spec = load_spec(question.answer_spec)
                    print()
                    print(f"Unexpected marks on a {question.type} question: {right} / {wrong}")
                    print(f"  question: {question.stem_md[:300]}")
                    print(f"  submitted as right: {str(right_answer(spec))[:400]}")
                    print(f"  feedback on it: {feedback['right'][qid]}")

            print("\nMarking (right answers / wrong answers):")
            for type_, pairs in sorted(results.items()):
                ok = sum(
                    1
                    for right, wrong in pairs
                    if right is not None
                    and wrong is not None
                    and right >= RIGHT_AT_LEAST
                    and wrong <= WRONG_AT_MOST
                )
                failures += len(pairs) - ok
                shown = ", ".join(
                    f"{'-' if r is None else round(r, 2)}/{'-' if w is None else round(w, 2)}"
                    for r, w in pairs
                )
                print(f"  {type_:16} {ok}/{len(pairs)} as expected   ({shown})")
            spent = sum(
                (
                    await db.scalars(select(AIUsage.estimated_cost_usd).where(AIUsage.id > started))
                ).all()
            )
            print(f"\nCost: {config.ai.budget.from_usd(spent):.3f} {config.ai.budget.currency}")
    finally:
        async with sessions() as db:
            if created_quiz:
                await db.execute(delete(Quiz).where(Quiz.id == created_quiz))
            if created_questions:
                await db.execute(delete(Question).where(Question.id.in_(created_questions)))
            if drafts:
                await db.execute(delete(Draft).where(Draft.id.in_(drafts)))
            await db.commit()
        await engine.dispose()
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--module", help="module code (default: the first one)")
    parser.add_argument("--count", type=int, default=8, help="questions in the first draft")
    parser.add_argument("--yes", action="store_true", help="spend money on real API calls")
    args = parser.parse_args()
    if not args.yes:
        print(
            f"Would generate about {args.count + args.count // 2} questions and mark two "
            f"attempts, costing up to about {ESTIMATE:.2f} GBP. Run again with --yes."
        )
        sys.exit(0)
    sys.exit(asyncio.run(main(args.module, args.count)))
