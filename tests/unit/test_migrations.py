import sqlite3

import pytest

from ladelaug_avregning.db import Database
from ladelaug_avregning.migrations import run_migrations
from tests.conftest import MIGRATIONS_DIR

EXPECTED_TABLES = {
    "schema_migrations",
    "users",
    "sessions",
    "login_attempts",
    "members",
    "member_status_periods",
    "settlement_participation",
    "ledger_transactions",
    "audit_events",
}


def _names(conn, kind):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def test_all_tables_and_indexes_created(db: Database):
    tables = _names(db.connection, "table")
    assert EXPECTED_TABLES <= tables

    indexes = _names(db.connection, "index")
    for expected in (
        "idx_users_email_normalized",
        "idx_msp_one_open",
        "idx_sp_one_open",
        "idx_ledger_one_reversal",
        "idx_audit_type_time",
    ):
        assert expected in indexes


def test_foreign_keys_enabled(db: Database):
    assert db.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_rerun_is_noop(db: Database):
    assert run_migrations(db.connection, MIGRATIONS_DIR) == []
    applied = [
        r[0]
        for r in db.connection.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    on_disk = sorted(int(p.name[:4]) for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert applied == on_disk
    assert applied[0] == 1


def _seed_member_and_ledger(conn):
    conn.execute(
        "INSERT INTO members (member_reference, full_name, join_date, created_at, updated_at) "
        "VALUES ('A-1', 'Test', '2026-01-01', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00')"
    )
    member_id = conn.execute("SELECT id FROM members").fetchone()[0]
    conn.execute(
        "INSERT INTO ledger_transactions "
        "(member_id, txn_type, amount_ore, amount_nok, value_date, recorded_at) "
        "VALUES (?, 'payment', 10000, '100.00', '2026-01-01', "
        "'2026-01-01T00:00:00+00:00')",
        (member_id,),
    )
    conn.commit()
    return member_id


def test_ledger_is_append_only(db: Database):
    _seed_member_and_ledger(db.connection)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE ledger_transactions SET amount_ore = 0")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM ledger_transactions")


def test_audit_is_append_only(db: Database):
    db.connection.execute(
        "INSERT INTO audit_events "
        "(occurred_at, actor_label, event_type, entity_type, summary) "
        "VALUES ('2026-01-01T00:00:00+00:00', 'system', 'x.y', 'thing', 'hi')"
    )
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE audit_events SET summary = 'no'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM audit_events")


def test_one_open_status_period_per_member(db: Database):
    member_id = _seed_member_and_ledger(db.connection)
    db.connection.execute(
        "INSERT INTO member_status_periods "
        "(member_id, status, effective_from, created_at) "
        "VALUES (?, 'active', '2026-01-01', '2026-01-01T00:00:00+00:00')",
        (member_id,),
    )
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO member_status_periods "
            "(member_id, status, effective_from, created_at) "
            "VALUES (?, 'inactive', '2026-02-01', '2026-02-01T00:00:00+00:00')",
            (member_id,),
        )
