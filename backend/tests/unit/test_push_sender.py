"""The real Web Push sender, end to end without a browser: a local server
plays the push service, and the test decrypts the message as the browser
would and checks the VAPID signature."""

import base64
import json
import os
from typing import Any

import http_ece
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.core.config import get_config
from app.models import PushSubscription
from app.planner.push import VapidSender
from scripts.vapid_keys import b64url, generate


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


async def push_service(status: int) -> tuple[TestServer, list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []

    async def handle(request: web.Request) -> web.Response:
        # Header names are case-insensitive (pywebpush sends "ttl").
        received.append({"headers": request.headers.copy(), "body": await request.read()})
        return web.Response(status=status)

    app = web.Application()
    app.router.add_post("/push/{device}", handle)
    server = TestServer(app)
    await server.start_server()
    return server, received


async def test_a_push_is_encrypted_for_the_device_and_signed() -> None:
    server, received = await push_service(201)
    try:
        # The browser's side: its key pair and auth secret.
        device_key = ec.generate_private_key(ec.SECP256R1())
        device_public = device_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        auth = os.urandom(16)
        vapid_public, vapid_private = generate()
        subscription = PushSubscription(
            endpoint=str(server.make_url("/push/abc")),
            p256dh=b64url(device_public),
            auth=b64url(auth),
        )
        sent = await VapidSender(vapid_private, "mailto:test@example.com").send(
            subscription, json.dumps({"title": "Your exam is in 7 days."}), ttl=60
        )
        assert sent.ok
        [request] = received
        headers = request["headers"]
        assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == "60"

        # Only the device can read it.
        plain = http_ece.decrypt(
            request["body"], private_key=device_key, auth_secret=auth, version="aes128gcm"
        )
        assert json.loads(plain) == {"title": "Your exam is in 7 days."}

        # Signed with our VAPID key, for this push service, by this contact.
        scheme, _, params = headers["Authorization"].partition(" ")
        assert scheme == "vapid"
        fields = dict(part.strip().split("=", 1) for part in params.split(","))
        assert fields["k"] == vapid_public
        header_b64, claims_b64, signature_b64 = fields["t"].split(".")
        claims = json.loads(unb64(claims_b64))
        assert claims["sub"] == "mailto:test@example.com"
        assert claims["aud"] == str(server.make_url("/")).rstrip("/")
        raw = unb64(signature_b64)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(vapid_public))
        public.verify(
            encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
            f"{header_b64}.{claims_b64}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )
    finally:
        await server.close()


async def test_a_device_that_is_gone_is_reported() -> None:
    server, _ = await push_service(410)
    try:
        key = (
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        )
        _, private = generate()
        subscription = PushSubscription(
            endpoint=str(server.make_url("/push/old")),
            p256dh=b64url(key),
            auth=b64url(os.urandom(16)),
        )
        result = await VapidSender(private, "mailto:test@example.com").send(
            subscription, "{}", ttl=60
        )
        assert not result.ok and result.gone
    finally:
        await server.close()


async def test_the_sender_never_calls_anything_but_a_push_service() -> None:
    server, received = await push_service(201)
    try:
        _, private = generate()
        subscription = PushSubscription(
            endpoint=str(server.make_url("/push/x")), p256dh="k", auth="a"
        )
        hosts = get_config().planner.notifications.push_hosts
        result = await VapidSender(private, "mailto:test@example.com", hosts).send(
            subscription, "{}", ttl=60
        )
        assert not result.ok and result.gone
        assert received == []  # no request was made
    finally:
        await server.close()
