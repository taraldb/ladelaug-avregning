"""Email backends: ``console`` (log only), ``file`` (``.eml`` under
``state/mail/``), and ``smtp`` (stdlib ``smtplib`` run off the event loop).

An ``EmailSender.send`` that raises leaves the message queued for retry; a clean
return marks it sent.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import anyio

from ladelaug_avregning import clock
from ladelaug_avregning.config import EmailConfig

log = logging.getLogger(__name__)


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
    def __init__(self, cfg: EmailConfig, *, state_dir: Path | str = "state") -> None:
        self._cfg = cfg
        self._state = Path(state_dir)

    async def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        backend = self._cfg.backend
        msg = _build_message(self._cfg, to=to, subject=subject, text=text, html=html)
        if backend == "console":
            log.info("[email:console] to=%s subject=%s\n%s", to, subject, text)
            return
        if backend == "file":
            await anyio.to_thread.run_sync(self._write_eml, to, msg)
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


def build_sender(cfg: EmailConfig, *, state_dir: Path | str = "state") -> EmailSender:
    return EmailSender(cfg, state_dir=state_dir)
