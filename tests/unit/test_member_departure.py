"""Member departure workflow (US-204).

departure_check previews the open charger assignments, unsettled months, and
balance; process_departure ends the status, closes the assignments, and
optionally refunds the whole positive balance.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError

SYS = AuditContext.system()
LEAVE = "2026-09-01"


async def _member(db, ref="D-1"):
    row = await MemberRepo(db).create(
        member_reference=ref, full_name=f"Name {ref}", email=None, join_date="2026-01-01", actor=SYS
    )
    mid = int(row["id"])
    await MemberRepo(db).set_status(mid, "active", effective_from="2026-01-01", actor=SYS)
    return mid


async def _charger_for(db, member_id, name="C-1"):
    c = await ChargerRepo(db).create(name=name, serial_no=name, actor=SYS)
    await ChargerRepo(db).assign(int(c["id"]), member_id, effective_from="2026-01-01", actor=SYS)
    return int(c["id"])


def _session(db, member_id, month, sid="s-x"):
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES (?, 'z1', ?, ?, ?, ?, '5', 'none', 'test', 't', 't')",
        (sid, member_id, month, f"{month}-10T10:00:00+00:00", f"{month}-10T12:00:00+00:00"),
    )
    db.connection.commit()


async def test_departure_check_lists_assignments_unsettled_and_balance(db):
    m = await _member(db)
    cid = await _charger_for(db, m)
    _session(db, m, "2026-08")
    await LedgerRepo(db).record_payment(
        member_id=m, amount=Decimal("300.00"), value_date="2026-06-01", reference=None, actor=SYS
    )

    check = MemberRepo(db).departure_check(m, effective_date=LEAVE)
    assert [a["charger_id"] for a in check["open_assignments"]] == [cid]
    assert check["unsettled_months"] == ["2026-08"]
    assert check["balance_ore"] == 30000
    assert check["would_refund_ore"] == 30000
    assert check["current_status"] == "active"


async def test_process_departure_closes_assignments_and_sets_inactive(db):
    m = await _member(db)
    cid = await _charger_for(db, m)

    result = await MemberRepo(db).process_departure(m, effective_date=LEAVE, actor=SYS)
    assert result["status_changed"] is True
    assert result["assignments_closed"] == [cid]
    assert result["refund_txn_id"] is None

    assert MemberRepo(db).current_status(m, "2026-09-02") == "inactive"
    open_rows = db.connection.execute(
        "SELECT effective_to FROM charger_assignments WHERE charger_id = ?", (cid,)
    ).fetchall()
    assert [r["effective_to"] for r in open_rows] == [LEAVE]
    ev = db.connection.execute(
        "SELECT summary FROM audit_events WHERE event_type = 'member.departed'"
    ).fetchone()
    assert ev is not None and "departed 2026-09-01" in ev["summary"]


async def test_process_departure_refunds_positive_balance(db):
    m = await _member(db)
    await LedgerRepo(db).record_payment(
        member_id=m, amount=Decimal("450.00"), value_date="2026-06-01", reference=None, actor=SYS
    )
    result = await MemberRepo(db).process_departure(
        m, effective_date=LEAVE, refund=True, refund_reference="bank-out-1", actor=SYS
    )
    assert result["refund_txn_id"] is not None
    assert result["refunded_ore"] == 45000
    assert LedgerRepo(db).balance(m) == Decimal("0.00")
    txn = db.connection.execute(
        "SELECT txn_type, reference FROM ledger_transactions WHERE id = ?",
        (result["refund_txn_id"],),
    ).fetchone()
    assert txn["txn_type"] == "refund" and txn["reference"] == "bank-out-1"


async def test_refund_blocked_by_unsettled_month(db):
    m = await _member(db)
    _session(db, m, "2026-08")
    await LedgerRepo(db).record_payment(
        member_id=m, amount=Decimal("100.00"), value_date="2026-06-01", reference=None, actor=SYS
    )
    with pytest.raises(DomainError) as ei:
        await MemberRepo(db).process_departure(m, effective_date=LEAVE, refund=True, actor=SYS)
    assert ei.value.code == "unsettled_consumption"
    # nothing changed
    assert MemberRepo(db).current_status(m) == "active"


async def test_refund_with_non_positive_balance_is_a_noop(db):
    m = await _member(db)
    result = await MemberRepo(db).process_departure(m, effective_date=LEAVE, refund=True, actor=SYS)
    assert result["refund_txn_id"] is None
    assert result["refunded_ore"] == 0


def test_departure_routes(admin_client, make_member):
    m = make_member(member_reference="D-9")
    admin_client.post(
        f"/api/members/{m}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers={"X-Requested-With": "fetch"},
    )
    check = admin_client.get(f"/api/members/{m}/departure-check?effective_date={LEAVE}")
    assert check.status_code == 200 and check.json()["open_assignments"] == []

    done = admin_client.post(
        f"/api/members/{m}/departure",
        json={"effective_date": LEAVE},
        headers={"X-Requested-With": "fetch"},
    )
    assert done.status_code == 200 and done.json()["status_changed"] is True

    # CSRF header required on the mutation
    assert (
        admin_client.post(f"/api/members/{m}/departure", json={"effective_date": LEAVE}).status_code
        == 403
    )


def test_departure_check_requires_admin(member_client, make_member):
    m = make_member(member_reference="D-8")
    assert member_client.get(f"/api/members/{m}/departure-check").status_code == 403
