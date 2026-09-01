"""Server-side sessions.

A login mints an opaque 256-bit token that lives only in the client cookie; the
server stores ``sha256(token)`` as the ``sessions`` primary key. A session is
valid while it is un-revoked and un-expired. Expiry slides forward on activity
(throttled), so an active user stays signed in; logout and user-disable revoke
immediately.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ladelaug_avregning import clock, security
from ladelaug_avregning.db import Database

_TOUCH_THROTTLE = timedelta(minutes=5)


def revoke_all_for_user_rows(cur: sqlite3.Cursor, user_id: int, now: str) -> None:
    """Revoke every live session for a user on an existing cursor (no commit)."""
    cur.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (now, user_id),
    )


class SessionRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, *, user_id: int, ttl_hours: int, ip: str | None, user_agent: str | None
    ) -> str:
        token = security.new_session_token()
        now = clock.now_utc()
        now_iso = now.isoformat()
        expires_iso = (now + timedelta(hours=ttl_hours)).isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "INSERT INTO sessions "
                "(id, user_id, created_at, expires_at, last_seen_at, revoked_at, ip, user_agent) "
                "VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    security.hash_token(token),
                    user_id,
                    now_iso,
                    expires_iso,
                    now_iso,
                    ip,
                    user_agent,
                ),
            )
        return token

    def get_valid(self, token: str) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM sessions WHERE id = ? AND revoked_at IS NULL AND expires_at > ?",
            (security.hash_token(token), clock.now_utc().isoformat()),
        ).fetchone()
        return dict(row) if row else None

    async def touch(self, token: str, *, ttl_hours: int) -> None:
        """Slide expiry and bump last_seen_at, at most once per throttle window."""
        session_id = security.hash_token(token)
        row = self._db.connection.execute(
            "SELECT last_seen_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return
        now = clock.now_utc()
        try:
            last_seen = datetime.fromisoformat(row["last_seen_at"])
        except ValueError:
            last_seen = None
        if last_seen is not None and now - last_seen < _TOUCH_THROTTLE:
            return
        expires_iso = (now + timedelta(hours=ttl_hours)).isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE sessions SET last_seen_at = ?, expires_at = ? "
                "WHERE id = ? AND revoked_at IS NULL",
                (now.isoformat(), expires_iso, session_id),
            )

    async def revoke(self, token: str) -> None:
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (clock.now_utc().isoformat(), security.hash_token(token)),
            )

    async def revoke_all_for_user(self, user_id: int) -> None:
        async with self._db._write() as cur:
            revoke_all_for_user_rows(cur, user_id, clock.now_utc().isoformat())

    async def revoke_all_for_user_except(self, user_id: int, keep_token: str) -> None:
        """Revoke every live session for the user apart from the one holding
        ``keep_token`` — used when a member changes their own password so other
        devices are signed out but the current one stays put."""
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE sessions SET revoked_at = ? "
                "WHERE user_id = ? AND revoked_at IS NULL AND id != ?",
                (clock.now_utc().isoformat(), user_id, security.hash_token(keep_token)),
            )
