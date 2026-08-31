"""ASGI middleware that stamps HTTP security headers on every response.

Written at the raw ASGI layer rather than ``BaseHTTPMiddleware`` so it never
buffers or breaks the streaming PDF / file-download responses.

The Content-Security-Policy matches what the built SPA needs: a single
same-origin module ``<script>`` and stylesheet (Vite output), same-origin
``fetch`` to ``/api/*``, inline styles from Tailwind-in-JS style attributes, and
``data:`` images. Tighten it if the frontend build stops needing
``style-src 'unsafe-inline'``.
"""

from __future__ import annotations

from typing import Any

from ladelaug_avregning.config import AppConfig

_CSP = (
    "default-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'"
)

_BASE_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-security-policy", _CSP.encode("latin-1")),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: Any, *, config: AppConfig) -> None:
        self.app = app
        headers = list(_BASE_HEADERS)
        if config.auth.cookie_secure:
            # Only meaningful once the app is actually served over HTTPS.
            headers.append(
                (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
            )
        self._headers = headers

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                raw = message.setdefault("headers", [])
                present = {key.lower() for key, _ in raw}
                for key, value in self._headers:
                    if key not in present:
                        raw.append((key, value))
            await send(message)

        await self.app(scope, receive, send_wrapper)
