"""Web Push: subscribing devices, and the scheduler pushing each reminder once."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from py_vapid import Vapid02
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import get_config
from app.models import Exam, Notification, PushSubscription, User, UserSettings
from app.planner.push import Delivery, dispatch
from scripts import vapid_keys
from tests.learning_support import make_module
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)  # 10:00 in London
CONFIG = get_config()


@dataclass
class FakeSender:
    """Records pushes; devices whose endpoint is in `gone` no longer exist."""

    sent: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    gone: set[str] = field(default_factory=set)
    failing: set[str] = field(default_factory=set)

    async def send(self, subscription: PushSubscription, payload: str, ttl: int) -> Delivery:
        if subscription.endpoint in self.gone:
            return Delivery(ok=False, gone=True)
        if subscription.endpoint in self.failing:
            return Delivery(ok=False, detail="503")
        self.sent.append((subscription.endpoint, json.loads(payload)))
        return Delivery(ok=True)


@pytest.fixture(autouse=True)
def frozen() -> Iterator[None]:
    clock.freeze(NOW)
    yield
    clock.freeze(None)


@pytest.fixture
async def owner(db: AsyncSession) -> User:
    return await make_user(db)


@pytest.fixture
def sender(db_app: FastAPI) -> FakeSender:
    fake = FakeSender()
    db_app.state.push = fake
    return fake


@pytest.fixture
async def client(db_app: FastAPI, owner: User) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, owner) as c:
        yield c


def device(n: int) -> dict[str, object]:
    return {
        "endpoint": f"https://push.example.com/send/{n}",
        "keys": {"p256dh": f"key{n}", "auth": f"auth{n}"},
        "label": f"Device {n}",
    }


async def test_devices_subscribe_and_unsubscribe(
    client: httpx.AsyncClient, sender: FakeSender, db: AsyncSession, owner: User
) -> None:
    config = (await client.get("/api/v1/push/config")).json()
    assert config["enabled"] and config["devices"] == 0
    for n in (1, 2, 2):  # the same device twice is one device
        assert (await client.post("/api/v1/push/subscriptions", json=device(n))).status_code == 204
    assert (await client.get("/api/v1/push/config")).json()["devices"] == 2
    insecure = await client.post(
        "/api/v1/push/subscriptions", json={**device(3), "endpoint": "http://push.example.com/x"}
    )
    assert insecure.status_code == 422

    tested = await client.post("/api/v1/push/test")
    assert tested.json() == {"delivered": 2}
    assert sender.sent[0][1]["title"] == "Notifications are working."
    assert sender.sent[0][1]["url"] == "/settings"

    await client.post("/api/v1/push/unsubscribe", json={"endpoint": device(1)["endpoint"]})
    left = (await db.scalars(select(PushSubscription.endpoint))).all()
    assert left == [device(2)["endpoint"]]


async def test_push_is_off_without_keys(client: httpx.AsyncClient) -> None:
    config = (await client.get("/api/v1/push/config")).json()
    assert config == {"enabled": False, "public_key": None, "devices": 0}
    off = await client.post("/api/v1/push/test")
    assert off.status_code == 409 and off.json()["error"]["code"] == "push_off"


async def _subscribed(db: AsyncSession, owner: User, *endpoints: str) -> None:
    for endpoint in endpoints:
        db.add(PushSubscription(user_id=owner.id, endpoint=endpoint, p256dh="k", auth="a"))
    await db.commit()


async def test_the_scheduler_pushes_each_reminder_once(db: AsyncSession, owner: User) -> None:
    module, _, _ = await make_module(db, owner, "MATH101", ["Series"])
    db.add(
        Exam(
            id=uuid.uuid4(), user_id=owner.id, module_id=module.id, title="MATH101 final",
            starts_at=NOW + timedelta(days=7), duration_minutes=120,
        )
    )  # fmt: skip
    await _subscribed(db, owner, "https://p/phone", "https://p/old", "https://p/flaky")
    sender = FakeSender(gone={"https://p/old"}, failing={"https://p/flaky"})

    delivered = await dispatch(db, sender, CONFIG, NOW)
    assert delivered == 1
    [(endpoint, message)] = sender.sent
    assert endpoint == "https://p/phone"
    assert message["title"] == "Your MATH101 exam is in 7 days."
    assert message["url"] == "/planner" and message["tag"] == "revision-os-exam"
    devices = {d.endpoint: d.failures for d in await db.scalars(select(PushSubscription))}
    assert devices == {"https://p/phone": 0, "https://p/flaky": 1}  # the gone one is forgotten

    # Next tick: nothing new, so nothing is pushed again.
    assert await dispatch(db, sender, CONFIG, NOW + timedelta(minutes=5)) == 0
    # A device that keeps failing is forgotten.
    for _ in range(CONFIG.planner.notifications.push_max_failures):
        db.add(Notification(user_id=owner.id, kind="x", title="t", dedupe_key=str(uuid.uuid4())))
        await db.commit()
        await dispatch(db, sender, CONFIG, NOW + timedelta(minutes=10))
    endpoints = (await db.scalars(select(PushSubscription.endpoint))).all()
    assert endpoints == ["https://p/phone"]


async def test_read_old_and_quiet_hours_are_not_pushed(db: AsyncSession, owner: User) -> None:
    await _subscribed(db, owner, "https://p/phone")
    db.add_all(
        [
            Notification(user_id=owner.id, kind="x", title="read", dedupe_key="r", read_at=NOW),
            Notification(user_id=owner.id, kind="x", title="fresh", dedupe_key="f"),
        ]
    )
    await db.commit()
    settings = await db.get(UserSettings, owner.id)
    assert settings is not None
    settings.quiet_from, settings.quiet_to = 9, 12  # 10:00 London is quiet
    await db.commit()
    sender = FakeSender()
    assert await dispatch(db, sender, CONFIG, NOW) == 0
    settings.quiet_from = settings.quiet_to = None
    await db.commit()
    # A day later the unread one is too old to push.
    late = NOW + timedelta(hours=CONFIG.planner.notifications.push_max_age_hours + 1)
    assert await dispatch(db, sender, CONFIG, late) == 0
    assert await dispatch(db, sender, CONFIG, NOW) == 1
    assert [m["title"] for _, m in sender.sent] == ["fresh"]


def test_vapid_keys_are_written_once_and_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("POSTGRES_USER=x\nVAPID_PUBLIC_KEY=\nVAPID_PRIVATE_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(vapid_keys, "ENV", env)
    assert vapid_keys.main() == 0
    values = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert values["POSTGRES_USER"] == "x" and values["VAPID_SUBJECT"] == "mailto:admin@localhost"
    # The private key is one pywebpush accepts, and matches the public key.
    vapid = Vapid02.from_string(values["VAPID_PRIVATE_KEY"])
    assert (
        vapid_keys.b64url(vapid.public_key.public_bytes(*vapid_keys_encoding()))
        == values["VAPID_PUBLIC_KEY"]
    )
    before = env.read_text(encoding="utf-8")
    assert vapid_keys.main() == 0
    assert env.read_text(encoding="utf-8") == before  # existing keys are never replaced


def vapid_keys_encoding() -> tuple[object, object]:
    from cryptography.hazmat.primitives import serialization

    return serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
