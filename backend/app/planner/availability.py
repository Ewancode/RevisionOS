"""Plain-English availability to rules, via one structured Claude call
(ARCHITECTURE.md section 11). The result is a proposal: you confirm it
before it is saved."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient, parse_json, text_tokens
from app.core.config import AppConfig
from app.core.errors import AppError

PROMPT_VERSION = "availability.v1"
PROMPT = Path(__file__).parent.parent / "ai" / "prompts" / f"{PROMPT_VERSION}.md"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

SCHEMA = {
    "type": "object",
    "properties": {
        "weekdays": {
            "type": "object",
            "properties": {d: {"type": ["integer", "null"]} for d in WEEKDAYS},
            "required": list(WEEKDAYS),
            "additionalProperties": False,
        },
        "dates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"date": {"type": "string"}, "minutes": {"type": "integer"}},
                "required": ["date", "minutes"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["weekdays", "dates", "note"],
    "additionalProperties": False,
}


@dataclass
class Proposal:
    # Index 0 = Monday; None: unchanged.
    weekdays: list[int | None]
    dates: list[tuple[date, int]]
    note: str


async def parse(
    db: AsyncSession,
    claude: ClaudeClient,
    config: AppConfig,
    user_id: uuid.UUID,
    text: str,
    today: date,
) -> Proposal:
    system = PROMPT.read_text(encoding="utf-8")
    request = (
        f"Today is {today:%A} {today.isoformat()}.\n\nThe student says:\n<said>\n{text}\n</said>"
    )
    result = await claude.run(
        db,
        user_id=user_id,
        task="availability_parsing",
        prompt_version=PROMPT_VERSION,
        system=system,
        content=[{"type": "text", "text": request}],
        estimated_input_tokens=text_tokens(system) + text_tokens(request),
        output_schema=SCHEMA,
    )
    data = parse_json(result.text)
    limit = config.planner.availability.max_minutes_per_day
    weekdays: list[int | None] = []
    for name in WEEKDAYS:
        value = (data.get("weekdays") or {}).get(name)
        weekdays.append(None if value is None else min(max(int(value), 0), limit))
    dates = []
    for item in data.get("dates") or []:
        try:
            day = datetime.strptime(str(item.get("date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if day >= today:
            dates.append((day, min(max(int(item.get("minutes") or 0), 0), limit)))
    if all(w is None for w in weekdays) and not dates:
        raise AppError(
            "availability_unclear",
            str(
                data.get("note")
                or "That didn't describe any study time. Try e.g. "
                "“2 hours every weekday, 1 hour at weekends”."
            ),
            422,
        )
    return Proposal(weekdays, dates, str(data.get("note", "")))
