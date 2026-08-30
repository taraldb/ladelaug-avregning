from __future__ import annotations

import asyncio
from decimal import Decimal

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from tests.conftest import MIGRATIONS_DIR

SYS = AuditContext.system()

# member_client seeds member "M-100" as member id 1, linked to user kari@example.com.
MY_ID = 1


def _seed_payment(config, member_id, amount, reference):
    sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
    try:
        asyncio.run(
            LedgerRepo(sep).record_payment(
                member_id=member_id,
                amount=Decimal(amount),
                value_date="2026-08-01",
                reference=reference,
                actor=SYS,
            )
        )
    finally:
        sep.close()


def _add_member(db, reference):
    db.connection.execute(
        "INSERT INTO members (member_reference, full_name, join_date, created_at, updated_at) "
        "VALUES (?, 'Other', '2026-01-01', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00')",
        (reference,),
    )
    db.connection.commit()
    return db.connection.execute(
        "SELECT id FROM members WHERE member_reference = ?", (reference,)
    ).fetchone()[0]


def test_me_returns_own_record(member_client):
    body = member_client.get("/api/me").json()
    assert body["id"] == MY_ID
    assert body["member_reference"] == "M-100"


def test_me_requires_member_role(admin_client):
    for path in ("/api/me", "/api/me/balance", "/api/me/ledger", "/api/me/status"):
        assert admin_client.get(path).status_code == 403


def test_me_requires_authentication(client):
    for path in ("/api/me", "/api/me/balance", "/api/me/ledger", "/api/me/status"):
        assert client.get(path).status_code == 401


def test_me_balance_matches_repo_and_excludes_others(member_client, config, db):
    other = _add_member(db, "M-200")
    _seed_payment(config, MY_ID, "1500.00", "mine-1")
    _seed_payment(config, MY_ID, "100.00", "mine-2")
    _seed_payment(config, other, "9999.00", "theirs")

    body = member_client.get("/api/me/balance").json()
    assert body["member_id"] == MY_ID
    assert body["balance_nok"] == "1600.00"
    assert Decimal(body["balance_nok"]) == LedgerRepo(db).balance(MY_ID)


def test_me_ledger_is_exactly_own_rows(member_client, config, db):
    other = _add_member(db, "M-200")
    _seed_payment(config, MY_ID, "1500.00", "mine-1")
    _seed_payment(config, other, "9999.00", "theirs")

    body = member_client.get("/api/me/ledger").json()
    assert body["total"] == 1
    assert [t["reference"] for t in body["transactions"]] == ["mine-1"]
    assert all(t["member_id"] == MY_ID for t in body["transactions"])


def test_me_status_reflects_own_timeline(member_client, config):
    sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)
    try:
        asyncio.run(
            MemberRepo(sep).set_status(MY_ID, "active", effective_from="2026-01-01", actor=SYS)
        )
    finally:
        sep.close()

    body = member_client.get("/api/me/status").json()
    assert body["status"] == "active"
    assert body["participates"] is True
    assert len(body["history"]) == 1
