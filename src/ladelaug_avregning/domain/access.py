"""Charging-access status (US-305) + its member notifications (US-1003 / US-1004).

An admin records an intent — ``warned``, ``disabled`` or ``restored`` — against a
member. Each is one ``charging_access_events`` row and one audit event; the
``warned`` and ``restored`` actions also enqueue a Norwegian email to the member.

This is a **status of record**: Release 1D does not call Zaptec to actually pause
or authorise a charger (that is the Release 2 "Direct Zaptec access control"
item). The member can keep charging until an admin acts in the Zaptec portal —
the portal link travels in the email and the portal banner.
"""

from __future__ import annotations

from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.notifications import _member_email
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import DomainError, NotFoundError

_ACTIONS = ("warned", "disabled", "restored")

_SUBJECT = {
    "warned": "Varsel: ladetilgangen din kan bli stengt",
    "restored": "Ladetilgangen din er gjenåpnet",
}


def _email_body(action: str, reason: str | None, portal_url: str | None) -> str:
    if action == "warned":
        lines = [
            "Hei,",
            "",
            "Ladelauget varsler at ladetilgangen din kan bli stengt.",
        ]
        if reason:
            lines.append(f"Årsak: {reason}")
        lines += [
            "Ta kontakt med styret for å unngå at tilgangen blir stengt.",
        ]
    else:  # restored
        lines = ["Hei,", "", "Ladetilgangen din er gjenåpnet. Du kan lade som normalt igjen."]
        if reason:
            lines.append(f"Merknad: {reason}")
    if portal_url:
        lines += ["", f"Zaptec-portal: {portal_url}"]
    return "\n".join(lines) + "\n"


class AccessRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- reads -----------------------------------------------------------

    def current(self, member_id: int) -> str | None:
        row = self._db.connection.execute(
            "SELECT action FROM charging_access_events WHERE member_id = ? ORDER BY id DESC LIMIT 1",
            (member_id,),
        ).fetchone()
        return row["action"] if row else None

    def history(self, member_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM charging_access_events WHERE member_id = ? ORDER BY id DESC",
            (member_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def status_map(self) -> dict[int, str]:
        """member_id -> latest access action, for every member that has any."""
        rows = self._db.connection.execute(
            "SELECT member_id, action FROM charging_access_events e "
            "WHERE id = (SELECT MAX(id) FROM charging_access_events WHERE member_id = e.member_id)"
        ).fetchall()
        return {int(r["member_id"]): r["action"] for r in rows}

    def disabled_count(self) -> int:
        return sum(1 for a in self.status_map().values() if a == "disabled")

    # --- mutation ------------------------------------------------------

    async def record(
        self,
        member_id: int,
        action: str,
        *,
        reason: str | None = None,
        note: str | None = None,
        portal_url: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        if action not in _ACTIONS:
            raise DomainError("bad_action", f"action must be one of {_ACTIONS}")
        if MemberRepo(self._db).get(member_id) is None:
            raise NotFoundError(f"member {member_id} not found")

        reason = (reason or "").strip() or None
        note = (note or "").strip() or None
        now = clock.now_utc().isoformat()
        to_address = (
            _member_email(member_id, UserRepo(self._db), MemberRepo(self._db))
            if action in ("warned", "restored")
            else None
        )

        async with self._db._write() as cur:
            email_id: int | None = None
            if to_address and action in _SUBJECT:
                cur.execute(
                    "INSERT INTO email_messages "
                    "(to_address, subject, body_text, body_html, template, related_entity_type, "
                    " related_entity_id, status, attempts, max_attempts, next_attempt_at, "
                    " created_at) "
                    "VALUES (?, ?, ?, NULL, ?, 'member', ?, 'queued', 0, 5, ?, ?)",
                    (
                        to_address,
                        _SUBJECT[action],
                        _email_body(action, reason, portal_url),
                        f"access_{action}",
                        str(member_id),
                        now,
                        now,
                    ),
                )
                email_id = int(cur.lastrowid or 0)

            cur.execute(
                "INSERT INTO charging_access_events "
                "(member_id, action, reason, note, created_at, created_by_user_id, "
                " email_message_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (member_id, action, reason, note, now, actor.actor_user_id, email_id),
            )
            event_id = int(cur.lastrowid or 0)
            write_audit_row(
                cur,
                actor,
                event_type=f"access.{action}",
                entity_type="member",
                entity_id=member_id,
                summary=f"Charging access for member {member_id}: {action}"
                + (f" ({reason})" if reason else ""),
                detail={
                    "member_id": member_id,
                    "action": action,
                    "reason": reason,
                    "note": note,
                    "email_message_id": email_id,
                },
            )
        return dict(
            self._db.connection.execute(
                "SELECT * FROM charging_access_events WHERE id = ?", (event_id,)
            ).fetchone()
        )
