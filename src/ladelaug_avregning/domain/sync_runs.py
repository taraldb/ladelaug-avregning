"""Sync-run bookkeeping (US-403 / US-1104).

Every Zaptec sync writes one ``sync_runs`` row — kind, status, window, counts,
and any error — so the admin health view can show "last chargers sync: ok,
2 min ago" and surface failures.
"""

from __future__ import annotations

from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.db import Database


class SyncRunRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        kind: str,
        status: str,
        started_at: str,
        window_from: str | None = None,
        window_to: str | None = None,
        items_seen: int = 0,
        items_imported: int = 0,
        error: str | None = None,
        created_by_user_id: int | None = None,
    ) -> int:
        async with self._db._write() as cur:
            cur.execute(
                "INSERT INTO sync_runs "
                "(kind, status, started_at, finished_at, window_from, window_to, "
                " items_seen, items_imported, error, created_by_user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    status,
                    started_at,
                    clock.now_utc().isoformat(),
                    window_from,
                    window_to,
                    items_seen,
                    items_imported,
                    error,
                    created_by_user_id,
                ),
            )
            return int(cur.lastrowid or 0)

    def latest(self, kind: str) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM sync_runs WHERE kind = ? ORDER BY started_at DESC, id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        return dict(row) if row else None

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def failure_count(self) -> int:
        return int(
            self._db.connection.execute(
                "SELECT COUNT(*) FROM sync_runs WHERE status = 'error'"
            ).fetchone()[0]
        )
