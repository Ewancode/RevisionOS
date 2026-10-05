"""Ordering Today's panels by what is pressing."""

from hypothesis import given
from hypothesis import strategies as st

from app.analytics.dashboard import Pressing, rank
from app.core.config import PANELS, get_config

CONFIG = get_config().analytics.dashboard


def keys(pressing: Pressing) -> list[str]:
    return [p.key for p in rank(CONFIG, pressing)]


def test_with_nothing_pressing_the_usual_order_holds() -> None:
    panels = rank(CONFIG, Pressing())
    assert [p.key for p in panels] == CONFIG.order
    assert all(p.reason is None for p in panels)


def test_pressing_things_move_up_and_say_why() -> None:
    soon = rank(CONFIG, Pressing(exam_days=3, exam_title="MATH101 final", cards_due=4))
    assert [p.key for p in soon][:2] == ["todays_revision", "exams"]
    assert soon[0].reason == "MATH101 final is in 3 days"
    # 4 cards is below the threshold: no boost.
    assert next(p for p in soon if p.key == "flashcards").reason is None

    busy = keys(Pressing(quiz_not_done=True, cards_due=30))
    assert busy.index("daily_quiz") < busy.index("glance")
    assert busy.index("flashcards") < busy.index("recommended")
    far = keys(Pressing(exam_days=30, exam_title="x"))
    assert far == CONFIG.order


@given(
    st.one_of(st.none(), st.integers(min_value=0, max_value=60)),
    st.booleans(),
    st.integers(min_value=0, max_value=100),
    st.integers(min_value=0, max_value=5),
)
def test_every_panel_appears_once(exam: int | None, quiz: bool, cards: int, mistakes: int) -> None:
    ranked = keys(
        Pressing(
            exam_days=exam,
            exam_title="E",
            quiz_not_done=quiz,
            cards_due=cards,
            recurring_mistakes=mistakes,
        )
    )
    assert sorted(ranked) == sorted(PANELS)
