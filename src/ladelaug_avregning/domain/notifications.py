"""Outgoing email queue with retry/backoff (US-1001, US-1002).

Messages are enqueued in the same transaction as whatever triggered them, then
drained by ``process_queue`` (an admin endpoint / cron). A send failure bumps
``attempts`` and pushes ``next_attempt_at`` out; after ``max_attempts`` the row
goes ``failed`` and shows up in the system-health view (US-1104).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.email.sender import EmailSender
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import ore_to_nok

# a warning is re-sent inside the cooldown window if the balance drops by at
# least this many øre, or the severity escalates from 'low' to 'critical'
_BALANCE_DROP_RESEND_ORE = 100

# minutes to wait before the Nth retry (index = attempts already made)
_BACKOFF_MINUTES = [1, 5, 15, 60, 240]

# columns returned by recent() / get() — the row shape the admin UI renders
_MESSAGE_COLUMNS = (
    "id, to_address, subject, template, related_entity_type, related_entity_id, "
    "status, attempts, max_attempts, last_error, next_attempt_at, created_at, sent_at"
)


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

        tally = {"sent": 0, "failed": 0, "retried": 0}
        for row in due:
            tally[await self._attempt(dict(row), sender, now)] += 1
        return {"due": len(due), **tally}

    async def _attempt(self, msg: dict[str, Any], sender: EmailSender, now: datetime) -> str:
        """Try to deliver one row and record the outcome. Returns ``"sent"``,
        ``"failed"`` (gave up after ``max_attempts``), or ``"retried"`` (queued
        again with backoff). A send failure never propagates."""
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
                return "failed"
            nxt = (now + _backoff(attempts)).isoformat()
            await self._mark(
                msg["id"],
                status="queued",
                attempts=attempts,
                error=str(exc),
                next_attempt_at=nxt,
            )
            return "retried"
        await self._mark(msg["id"], status="sent", attempts=int(msg["attempts"]) + 1)
        return "sent"

    async def send_now(self, sender: EmailSender, *, message_id: int) -> str:
        """Attempt an immediate delivery of one still-``queued`` row, for
        latency-sensitive callers (the magic-link / password-reset endpoints).
        Returns ``"sent"`` / ``"retried"`` / ``"failed"`` like :meth:`_attempt`,
        or ``"skipped"`` when the row is gone or no longer queued. A send failure
        leaves the row queued for ``process_queue`` exactly as normal — this
        never raises for a delivery error."""
        row = self._db.connection.execute(
            "SELECT * FROM email_messages WHERE id = ? AND status = 'queued'", (message_id,)
        ).fetchone()
        if row is None:
            return "skipped"
        return await self._attempt(dict(row), sender, clock.now_utc())

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
            f"SELECT {_MESSAGE_COLUMNS} FROM email_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, message_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM email_messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    async def requeue(self, message_id: int, *, actor: AuditContext) -> dict[str, Any]:
        """Put a single ``failed`` or ``sent`` message back on the queue: reset
        its attempt counter and make it due now. Writes one
        ``notifications.email_requeued`` audit row in the same transaction. A
        message that is already ``queued`` raises ``not_requeueable``."""
        current = self.get(message_id)
        if current is None:
            raise NotFoundError(f"email message {message_id} not found")
        if current["status"] not in ("failed", "sent"):
            raise DomainError(
                "not_requeueable",
                "Only a failed or sent email can be put back on the queue.",
            )
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE email_messages SET status = 'queued', attempts = 0, last_error = NULL, "
                "sent_at = NULL, next_attempt_at = ? WHERE id = ?",
                (now, message_id),
            )
            write_audit_row(
                cur,
                actor,
                event_type="notifications.email_requeued",
                entity_type="email_message",
                entity_id=message_id,
                summary=(f"Email {message_id} to {current['to_address']} put back on the queue"),
                detail={
                    "previous_status": current["status"],
                    "to_address": current["to_address"],
                    "template": current["template"],
                },
            )
        refreshed = self.get(message_id)
        assert refreshed is not None
        return refreshed

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

    async def enqueue_correction_reports(
        self, *, settlement_id: int, correction: dict[str, Any], base_url: str
    ) -> int:
        """One email per adjusted member with a linked, enabled user (US-703):
        the correction delta (kr tilbakeført / kr ekstra), the new balance, and
        a portal link."""
        from ladelaug_avregning.domain.ledger import LedgerRepo
        from ladelaug_avregning.domain.users import UserRepo

        users = UserRepo(self._db)
        ledger = LedgerRepo(self._db)
        month = correction["period_month"]
        seq = correction["sequence"]
        link = f"{base_url.rstrip('/')}/my-account"
        queued = 0
        for m in correction["members"]:
            if int(m["delta_ore"]) == 0:
                continue
            user = users.get_by_member_id(m["member_id"])
            if not user or user["disabled"] or not user["email"]:
                continue
            delta_ore = int(m["delta_ore"])
            balance_nok = ore_to_nok(ledger.balance_ore(m["member_id"]))
            if delta_ore > 0:
                movement = f"Du får {ore_to_nok(delta_ore)} kr tilbakeført."
            else:
                movement = f"Du blir belastet {ore_to_nok(-delta_ore)} kr ekstra."
            text = (
                f"Hei {m['full_name']},\n\n"
                f"Avregningen for {month} er korrigert (korrigering #{seq}). "
                f"{movement}\n"
                f"Ny saldo er {balance_nok} kr.\n\n"
                f"Se detaljene i portalen: {link}\n"
            )
            await self.enqueue(
                to_address=user["email"],
                subject=f"Korrigert avregning {month}",
                body_text=text,
                template="settlement_correction",
                related_entity_type="settlement",
                related_entity_id=settlement_id,
            )
            queued += 1
        return queued

    async def scan_low_balances(self, *, actor: AuditContext) -> dict[str, int]:
        """Enqueue a Norwegian low-balance warning for every member whose forecast
        says ``low_balance`` (US-805), skipping members whose forecast is not
        ``available`` and applying the decision-C6 suppression rule. Each send
        writes one ``low_balance_notifications`` row (linked to the queued
        ``email_messages`` id) and one ``notifications.low_balance_warned`` audit
        event in the same locked transaction. Idempotent within the cooldown
        window — safe to run hourly from cron."""
        from ladelaug_avregning.domain.forecast import ForecastRepo
        from ladelaug_avregning.domain.members import MemberRepo
        from ladelaug_avregning.domain.users import UserRepo

        forecast_repo = ForecastRepo(self._db)
        cooldown_days = int(forecast_repo.settings()["notify_cooldown_days"])
        members = MemberRepo(self._db)
        users = UserRepo(self._db)
        now = clock.now_utc()

        scanned = below = queued = suppressed = 0
        for fc in forecast_repo.all_member_forecasts():
            if not fc["available"]:
                continue
            scanned += 1
            if not fc["low_balance"]:
                continue
            below += 1

            member_id = int(fc["member_id"])
            last = self._db.connection.execute(
                "SELECT severity, balance_ore, created_at FROM low_balance_notifications "
                "WHERE member_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (member_id,),
            ).fetchone()
            trigger = _warn_trigger(fc, last, now, cooldown_days)
            if trigger is None:
                suppressed += 1
                continue

            to_address = _member_email(member_id, users, members)
            if not to_address:
                suppressed += 1
                continue

            await self._enqueue_low_balance_warning(
                member_id=member_id,
                to_address=to_address,
                forecast=fc,
                trigger=trigger,
                actor=actor,
            )
            queued += 1

        return {"scanned": scanned, "below": below, "queued": queued, "suppressed": suppressed}

    async def _enqueue_low_balance_warning(
        self,
        *,
        member_id: int,
        to_address: str,
        forecast: dict[str, Any],
        trigger: str,
        actor: AuditContext,
    ) -> None:
        severity = forecast["severity"]
        balance_ore = int(forecast["balance_ore"])
        minimum_ore = int(forecast["recommended_minimum_ore"])
        cost_ore = int(forecast["forecast_monthly_cost_ore"])
        topup_ore = int(forecast["recommended_topup_ore"])
        now = clock.now_utc().isoformat()

        lines = [
            "Hei,",
            "",
            f"Saldoen din i ladelauget er lav: {ore_to_nok(balance_ore)} kr.",
            f"Anbefalt minstesaldo er {ore_to_nok(minimum_ore)} kr.",
            f"Vi anbefaler at du betaler inn minst {ore_to_nok(topup_ore)} kr.",
        ]
        if severity == "critical":
            lines.append(
                f"Saldoen dekker ikke neste måneds forventede kostnad på {ore_to_nok(cost_ore)} kr."
            )
        lines += ["", "Logg inn på Min konto i portalen for detaljer."]
        body_text = "\n".join(lines) + "\n"
        subject = "Varsel: lav saldo på ladelaugskontoen din"

        async with self._db._write() as cur:
            cur.execute(
                "INSERT INTO email_messages "
                "(to_address, subject, body_text, body_html, template, related_entity_type, "
                " related_entity_id, status, attempts, max_attempts, next_attempt_at, created_at) "
                "VALUES (?, ?, ?, NULL, 'low_balance_warning', 'member', ?, 'queued', 0, 5, ?, ?)",
                (to_address, subject, body_text, str(member_id), now, now),
            )
            email_id = int(cur.lastrowid or 0)
            cur.execute(
                "INSERT INTO low_balance_notifications "
                "(member_id, severity, balance_ore, recommended_minimum_ore, "
                " forecast_monthly_cost_ore, email_message_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (member_id, severity, balance_ore, minimum_ore, cost_ore, email_id, now),
            )
            write_audit_row(
                cur,
                actor,
                event_type="notifications.low_balance_warned",
                entity_type="member",
                entity_id=member_id,
                summary=(
                    f"Low-balance warning ({severity}) queued for member {member_id}: "
                    f"balance {ore_to_nok(balance_ore)} kr < minimum {ore_to_nok(minimum_ore)} kr"
                ),
                detail={
                    "member_id": member_id,
                    "severity": severity,
                    "trigger": trigger,
                    "balance_ore": balance_ore,
                    "recommended_minimum_ore": minimum_ore,
                    "forecast_monthly_cost_ore": cost_ore,
                    "email_message_id": email_id,
                },
            )


def _warn_trigger(
    forecast: dict[str, Any],
    last: Any,
    now: datetime,
    cooldown_days: int,
) -> str | None:
    """Return why a warning should be (re-)sent, or ``None`` to suppress it
    (decision C6): send when there is no prior row within the cooldown window,
    OR the balance dropped by >= 100 øre since the last row, OR the severity
    escalated from 'low' to 'critical'."""
    if last is None:
        return "first_warning"
    last_at = datetime.fromisoformat(last["created_at"])
    if now - last_at >= timedelta(days=cooldown_days):
        return "cooldown_elapsed"
    if int(last["balance_ore"]) - int(forecast["balance_ore"]) >= _BALANCE_DROP_RESEND_ORE:
        return "balance_dropped"
    if last["severity"] == "low" and forecast["severity"] == "critical":
        return "severity_escalated"
    return None


def _member_email(member_id: int, users: Any, members: Any) -> str | None:
    """The member's linked, enabled portal account email, else their own
    ``members.email``."""
    user = users.get_by_member_id(member_id)
    if user and not user["disabled"] and user["email"]:
        return str(user["email"])
    member = members.get(member_id)
    if member and member["email"]:
        return str(member["email"])
    return None
