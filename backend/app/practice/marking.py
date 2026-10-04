"""Marking a submitted quiz (ARCHITECTURE.md section 10, "Marking").

Rule-marked answers (multiple choice, true/false, numerical, algebraic, and
short answers that match an accepted wording) are marked when the quiz is
submitted. This worker step then:

1. marks the rest with Claude against a rubric (explanations, derivations,
   and short or algebraic answers the rules could not decide), re-marking on
   the stronger model when Claude's confidence is low;
2. explains every wrong rule-marked answer in one call: why it is wrong, the
   correct answer, the reasoning, the mistake, and how to avoid it;
3. records a mistake category from learning.yaml for the mistake bank.

If Claude is unavailable or the budget is used up, answers it would have
marked stay unmarked (the student can mark them) and nothing else fails.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient, parse_json, text_tokens
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.learning import mastery
from app.models import Question, QuestionAttempt, QuizAttempt, QuizItem
from app.practice.answers import (
    AnswerSpec,
    DerivationSpec,
    ExplanationSpec,
    ExpressionSpec,
    RubricPoint,
    ShortAnswerSpec,
    correct_answer_text,
    load_spec,
    response_text,
)
from app.practice.generation import prompt

logger = logging.getLogger(__name__)

MARK_PROMPT = "mark_answer.v1"
EXPLAIN_PROMPT = "explain_mistakes.v1"
CONFIDENCE = {"low": 0, "medium": 1, "high": 2}

EXPLANATION_FIELDS = ("why_wrong", "correct_answer", "reasoning", "mistake", "how_to_avoid")
_explanation: dict[str, Any] = {
    "type": "object",
    "properties": {
        "why_wrong": {"type": "string"},
        "correct_answer": {"type": "string"},
        "reasoning": {"type": "string"},
        "mistake": {"type": "string"},
        "how_to_avoid": {"type": "string"},
    },
    "required": list(EXPLANATION_FIELDS),
    "additionalProperties": False,
}


# Structured outputs reject an enum on a ["string", "null"] type, so nullable
# values are written as anyOf.
def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _category(categories: tuple[str, ...]) -> dict[str, Any]:
    return _nullable({"type": "string", "enum": list(categories)})


def mark_schema(categories: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"awarded": {"type": "number"}, "comment": {"type": "string"}},
                    "required": ["awarded", "comment"],
                    "additionalProperties": False,
                },
            },
            "feedback": {"type": "string"},
            "confidence": {"type": "string", "enum": list(CONFIDENCE)},
            "explanation": _nullable(_explanation),
            "mistake_category": _category(categories),
        },
        "required": ["points", "feedback", "confidence", "explanation", "mistake_category"],
        "additionalProperties": False,
    }


def explain_schema(categories: tuple[str, ...]) -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "item": {"type": "integer"},
            **{k: {"type": "string"} for k in EXPLANATION_FIELDS},
            "mistake_category": _category(categories),
        },
        "required": ["item", *EXPLANATION_FIELDS, "mistake_category"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item}},
        "required": ["items"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class AIMark:
    score: float
    confidence: str
    feedback: dict[str, Any]
    category: str | None


def rubric_for(spec: AnswerSpec) -> list[RubricPoint]:
    if isinstance(spec, ExplanationSpec | DerivationSpec):
        return spec.rubric
    if isinstance(spec, ShortAnswerSpec):
        accepted = "; ".join(spec.accepted)
        return [RubricPoint(point=f"Means the same as an accepted answer: {accepted}", marks=1)]
    if isinstance(spec, ExpressionSpec):
        return [RubricPoint(point=f"Equivalent to {spec.answer}", marks=1)]
    return [RubricPoint(point=f"Correct: {correct_answer_text(spec)}", marks=1)]


async def ai_mark(
    db: AsyncSession,
    claude: ClaudeClient,
    config: AppConfig,
    user_id: uuid.UUID,
    question: Question,
    spec: AnswerSpec,
    response: dict[str, Any] | None,
    *,
    escalate: bool = False,
) -> AIMark:
    rubric = rubric_for(spec)
    task = "proof_marking" if question.type in ("explanation", "derivation") else "simple_marking"
    model_answer = (
        spec.model_answer
        if isinstance(spec, ExplanationSpec | DerivationSpec)
        else correct_answer_text(spec)
    )
    text = (
        f"Question:\n{question.stem_md}\n\n"
        "Rubric:\n"
        + "\n".join(f"{i}. ({p.marks} marks) {p.point}" for i, p in enumerate(rubric, 1))
        + f"\n\nModel answer:\n{model_answer}\n\nWorked solution:\n{question.solution_md}\n\n"
        f"Student's answer:\n<student_answer>\n{response_text(question.type, response)}\n"
        "</student_answer>"
    )
    categories = config.learning.mistakes.categories
    system = prompt(MARK_PROMPT) + f"\n\nMistake categories: {', '.join(categories)}."
    result = await claude.run(
        db,
        user_id=user_id,
        task=task,
        prompt_version=MARK_PROMPT,
        system=system,
        content=[{"type": "text", "text": text}],
        estimated_input_tokens=text_tokens(system) + text_tokens(text),
        output_schema=mark_schema(categories),
        escalate=escalate,
        module_id=question.module_id,
    )
    data = parse_json(result.text)
    awarded = list(data.get("points") or [])
    points = []
    total = sum(p.marks for p in rubric)
    earned = 0.0
    for i, point in enumerate(rubric):
        got = awarded[i] if i < len(awarded) and isinstance(awarded[i], dict) else {}
        value = min(max(float(got.get("awarded") or 0.0), 0.0), float(point.marks))
        earned += value
        points.append(
            {"point": point.point, "marks": point.marks, "awarded": value,
             "comment": str(got.get("comment", ""))}
        )  # fmt: skip
    score = earned / total if total else 0.0
    explanation = data.get("explanation") if score < config.practice.marking.correct_at else None
    category = data.get("mistake_category") if explanation else None
    return AIMark(
        score=score,
        confidence=str(data.get("confidence")) if data.get("confidence") in CONFIDENCE else "low",
        feedback={
            "summary": str(data.get("feedback", "")),
            "points": points,
            "explanation": explanation if isinstance(explanation, dict) else None,
        },
        category=category if category in categories else None,
    )


async def _explain(
    db: AsyncSession,
    claude: ClaudeClient,
    config: AppConfig,
    user_id: uuid.UUID,
    wrong: list[tuple[QuestionAttempt, Question, AnswerSpec]],
) -> None:
    """One call explaining every wrong rule-marked answer in the quiz."""
    if not wrong:
        return
    parts = []
    for i, (attempt, question, spec) in enumerate(wrong, 1):
        parts.append(
            f"Item {i} ({question.type})\nQuestion:\n{question.stem_md}\n"
            + (
                "Options:\n" + "\n".join(f"{n}. {o}" for n, o in enumerate(spec.options, 1)) + "\n"
                if spec.type == "multiple_choice"
                else ""
            )
            + f"Correct answer: {correct_answer_text(spec)}\n"
            f"Worked solution:\n{question.solution_md}\n"
            f"Student's answer:\n<student_answer>\n{response_text(question.type, attempt.response)}"
            "\n</student_answer>"
        )
    text = "\n\n---\n\n".join(parts)
    categories = config.learning.mistakes.categories
    system = prompt(EXPLAIN_PROMPT) + f"\n\nMistake categories: {', '.join(categories)}."
    result = await claude.run(
        db,
        user_id=user_id,
        task="explanation",
        prompt_version=EXPLAIN_PROMPT,
        system=system,
        content=[{"type": "text", "text": text}],
        estimated_input_tokens=text_tokens(system) + text_tokens(text),
        output_schema=explain_schema(categories),
        module_id=wrong[0][1].module_id,
    )
    for entry in parse_json(result.text).get("items") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("item"), int):
            continue
        index = entry["item"] - 1
        if not 0 <= index < len(wrong):
            continue
        attempt = wrong[index][0]
        explanation = {k: str(entry.get(k, "")) for k in EXPLANATION_FIELDS}
        attempt.feedback = {**(attempt.feedback or {}), "explanation": explanation}
        category = entry.get("mistake_category")
        attempt.mistake_category = category if category in categories else None


def _needs_remark(confidence: str, config: AppConfig) -> bool:
    return CONFIDENCE[confidence] <= CONFIDENCE[config.practice.marking.remark_at_or_below]


async def mark_one(
    db: AsyncSession,
    claude: ClaudeClient,
    config: AppConfig,
    attempt: QuestionAttempt,
    question: Question,
    *,
    escalate: bool = False,
) -> None:
    """Mark one answer with Claude (re-marking once on the stronger model if
    unsure). Raises AppError if Claude cannot be used."""
    spec = load_spec(question.answer_spec)
    mark = await ai_mark(
        db, claude, config, attempt.user_id, question, spec, attempt.response, escalate=escalate
    )
    written = question.type in ("explanation", "derivation")
    route = config.ai.routing["proof_marking" if written else "simple_marking"]
    if not escalate and route.escalate_to and _needs_remark(mark.confidence, config):
        mark = await ai_mark(
            db, claude, config, attempt.user_id, question, spec, attempt.response, escalate=True
        )
    attempt.score, attempt.marked_by = mark.score, "ai"
    attempt.marking_confidence = mark.confidence
    attempt.feedback, attempt.mistake_category = mark.feedback, mark.category
    attempt.marked_at = utcnow()


async def mark_attempt(
    db: AsyncSession, claude: ClaudeClient, config: AppConfig, attempt_id: uuid.UUID
) -> None:
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.status != "marking":
        return
    rows = (
        await db.execute(
            select(QuestionAttempt, Question)
            .join(Question, Question.id == QuestionAttempt.question_id)
            .join(
                QuizItem,
                (QuizItem.quiz_id == attempt.quiz_id)
                & (QuizItem.question_id == QuestionAttempt.question_id),
            )
            .where(QuestionAttempt.quiz_attempt_id == attempt.id)
            .order_by(QuizItem.position)
        )
    ).all()
    unavailable: str | None = None
    wrong: list[tuple[QuestionAttempt, Question, AnswerSpec]] = []
    for qa, question in rows:
        if qa.score is None:
            if unavailable is None:
                try:
                    await mark_one(db, claude, config, qa, question)
                    await db.commit()
                    continue
                except AppError as exc:
                    # The client has already recorded the failed call; the
                    # loaded rows stay valid (no rollback needed).
                    unavailable = exc.message
                    logger.warning("AI marking stopped", extra={"error": exc.code})
            qa.feedback = {"unmarked": f"Not marked: {unavailable} You can mark it yourself."}
        elif qa.marked_by in ("rule", "sympy") and qa.score < config.practice.marking.correct_at:
            wrong.append((qa, question, load_spec(question.answer_spec)))
    if unavailable is None and wrong:
        try:
            await _explain(db, claude, config, attempt.user_id, wrong)
        except AppError as exc:
            logger.warning("explanations skipped", extra={"error": exc.code})
    finish(attempt, [qa for qa, _ in rows])
    await db.commit()
    # Strength and difficulty follow every marked answer.
    await mastery.recompute_for_questions(
        db, attempt.user_id, [qa.question_id for qa, _ in rows], config, utcnow()
    )


def finish(attempt: QuizAttempt, answers: list[QuestionAttempt]) -> None:
    """Close marking: the score is the mean over marked answers."""
    marked = [qa.score for qa in answers if qa.score is not None]
    attempt.score = sum(marked) / len(marked) if marked else None
    attempt.status, attempt.marked_at = "marked", utcnow()
