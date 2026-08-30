"""Shared test fixtures.

``db`` and the web ``client`` share one SQLite file so a test can drive the app
over HTTP and then inspect rows directly. Anything that needs to *write* async
repo state as setup goes through a throwaway ``Database`` on the same path
(``seed_*`` fixtures) so the app connection's ``asyncio.Lock`` is never bound to
a short-lived event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.domain.users import UserRepo

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

# argon2 tuned right down — these tests hash a lot and don't care about strength.
FAST_ARGON2 = (1, 8192, 1)


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "server": {"static_dir": str(tmp_path / "no-frontend")},
            "database": {"path": str(tmp_path / "app.db")},
            "logging": {"level": "WARNING"},
            "auth": {
                "secret_key": "test-secret",
                "cookie_secure": False,
                "session_ttl_hours": 720,
                "login_max_attempts": 5,
                "login_window_seconds": 900,
                "argon2_time_cost": FAST_ARGON2[0],
                "argon2_memory_cost_kib": FAST_ARGON2[1],
                "argon2_parallelism": FAST_ARGON2[2],
            },
        }
    )


@pytest.fixture
def db(config: AppConfig) -> Iterator[Database]:
    database = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def client(config: AppConfig, db: Database) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from ladelaug_avregning.webapp.app import create_app

    with TestClient(create_app(config, db)) as test_client:
        yield test_client


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def seed_user_sync(config: AppConfig) -> Callable[..., int]:
    """Create a user via a throwaway Database on the same file. Returns its id."""

    def _make(
        *,
        email: str,
        password: str = "changeme123",
        role: str = "admin",
        member_id: int | None = None,
        disabled: bool = False,
    ) -> int:
        sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)

        async def _seed() -> int:
            repo = UserRepo(sep)
            uid = await repo.create(
                email=email,
                password=password,
                role=role,
                member_id=member_id,
                actor=AuditContext.system(),
                argon2=FAST_ARGON2,
            )
            if disabled:
                await repo.set_disabled(uid, True, actor=AuditContext.system())
            return uid

        try:
            return _run(_seed())
        finally:
            sep.close()

    return _make


@pytest.fixture
def seed_member_sync(config: AppConfig) -> Callable[..., int]:
    """Insert a bare ``members`` row (MemberRepo arrives in Phase C). Returns id."""

    def _make(
        *, reference: str = "M-1", full_name: str = "Test Member", email: str = "m@example.com"
    ) -> int:
        sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
        try:
            now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
            conn = sep.connection
            cur = conn.execute(
                "INSERT INTO members "
                "(member_reference, full_name, email, join_date, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (reference, full_name, email, "2026-01-01", now, now),
            )
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            sep.close()

    return _make


@pytest.fixture
def make_session(config: AppConfig) -> Callable[..., str]:
    """Mint a session for a user id via a throwaway Database. Returns the raw token."""

    def _make(user_id: int, *, ttl_hours: int = 720) -> str:
        sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
        try:
            return _run(
                SessionRepo(sep).create(
                    user_id=user_id, ttl_hours=ttl_hours, ip="test", user_agent="pytest"
                )
            )
        finally:
            sep.close()

    return _make


@pytest.fixture
def make_member(config: AppConfig) -> Callable[..., int]:
    """Create a member via MemberRepo on a throwaway Database. Returns the id."""

    def _make(
        *,
        member_reference: str = "M-1",
        full_name: str = "Test Member",
        email: str | None = "m@example.com",
        join_date: str = "2026-01-01",
    ) -> int:
        sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
        try:
            row = _run(
                MemberRepo(sep).create(
                    member_reference=member_reference,
                    full_name=full_name,
                    email=email,
                    join_date=join_date,
                    actor=AuditContext.system(),
                )
            )
            return int(row["id"])
        finally:
            sep.close()

    return _make


@pytest.fixture
def admin_client(
    client: Any,
    config: AppConfig,
    seed_user_sync: Callable[..., int],
    make_session: Callable[..., str],
) -> Any:
    uid = seed_user_sync(email="admin@example.com", role="admin")
    client.cookies.set(config.auth.cookie_name, make_session(uid))
    return client


@pytest.fixture
def member_client(
    client: Any,
    config: AppConfig,
    seed_user_sync: Callable[..., int],
    seed_member_sync: Callable[..., int],
    make_session: Callable[..., str],
) -> Any:
    member_id = seed_member_sync(reference="M-100", email="kari@example.com")
    uid = seed_user_sync(email="kari@example.com", role="member", member_id=member_id)
    client.cookies.set(config.auth.cookie_name, make_session(uid))
    return client


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> dict[str, datetime]:
    """Freeze ``clock.now_utc``. Mutate ``holder['now']`` to advance time."""
    holder = {"now": datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)}
    monkeypatch.setattr("ladelaug_avregning.clock.now_utc", lambda: holder["now"])
    return holder
