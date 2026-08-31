"""User accounts: the login identities behind both roles.

One row per person who can sign in. ``role`` is ``admin`` or ``member``;
``member_id`` links a ``member`` login to its member record (``NULL`` = a pure
administrator). Emails are stored as given but matched case-insensitively via
``email_normalized``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ladelaug_avregning import clock, security
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import sessions
from ladelaug_avregning.errors import DomainError, NotFoundError

Argon2Params = tuple[int, int, int]  # (time_cost, memory_cost_kib, parallelism)

_DEFAULT_ARGON2: Argon2Params = (
    security.DEFAULT_TIME_COST,
    security.DEFAULT_MEMORY_COST_KIB,
    security.DEFAULT_PARALLELISM,
)


def _strip_secret(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("password_hash", None)
    return row


class UserRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        email: str,
        password: str | None,
        role: str,
        member_id: int | None = None,
        actor: AuditContext,
        argon2: Argon2Params = _DEFAULT_ARGON2,
    ) -> int:
        """Create a login. ``password=None`` leaves ``password_hash`` NULL — the
        account can only be entered via a magic link or a password-reset."""
        if role not in ("admin", "member"):
            raise DomainError("bad_role", f"role must be 'admin' or 'member', not {role!r}")
        email = email.strip()
        email_normalized = email.lower()
        now = clock.now_utc().isoformat()
        if password is None:
            password_hash = None
            password_changed_at = None
        else:
            time_cost, memory_cost, parallelism = argon2
            password_hash = security.hash_password(
                password, time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
            )
            password_changed_at = now

        async with self._db._write() as cur:
            try:
                cur.execute(
                    "INSERT INTO users "
                    "(email, email_normalized, password_hash, role, disabled, member_id, "
                    " password_changed_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                    (
                        email,
                        email_normalized,
                        password_hash,
                        role,
                        member_id,
                        password_changed_at,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "email_normalized" in str(exc):
                    raise DomainError(
                        "email_taken", "An account with that email already exists."
                    ) from exc
                if "member_id" in str(exc):
                    raise DomainError("member_linked", "That member already has a login.") from exc
                raise
            user_id = int(cur.lastrowid or 0)
            write_audit_row(
                cur,
                actor,
                event_type="user.created",
                entity_type="user",
                entity_id=user_id,
                summary=f"User {email} created ({role})",
                detail={"role": role, "member_id": member_id},
            )
            return user_id

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM users WHERE email_normalized = ?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None

    def get(self, user_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_by_member_id(self, member_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM users WHERE member_id = ?", (member_id,)
        ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self._db.connection.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
        return [_strip_secret(dict(r)) for r in rows]

    async def set_disabled(self, user_id: int, disabled: bool, *, actor: AuditContext) -> None:
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE users SET disabled = ?, updated_at = ? WHERE id = ?",
                (1 if disabled else 0, now, user_id),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"user {user_id} not found")
            if disabled:
                sessions.revoke_all_for_user_rows(cur, user_id, now)
            write_audit_row(
                cur,
                actor,
                event_type="user.disabled" if disabled else "user.enabled",
                entity_type="user",
                entity_id=user_id,
                summary=f"User {user_id} {'disabled' if disabled else 're-enabled'}",
            )

    async def set_password(
        self,
        user_id: int,
        password: str,
        *,
        actor: AuditContext,
        argon2: Argon2Params = _DEFAULT_ARGON2,
    ) -> None:
        time_cost, memory_cost, parallelism = argon2
        password_hash = security.hash_password(
            password, time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
        )
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE users SET password_hash = ?, password_changed_at = ?, updated_at = ? "
                "WHERE id = ?",
                (password_hash, now, now, user_id),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"user {user_id} not found")
            write_audit_row(
                cur,
                actor,
                event_type="user.password_changed",
                entity_type="user",
                entity_id=user_id,
                summary=f"Password changed for user {user_id}",
            )
