import sqlite3

import pytest

from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.audit_repo import AuditRepo

CTX = AuditContext(actor_user_id=None, actor_label="admin@example.com", ip="127.0.0.1")


async def _seed(db: Database):
    await record_audit(
        db,
        CTX,
        event_type="member.created",
        entity_type="member",
        entity_id=1,
        summary="created Kari",
    )
    await record_audit(
        db,
        CTX,
        event_type="member.updated",
        entity_type="member",
        entity_id=1,
        summary="renamed",
        detail={"before": "Kari", "after": "Kari N"},
    )
    await record_audit(
        db,
        CTX,
        event_type="ledger.payment_recorded",
        entity_type="ledger_transaction",
        entity_id=7,
        summary="+1000",
    )


async def test_list_newest_first_and_total(db: Database):
    await _seed(db)
    rows, total = AuditRepo(db).list_audit_events()
    assert total == 3
    assert [r["event_type"] for r in rows] == [
        "ledger.payment_recorded",
        "member.updated",
        "member.created",
    ]


async def test_pagination(db: Database):
    await _seed(db)
    repo = AuditRepo(db)
    page1, total = repo.list_audit_events(limit=2, offset=0)
    page2, _ = repo.list_audit_events(limit=2, offset=2)
    assert total == 3
    assert len(page1) == 2 and len(page2) == 1


async def test_filters(db: Database):
    await _seed(db)
    repo = AuditRepo(db)
    by_type, n = repo.list_audit_events(event_type="member.created")
    assert n == 1 and by_type[0]["summary"] == "created Kari"

    by_entity, n = repo.list_audit_events(entity_type="ledger_transaction")
    assert n == 1 and by_entity[0]["entity_id"] == "7"

    by_id, n = repo.list_audit_events(entity_type="member", entity_id="1")
    assert n == 2 and len(by_id) == 2


async def test_detail_roundtrips(db: Database):
    await _seed(db)
    rows, _ = AuditRepo(db).list_audit_events(event_type="member.updated")
    assert rows[0]["detail"] == {"before": "Kari", "after": "Kari N"}


async def test_bad_sort_column(db: Database):
    with pytest.raises(ValueError):
        AuditRepo(db).list_audit_events(sort_by="ip")


async def test_get_unknown_returns_none(db: Database):
    assert AuditRepo(db).get_audit_event(999) is None


async def test_count_by_type(db: Database):
    await _seed(db)
    assert AuditRepo(db).count_by_type() == {
        "member.created": 1,
        "member.updated": 1,
        "ledger.payment_recorded": 1,
    }


async def test_events_are_immutable(db: Database):
    await _seed(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE audit_events SET summary = 'tampered'")


async def test_context_captures_ip_user_agent_and_role(db: Database):
    ctx = AuditContext(
        actor_user_id=None,
        actor_label="admin@example.com",
        ip="10.1.2.3",
        user_agent="Mozilla/5.0 (pytest)",
        actor_role="admin",
    )
    await record_audit(
        db, ctx, event_type="member.created", entity_type="member", entity_id=1, summary="x"
    )
    row = AuditRepo(db).get_audit_event(1)
    assert row["ip"] == "10.1.2.3"
    assert row["user_agent"] == "Mozilla/5.0 (pytest)"
    assert row["actor_role"] == "admin"
