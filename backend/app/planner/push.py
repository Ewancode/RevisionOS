"""Web Push: reminders reach your devices when the app is closed (Phase 11;
ARCHITECTURE.md section 11, "Notifications").

The scheduler runs `dispatch` every few minutes. For each user with a
subscribed device it makes any reminders now due (the same rules, quiet
hours and switches as the in-app bell), then pushes each unread one that has
not been pushed yet, to every device, once. A device the push service says
is gone (404/410) is forgotten at once; one that keeps failing, after
`push_max_failures` tries.
"""

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.models import Notification, PushSubscription, UserSettings
from app.planner import notifications
from app.planner.context import load

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Delivery:
    """What happened to one push: delivered, the device is gone, or failed."""

    ok: bool
    gone: bool = False
    detail: str = ""


def is_push_service(endpoint: str, hosts: Sequence[str]) -> bool:
    """An https URL on one of the known push services (or a subdomain), with
    no credentials or unusual port: never an address of our choosing."""
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return False
    host = (url.hostname or "").lower()
    if url.scheme != "https" or url.username or url.password or port not in (None, 443):
        return False
    return any(host == h or host.endswith("." + h) for h in hosts)


class Sender(Protocol):
    async def send(self, subscription: PushSubscription, payload: str, ttl: int) -> Delivery: ...


class VapidSender:
    """Sends with pywebpush, signed with the VAPID keys from the environment."""

    def __init__(self, private_key: str, subject: str, hosts: Sequence[str] | None = None) -> None:
        self.private_key = private_key
        self.subject = subject
        # None (tests only): any endpoint.
        self.hosts = hosts

    async def send(self, subscription: PushSubscription, payload: str, ttl: int) -> Delivery:
        if self.hosts is not None and not is_push_service(subscription.endpoint, self.hosts):
            # Checked at subscription too; a stored row is never trusted blindly.
            return Delivery(ok=False, gone=True, detail="not a push service")
        from pywebpush import WebPushException, webpush_async

        try:
            await webpush_async(
                {
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=self.private_key,
                vapid_claims={"sub": self.subject},
                ttl=ttl,
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status", None) or getattr(
                exc.response, "status_code", None
            )
            return Delivery(
                ok=False, gone=status in (404, 410), detail=f"push service said {status}"
            )
        except Exception as exc:
            return Delivery(ok=False, detail=type(exc).__name__)
        return Delivery(ok=True)


def create_sender(
    public_key: str | None,
    private_key: str | None,
    subject: str | None,
    hosts: Sequence[str],
) -> Sender | None:
    """Push is on only when all three VAPID settings are present."""
    if not (public_key and private_key and subject):
        return None
    return VapidSender(private_key, subject, hosts)


def payload(note: Notification) -> str:
    """What the service worker shows. The link opens the right page."""
    return json.dumps(
        {
            "title": note.title,
            "body": note.body,
            "url": note.link or "/",
            "tag": f"revision-os-{note.kind}",
            "id": note.id,
        }
    )


async def deliver(
    db: AsyncSession,
    sender: Sender,
    config: AppConfig,
    devices: Sequence[PushSubscription],
    notes: Sequence[Notification],
    now: datetime,
) -> int:
    """Push each note to each device; returns how many pushes were delivered."""
    rules = config.planner.notifications
    delivered = 0
    gone: set[uuid.UUID] = set()
    for note in notes:
        for device in devices:
            if device.id in gone:
                continue
            result = await sender.send(device, payload(note), rules.push_ttl_seconds)
            if result.ok:
                delivered += 1
                device.failures, device.last_sent_at = 0, now
            elif result.gone:
                gone.add(device.id)
            else:
                device.failures += 1
                logger.warning("push failed", extra={"detail": result.detail})
                if device.failures >= rules.push_max_failures:
                    gone.add(device.id)
        note.pushed_at = now
    if gone:
        await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
    await db.commit()
    return delivered


async def dispatch(db: AsyncSession, sender: Sender, config: AppConfig, now: datetime) -> int:
    """One scheduler tick, for every user with a device."""
    rules = config.planner.notifications
    users = (await db.scalars(select(PushSubscription.user_id).distinct())).all()
    total = 0
    for user_id in users:
        ctx = await load(db, user_id, config, now)
        # Nothing reaches your phone in your quiet hours; it waits until after.
        if notifications.is_quiet(
            await db.get(UserSettings, user_id), now.astimezone(ctx.zone).hour
        ):
            continue
        await notifications.refresh(db, user_id, ctx, config, now)
        await db.commit()
        notes = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.read_at.is_(None),
                    Notification.pushed_at.is_(None),
                    Notification.created_at >= now - timedelta(hours=rules.push_max_age_hours),
                )
            )
        ).all()
        if not notes:
            continue
        devices = (
            await db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
        ).all()
        total += await deliver(db, sender, config, devices, notes, now)
    return total
