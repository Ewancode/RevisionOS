"""Security headers on every API response (ARCHITECTURE.md section 12).

The API only ever returns JSON, so its Content-Security-Policy forbids
everything. The SPA's own CSP is set where it is served (Phase 13).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # Authenticated JSON must never be stored by shared caches.
    "Cache-Control": "no-store",
}
_HSTS = "max-age=63072000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.headers = dict(_BASE_HEADERS)
        if hsts:
            self.headers["Strict-Transport-Security"] = _HSTS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
