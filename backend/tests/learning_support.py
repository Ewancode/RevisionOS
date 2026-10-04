"""Building course data directly in the database, for learning tests."""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.models import AcademicYear, Module, Question, Topic, User

DIFFICULTIES = ("easy", "medium", "hard")


async def make_module(
    db: AsyncSession, user: User, code: str, topics: list[str], year: AcademicYear | None = None
) -> tuple[Module, dict[str, Topic], AcademicYear]:
    if year is None:
        year = AcademicYear(
            id=uuid.uuid4(),
            user_id=user.id,
            label="2026/27",
            start_date=date(2026, 9, 21),
            end_date=date(2027, 6, 11),
            is_current=True,
        )
        db.add(year)
        await db.flush()
    module = Module(
        id=uuid.uuid4(), user_id=user.id, academic_year_id=year.id, code=code, title=code
    )
    db.add(module)
    await db.flush()
    made = {}
    for position, title in enumerate(topics):
        topic = Topic(
            id=uuid.uuid4(), user_id=user.id, module_id=module.id, title=title, position=position
        )
        db.add(topic)
        made[title] = topic
    await db.commit()
    return module, made, year


async def make_questions(
    db: AsyncSession, user: User, module: Module, topic: Topic | None, count: int
) -> list[Question]:
    """Multiple-choice questions (marked exactly, so no AI is needed);
    option 0 is right."""
    ratings = get_config().learning.difficulty.initial_ratings
    made = []
    for n in range(count):
        difficulty = DIFFICULTIES[n % len(DIFFICULTIES)]
        question = Question(
            id=uuid.uuid4(),
            user_id=user.id,
            module_id=module.id,
            topic_id=topic.id if topic else None,
            type="multiple_choice",
            difficulty=difficulty,
            rating=getattr(ratings, difficulty),
            stem_md=f"{topic.title if topic else module.code} question {n}",
            answer_spec={"type": "multiple_choice", "options": ["right", "wrong"], "correct": 0},
            solution_md="Because.",
            origin="claude",
        )
        db.add(question)
        made.append(question)
    await db.commit()
    return made
