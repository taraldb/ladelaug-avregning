"""Outgoing email queue with retry/backoff (US-1001, US-1002).

Messages are enqueued in the same transaction as whatever triggered them, then
drained by ``process_queue`` (an admin endpoint / cron). A send failure bumps
``attempts`` and pushes ``next_attempt_at`` out; after ``max_attempts`` the row
goes ``failed`` and shows up in the system-health view (US-1104).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.db import Database
from ladelaug_avregning.email.sender import EmailSender

# minutes to wait before the Nth retry (index = attempts already made)
_BACKOFF_MINUTES = [1, 5, 15, 60, 240]


def _backoff(attempts: int) -> timedelta:
    idx = min(attempts, len(_BACKOFF_MINUTES) - 1)
    return timedelta(minutes=_BACKOFF_MINUTES[idx])


class NotificationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def enqueue(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        template: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: str | int | None = None,
        max_attempts: int = 5,
    ) -> int:
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "INSERT INTO email_messages "
                "(to_address, subject, body_text, body_html, template, related_entity_type, "
                " related_entity_id, status, attempts, max_attempts, next_attempt_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)",
                (
                    to_address,
                    subject,
                    body_text,
                    body_html,
                    template,
                    related_entity_type,
                    None if related_entity_id is None else str(related_entity_id),
                    max_attempts,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid or 0)

    async def process_queue(self, sender: EmailSender, *, limit: int = 50) -> dict[str, int]:
        now = clock.now_utc()
        due = self._db.connection.execute(
            "SELECT * FROM email_messages WHERE status = 'queued' AND next_attempt_at <= ? "
            "ORDER BY id LIMIT ?",
            (now.isoformat(), limit),
        ).fetchall()

        sent = failed = retried = 0
        for row in due:
            msg = dict(row)
            try:
                await sender.send(
                    to=msg["to_address"],
                    subject=msg["subject"],
                    text=msg["body_text"],
                    html=msg["body_html"],
                )
            except Exception as exc:  # noqa: BLE001 - any send failure is retryable
                attempts = int(msg["attempts"]) + 1
                if attempts >= int(msg["max_attempts"]):
                    await self._mark(msg["id"], status="failed", attempts=attempts, error=str(exc))
                    failed += 1
                else:
                    nxt = (now + _backoff(attempts)).isoformat()
                    await self._mark(
                        msg["id"],
                        status="queued",
                        attempts=attempts,
                        error=str(exc),
                        next_attempt_at=nxt,
                    )
                    retried += 1
            else:
                await self._mark(msg["id"], status="sent", attempts=int(msg["attempts"]) + 1)
                sent += 1
        return {"due": len(due), "sent": sent, "failed": failed, "retried": retried}

    async def _mark(
        self,
        message_id: int,
        *,
        status: str,
        attempts: int,
        error: str | None = None,
        next_attempt_at: str | None = None,
    ) -> None:
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE email_messages SET status = ?, attempts = ?, last_error = ?, "
                "next_attempt_at = COALESCE(?, next_attempt_at), "
                "sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END WHERE id = ?",
                (
                    status,
                    attempts,
                    error,
                    next_attempt_at,
                    status,
                    clock.now_utc().isoformat(),
                    message_id,
                ),
            )

    def stats(self) -> dict[str, Any]:
        rows = self._db.connection.execute(
            "SELECT status, COUNT(*) AS n FROM email_messages GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: int(r["n"]) for r in rows}
        nxt = self._db.connection.execute(
            "SELECT MIN(next_attempt_at) FROM email_messages WHERE status = 'queued'"
        ).fetchone()[0]
        return {
            "queued": by_status.get("queued", 0),
            "sent": by_status.get("sent", 0),
            "failed": by_status.get("failed", 0),
            "next_attempt_at": nxt,
        }

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT id, to_address, subject, template, related_entity_type, related_entity_id, "
            "status, attempts, max_attempts, last_error, next_attempt_at, created_at, sent_at "
            "FROM email_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def enqueue_settlement_reports(
        self, *, settlement_id: int, result: dict[str, Any], base_url: str
    ) -> int:
        """One report email per member with a linked, enabled user (US-1001)."""
        from ladelaug_avregning.domain.users import UserRepo

        users = UserRepo(self._db)
        month = result["period_month"]
        queued = 0
        for m in result["members"]:
            user = users.get_by_member_id(m["member_id"])
            if not user or user["disabled"] or not user["email"]:
                continue
            link = f"{base_url.rstrip('/')}/my-account"
            text = (
                f"Hei {m['full_name']},\n\n"
                f"Avregningen for {month} er klar. Din andel er {m['charge_nok']} kr, "
                f"og saldo etter avregning er {m['balance_after_nok']} kr.\n\n"
                f"Se detaljene i portalen: {link}\n"
            )
            await self.enqueue(
                to_address=user["email"],
                subject=f"Avregning {month}",
                body_text=text,
                template="settlement_report",
                related_entity_type="settlement",
                related_entity_id=settlement_id,
            )
            queued += 1
        return queued
