"""The revision planner: exams, availability, preferences, the plan, the
calendar, "I have N minutes" and notifications (ARCHITECTURE.md section 11)."""

import uuid
from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import Client, Config, CurrentUser, DbSession
from app.core.settings import get_settings
from app.schemas.planner import (
    AvailabilityIn,
    AvailabilityOut,
    AvailabilityProposal,
    AvailabilityText,
    BuiltBlock,
    BuiltSession,
    CalendarOut,
    ExamIn,
    ExamOut,
    ExamUpdate,
    NotificationOut,
    NotificationsOut,
    PlanOut,
    PreferencesIn,
    PreferencesOut,
    PushConfig,
    PushSubscriptionIn,
    PushTestOut,
    PushUnsubscribe,
    SessionMove,
    SessionStatusIn,
    StudySessionOut,
)
from app.services.planner import PlannerService

router = APIRouter(tags=["planner"])


def _planner(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> PlannerService:
    return PlannerService(db, user.id, client, config=config, claude=request.app.state.claude)


Planner = Annotated[PlannerService, Depends(_planner)]


# --- exams ------------------------------------------------------------------------------


@router.get("/exams", response_model=list[ExamOut])
async def list_exams(planner: Planner, module_id: uuid.UUID | None = None) -> list[ExamOut]:
    return await planner.exams(module_id)


@router.post("/exams", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
async def create_exam(body: ExamIn, planner: Planner) -> ExamOut:
    """Add an exam; the plan is remade around it."""
    return await planner.create_exam(body)


@router.patch("/exams/{exam_id}", response_model=ExamOut)
async def update_exam(exam_id: uuid.UUID, body: ExamUpdate, planner: Planner) -> ExamOut:
    return await planner.update_exam(exam_id, body)


@router.delete("/exams/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exam(exam_id: uuid.UUID, planner: Planner) -> None:
    await planner.delete_exam(exam_id)


# --- availability and preferences ------------------------------------------------------


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(planner: Planner) -> AvailabilityOut:
    return await planner.availability()


@router.put("/availability", response_model=AvailabilityOut)
async def set_availability(body: AvailabilityIn, planner: Planner) -> AvailabilityOut:
    return await planner.set_availability(body)


@router.delete("/availability/overrides/{day}", response_model=AvailabilityOut)
async def delete_override(day: date, planner: Planner) -> AvailabilityOut:
    return await planner.delete_override(day)


@router.post("/availability/parse", response_model=AvailabilityProposal)
async def parse_availability(body: AvailabilityText, planner: Planner) -> AvailabilityProposal:
    """Turn "3 hours every weekday, 1 hour at weekends" into rules to confirm.
    Nothing is saved."""
    return await planner.parse_availability(body.text)


@router.get("/planner/preferences", response_model=PreferencesOut)
async def get_preferences(planner: Planner) -> PreferencesOut:
    return await planner.preferences()


@router.patch("/planner/preferences", response_model=PreferencesOut)
async def set_preferences(body: PreferencesIn, planner: Planner) -> PreferencesOut:
    return await planner.set_preferences(body)


# --- the plan ----------------------------------------------------------------------------


@router.get("/plan", response_model=PlanOut)
async def get_plan(planner: Planner) -> PlanOut:
    """Today's sessions and the next two weeks, remade first if out of date."""
    return await planner.plan()


@router.patch("/sessions/{session_id}", response_model=StudySessionOut)
async def move_session(
    session_id: uuid.UUID, body: SessionMove, planner: Planner
) -> StudySessionOut:
    """Move or resize a session; it is then locked, and the rest rebalances."""
    return await planner.move(session_id, body.day, body.minutes)


@router.post("/sessions/{session_id}/status", response_model=StudySessionOut)
async def session_status(
    session_id: uuid.UUID, body: SessionStatusIn, planner: Planner
) -> StudySessionOut:
    return await planner.set_status(session_id, body.status, body.actual_minutes)


@router.get("/calendar", response_model=CalendarOut)
async def calendar(start: date, end: date, planner: Planner) -> CalendarOut:
    return await planner.calendar(start, end)


@router.get("/session-builder", response_model=BuiltSession)
async def build_session(
    planner: Planner, minutes: Annotated[int, Query(ge=1, le=1440)]
) -> BuiltSession:
    """ "I have N minutes": a session from today's priorities, with reasons."""
    built = await planner.build_session(minutes)
    return BuiltSession(
        minutes=built.minutes,
        summary=built.summary,
        blocks=[BuiltBlock.model_validate(asdict(b)) for b in built.blocks],
    )


@router.get("/recommendations", response_model=list[BuiltBlock])
async def recommendations(
    planner: Planner, limit: Annotated[int, Query(ge=1, le=10)] = 3
) -> list[BuiltBlock]:
    """What to study next, best first, each with the measurements behind it."""
    return [BuiltBlock.model_validate(asdict(b)) for b in await planner.recommendations(limit)]


# --- notifications --------------------------------------------------------------------------


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(planner: Planner) -> NotificationsOut:
    unread, items = await planner.notifications()
    return NotificationsOut(unread=unread, items=[NotificationOut.model_validate(n) for n in items])


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_notification(notification_id: int, planner: Planner) -> None:
    await planner.read(notification_id)


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all_notifications(planner: Planner) -> None:
    await planner.read(None)


# --- push -------------------------------------------------------------------------------------


@router.get("/push/config", response_model=PushConfig)
async def push_config(planner: Planner, request: Request) -> PushConfig:
    """Whether push is on, the public key browsers subscribe with, and how
    many of your devices are subscribed."""
    return await planner.push_config(
        get_settings().vapid_public_key, request.app.state.push is not None
    )


@router.post("/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_push(body: PushSubscriptionIn, planner: Planner) -> None:
    """Receive reminders on this device."""
    await planner.subscribe(body)


@router.post("/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push(body: PushUnsubscribe, planner: Planner) -> None:
    await planner.unsubscribe(body.endpoint)


@router.post("/push/test", response_model=PushTestOut)
async def test_push(planner: Planner, request: Request) -> PushTestOut:
    """Send a test notification to your devices."""
    return PushTestOut(delivered=await planner.test_push(request.app.state.push))
