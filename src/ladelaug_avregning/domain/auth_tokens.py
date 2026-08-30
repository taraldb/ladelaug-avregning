"""Single-use, expiring auth tokens: magic-link sign-in (US-102) and password
reset (US-103).

Only the SHA-256 of the token is stored (same scheme as sessions). Requesting a
new token of a kind invalidates the user's earlier unused ones of that kind, so
at most one link is ever live.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ladelaug_avregning import clock, security
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import DomainError

_KINDS = ("magic_link", "password_reset")


class AuthTokenRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def issue(self, *, user_id: int, kind: str, ttl_minutes: int, ip: str | None) -> str:
        if kind not in _KINDS:
            raise DomainError("bad_kind", f"kind must be one of {_KINDS}")
        token = security.new_session_token()
        now = clock.now_utc()
        expires = (now + timedelta(minutes=ttl_minutes)).isoformat()
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE auth_tokens SET used_at = ? "
                "WHERE user_id = ? AND kind = ? AND used_at IS NULL",
                (now.isoformat(), user_id, kind),
            )
            cur.execute(
                "INSERT INTO auth_tokens "
                "(user_id, kind, token_hash, created_at, expires_at, requested_ip) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, kind, security.hash_token(token), now.isoformat(), expires, ip),
            )
        return token

    async def consume(self, *, token: str, kind: str) -> int:
        """Validate and burn a token, returning its user_id. Raises DomainError
        (``invalid_token`` / ``expired_token``) on any problem — the caller
        should not disclose which."""
        token_hash = security.hash_token(token or "")
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            row = cur.execute(
                "SELECT * FROM auth_tokens WHERE token_hash = ? AND kind = ?",
                (token_hash, kind),
            ).fetchone()
            if row is None or row["used_at"] is not None:
                raise DomainError("invalid_token", "This link is invalid or has already been used.")
            if row["expires_at"] <= now:
                raise DomainError("expired_token", "This link has expired.", status=422)
            cur.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
            return int(row["user_id"])

    def recent_for_user(self, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT id, kind, created_at, expires_at, used_at FROM auth_tokens "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
