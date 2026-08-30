"""SQLite access layer.

One connection, WAL mode, a single ``asyncio.Lock`` serialising every write. Read
queries go straight to the connection (WAL makes concurrent readers safe). Domain
repositories live under ``ladelaug_avregning.domain`` and take a ``Database``.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from ladelaug_avregning.migrations import run_migrations

_DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class Database:
    def __init__(self, path: str | Path, migrations_dir: str | Path | None = None) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = asyncio.Lock()
        run_migrations(self._conn, Path(migrations_dir or _DEFAULT_MIGRATIONS_DIR))

    @property
    def connection(self) -> sqlite3.Connection:
        """Read-only access. Do not mutate through this — use ``_write``."""
        return self._conn

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[sqlite3.Cursor]:
        """Serialise writes on the lock; commit on success, roll back on error."""
        async with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()
            finally:
                cur.close()

    def close(self) -> None:
        self._conn.close()
