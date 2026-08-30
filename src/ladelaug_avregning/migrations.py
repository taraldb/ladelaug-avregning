"""Forward-only SQL migration runner.

Each ``migrations/NNNN_description.sql`` file is applied once, in numeric order,
inside a single transaction, and its version recorded in ``schema_migrations``.
There are no down migrations: the rollback story is "restore the state/ backup".
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_FILENAME_RE = re.compile(r"^(\d{4})_.+\.sql$")


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        m = _FILENAME_RE.match(path.name)
        if m:
            found.append((int(m.group(1)), path))
    return found


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> list[int]:
    """Apply any unapplied migrations. Returns the versions applied this call.

    ``executescript`` ignores ``isolation_level`` and any pending transaction,
    so atomicity is enforced by wrapping each file's statements in an explicit
    ``BEGIN``/``COMMIT`` and rolling back on error.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    newly: list[int] = []

    for version, path in _discover(Path(migrations_dir)):
        if version in applied:
            continue
        body = path.read_text(encoding="utf-8")
        script = (
            "BEGIN;\n"
            f"{body}\n"
            "INSERT INTO schema_migrations (version, applied_at) "
            f"VALUES ({version}, '{datetime.now(UTC).isoformat()}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            conn.rollback()
            raise
        newly.append(version)

    return newly
