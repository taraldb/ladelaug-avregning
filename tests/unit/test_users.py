from __future__ import annotations

import pytest
import yaml

from ladelaug_avregning import security
from ladelaug_avregning.__main__ import _bootstrap_admin, main
from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import DomainError
from tests.conftest import FAST_ARGON2, MIGRATIONS_DIR


def _audit(db, event_type):
    return db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = ?", (event_type,)
    ).fetchall()


async def test_create_writes_user_and_audit_row(db):
    repo = UserRepo(db)
    uid = await repo.create(
        email="Admin@Example.com",
        password="changeme123",
        role="admin",
        actor=AuditContext.system(),
        argon2=FAST_ARGON2,
    )

    row = repo.get(uid)
    assert row["role"] == "admin"
    assert row["email"] == "Admin@Example.com"
    assert row["email_normalized"] == "admin@example.com"
    assert row["disabled"] == 0
    assert row["password_changed_at"] is not None
    assert security.verify_password(row["password_hash"], "changeme123")

    events = _audit(db, "user.created")
    assert len(events) == 1
    assert events[0]["actor_label"] == "system"
    assert events[0]["entity_id"] == str(uid)


async def test_duplicate_email_is_case_insensitive(db):
    repo = UserRepo(db)
    await repo.create(
        email="admin@example.com",
        password="changeme123",
        role="admin",
        actor=AuditContext.system(),
        argon2=FAST_ARGON2,
    )
    with pytest.raises(DomainError) as excinfo:
        await repo.create(
            email="ADMIN@Example.com",
            password="changeme123",
            role="admin",
            actor=AuditContext.system(),
            argon2=FAST_ARGON2,
        )
    assert excinfo.value.code == "email_taken"


async def test_set_disabled_revokes_sessions_and_audits(db):
    repo = UserRepo(db)
    uid = await repo.create(
        email="a@b.no",
        password="changeme123",
        role="admin",
        actor=AuditContext.system(),
        argon2=FAST_ARGON2,
    )
    token = await SessionRepo(db).create(user_id=uid, ttl_hours=1, ip="x", user_agent="y")
    assert SessionRepo(db).get_valid(token) is not None

    await repo.set_disabled(uid, True, actor=AuditContext.system())

    assert repo.get(uid)["disabled"] == 1
    assert SessionRepo(db).get_valid(token) is None
    assert len(_audit(db, "user.disabled")) == 1


def test_bootstrap_admin_runs_once(config):
    config.bootstrap_admin.email = "boot@example.com"
    config.bootstrap_admin.password = "changeme123"

    _bootstrap_admin(config)
    _bootstrap_admin(config)  # users table now non-empty -> no-op

    sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
    try:
        count = sep.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = sep.connection.execute("SELECT role FROM users").fetchone()[0]
    finally:
        sep.close()
    assert count == 1
    assert role == "admin"


@pytest.fixture
def config_file(config, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump()))
    return path


def test_create_admin_cli_inserts_and_then_reports_conflict(config_file, config, capsys):
    rc = main(
        [
            "--config",
            str(config_file),
            "create-admin",
            "--email",
            "cli@example.com",
            "--password",
            "changeme123",
        ]
    )
    assert rc == 0
    assert "Created admin cli@example.com" in capsys.readouterr().out

    sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
    try:
        assert (
            sep.connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='user.created'"
            ).fetchone()[0]
            == 1
        )
    finally:
        sep.close()

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--config",
                str(config_file),
                "create-admin",
                "--email",
                "CLI@example.com",
                "--password",
                "changeme123",
            ]
        )
    assert excinfo.value.code == 1
    assert "already exists" in capsys.readouterr().err
