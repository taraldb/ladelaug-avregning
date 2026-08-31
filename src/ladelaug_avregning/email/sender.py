"""Email backends: ``console`` (log only), ``file`` (``.eml`` under
``state/mail/``), ``smtp`` (stdlib ``smtplib`` run off the event loop), and
``gmail`` (Gmail REST API, OAuth2 refresh token).

An ``EmailSender.send`` that raises leaves the message queued for retry; a clean
return marks it sent.
"""

from __future__ import annotations

import base64
import logging
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import anyio
import httpx

from ladelaug_avregning import clock
from ladelaug_avregning.config import EmailConfig

log = logging.getLogger(__name__)

_GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

_TOKEN_IN_URL = re.compile(r"([?#]token=)[A-Za-z0-9_-]+")


def _redact_tokens(text: str) -> str:
    """Blank out `?token=…` / `#token=…` so a live sign-in link is not left in
    the logs by the console backend."""
    return _TOKEN_IN_URL.sub(r"\1<redacted>", text)


def _build_message(
    cfg: EmailConfig, *, to: str, subject: str, text: str, html: str | None
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = clock.now_utc().strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg["Message-ID"] = make_msgid()
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


class EmailSender:
    def __init__(
        self,
        cfg: EmailConfig,
        *,
        state_dir: Path | str = "state",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = cfg
        self._state = Path(state_dir)
        # Injected for tests; otherwise a short-lived client is created per send.
        self._http = http
        self._gmail_token: str | None = None
        self._gmail_token_expiry: datetime | None = None

    async def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        backend = self._cfg.backend
        msg = _build_message(self._cfg, to=to, subject=subject, text=text, html=html)
        if backend == "console":
            log.info(
                "[email:console] to=%s subject=%s\n%s", to, subject, _redact_tokens(text)
            )
            return
        if backend == "file":
            await anyio.to_thread.run_sync(self._write_eml, to, msg)
            return
        if backend == "gmail":
            await self._gmail_send(msg)
            return
        await anyio.to_thread.run_sync(self._smtp_send, msg)

    def _write_eml(self, to: str, msg: EmailMessage) -> None:
        out = self._state / "mail"
        out.mkdir(parents=True, exist_ok=True)
        stamp = clock.now_utc().strftime("%Y%m%dT%H%M%S%f")
        safe = to.replace("@", "_at_").replace("/", "_")
        (out / f"{stamp}-{safe}.eml").write_bytes(bytes(msg))

    def _smtp_send(self, msg: EmailMessage) -> None:
        cfg = self._cfg
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            if cfg.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if cfg.smtp_username:
                smtp.login(cfg.smtp_username, cfg.smtp_password)
            smtp.send_message(msg)

    # --- gmail --------------------------------------------------------------

    async def _gmail_send(self, msg: EmailMessage) -> None:
        cfg = self._cfg
        sender = cfg.gmail_sender.strip() or cfg.from_address
        if msg["From"] != sender:
            del msg["From"]
            msg["From"] = sender
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        if self._http is not None:
            await self._gmail_post(self._http, raw)
        else:
            async with httpx.AsyncClient(timeout=30) as http:
                await self._gmail_post(http, raw)

    async def _gmail_post(self, http: httpx.AsyncClient, raw: str) -> None:
        token = await self._gmail_access_token(http)
        resp = await http.post(
            _GMAIL_SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 401:
            # Token rejected mid-flight — force one refresh and retry once.
            self._gmail_token = None
            token = await self._gmail_access_token(http)
            resp = await http.post(
                _GMAIL_SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"}
            )
        if resp.status_code >= 300:
            raise RuntimeError(f"Gmail send failed ({resp.status_code}): {resp.text[:500]}")

    async def _gmail_access_token(self, http: httpx.AsyncClient) -> str:
        now = clock.now_utc()
        if (
            self._gmail_token is not None
            and self._gmail_token_expiry is not None
            and now < self._gmail_token_expiry
        ):
            return self._gmail_token
        cfg = self._cfg
        try:
            resp = await http.post(
                _GMAIL_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": cfg.gmail_client_id,
                    "client_secret": cfg.gmail_client_secret,
                    "refresh_token": cfg.gmail_refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gmail token request failed: {exc}") from exc
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Gmail token refresh failed ({resp.status_code}): {resp.text[:500]}"
            )
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError("Gmail token response had no access_token")
        self._gmail_token = str(token)
        ttl = int(body.get("expires_in", 3600))
        self._gmail_token_expiry = now + timedelta(seconds=max(ttl - 60, 60))
        return self._gmail_token


def build_sender(
    cfg: EmailConfig,
    *,
    state_dir: Path | str = "state",
    http: httpx.AsyncClient | None = None,
) -> EmailSender:
    return EmailSender(cfg, state_dir=state_dir, http=http)
