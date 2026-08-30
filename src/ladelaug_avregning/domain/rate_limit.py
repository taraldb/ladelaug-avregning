"""Login rate limiting, backed by the ``login_attempts`` table.

Counts recent attempts for an ``(email, ip)`` pair. Once the window is full and
the most recent attempt was a failure, further tries are refused with a ``429``
*before* any argon2 work — so a password-guessing flood cannot also burn CPU.
Every attempt (success or failure) is recorded.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from ladelaug_avregning import clock
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import RateLimitError

_SWEEP_AGE = timedelta(hours=24)


class LoginRateLimiter:
    def __init__(self, db: Database, *, max_attempts: int, window_seconds: int) -> None:
        self._db = db
        self._max_attempts = max_attempts
        self._window = timedelta(seconds=window_seconds)

    def check(self, email_normalized: str, ip: str, *, now: datetime | None = None) -> None:
        now = now or clock.now_utc()
        window_start = (now - self._window).isoformat()
        rows = self._db.connection.execute(
            "SELECT succeeded, occurred_at FROM login_attempts "
            "WHERE email_normalized = ? AND ip = ? AND occurred_at >= ? "
            "ORDER BY occurred_at DESC",
            (email_normalized, ip, window_start),
        ).fetchall()
        if len(rows) < self._max_attempts or rows[0]["succeeded"]:
            return
        # The N-th most recent attempt leaves the window at occurred_at + window.
        blocking = rows[self._max_attempts - 1]
        try:
            frees_at = datetime.fromisoformat(blocking["occurred_at"]) + self._window
            retry_after = max(1, math.ceil((frees_at - now).total_seconds()))
        except ValueError:
            retry_after = math.ceil(self._window.total_seconds())
        raise RateLimitError(
            "Too many failed sign-in attempts. Try again later.", retry_after=retry_after
        )

    async def record(
        self, email_normalized: str, ip: str, *, succeeded: bool, now: datetime | None = None
    ) -> None:
        now = now or clock.now_utc()
        async with self._db._write() as cur:
            cur.execute(
                "INSERT INTO login_attempts (email_normalized, ip, occurred_at, succeeded) "
                "VALUES (?, ?, ?, ?)",
                (email_normalized, ip, now.isoformat(), 1 if succeeded else 0),
            )
            cur.execute(
                "DELETE FROM login_attempts WHERE occurred_at < ?",
                ((now - _SWEEP_AGE).isoformat(),),
            )
