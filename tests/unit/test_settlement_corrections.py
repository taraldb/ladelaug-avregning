"""Settlement corrections engine (Epic 7 — US-701 / US-702 / US-703).

A posted settlement is recomputed from the month's *current* imported
consumption against its *frozen* invoice lines and frozen equal-cost
participation; the per-member difference is booked as ``settlement_correction``
ledger rows without touching the original settlement.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError

SYS = AuditContext.system()
MONTH = "2026-07"


async def _member(db, ref):
    row = await MemberRepo(db).create(
        member_reference=ref, full_name=f"Name {ref}", email=None, join_date="2026-01-01", actor=SYS
    )
    mid = int(row["id"])
    await MemberRepo(db).set_status(mid, "active", effective_from="2026-01-01", actor=SYS)
    return mid


def _add_consumption(db, *, member_id, kwh, sid=None, month=MONTH):
    sid = sid or f"s-{member_id}-{kwh}"
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES (?, 'z-1', ?, ?, ?, ?, ?, 'none', 'test', 't', 't')",
        (
            sid,
            member_id,
            month,
            f"{month}-10T10:00:00+00:00",
            f"{month}-10T12:00:00+00:00",
            str(Decimal(kwh)),
        ),
    )
    db.connection.commit()


async def _posted(db, *, equal_nok=None, consumption_nok=None, invoice_kwh="30"):
    repo = SettlementRepo(db)
    s = await repo.create_draft(MONTH, actor=SYS)
    sid = int(s["id"])
    if equal_nok is not None:
        await repo.add_line(
            sid, description="Fast", allocation_method="equal", amount=Decimal(equal_nok), actor=SYS
        )
    if consumption_nok is not None:
        await repo.add_line(
            sid,
            description="Energi",
            allocation_method="consumption",
            amount=Decimal(consumption_nok),
            actor=SYS,
        )
    await repo.set_invoice(sid, invoice_kwh=invoice_kwh, actor=SYS)
    await repo.add_attachment(sid, filename="f.pdf", content=b"%PDF-1.4", actor=SYS)
    await repo.freeze(sid, actor=SYS)
    await repo.post(sid, actor=SYS)
    return repo, sid


def _flag(db, sid, session_id="s-late"):
    db.connection.execute(
        "INSERT INTO late_session_flags "
        "(zaptec_session_id, period_month, settlement_id, kind, detected_at) "
        "VALUES (?, ?, ?, 'new', '2026-08-01T00:00:00+00:00')",
        (session_id, MONTH, sid),
    )
    db.connection.commit()


async def test_no_change_reports_nothing(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    repo, sid = await _posted(db, consumption_nok="1000")

    a = repo.assess_correction(sid)
    assert a["has_changes"] is False
    assert a["members"] == []
    assert a["sequence_next"] == 1

    with pytest.raises(DomainError) as ei:
        await repo.post_correction(sid, actor=SYS)
    assert ei.value.code == "no_correction_needed"


async def test_late_session_shifts_consumption_share(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    _add_consumption(db, member_id=m1, kwh=10)
    _add_consumption(db, member_id=m2, kwh=10)
    repo, sid = await _posted(db, consumption_nok="1000", invoice_kwh="20")
    _flag(db, sid)

    ledger = LedgerRepo(db)
    assert ledger.balance(m1) == Decimal("-500.00")
    assert ledger.balance(m2) == Decimal("-500.00")

    # a late session for m1: now 20 kWh vs 10 kWh -> m1 owes 2/3, m2 owes 1/3
    _add_consumption(db, member_id=m1, kwh=10, sid="s-late")

    a = repo.assess_correction(sid)
    assert a["has_changes"] is True
    by_id = {m["member_id"]: m for m in a["members"]}
    assert by_id[m1]["delta_ore"] < 0  # m1 under-charged -> extra debit
    assert by_id[m2]["delta_ore"] > 0  # m2 over-charged -> refund credit
    assert by_id[m1]["delta_ore"] + by_id[m2]["delta_ore"] == 0

    original_alloc = repo.allocations(sid)

    result = await repo.post_correction(sid, actor=SYS)
    assert result["sequence"] == 1
    assert result["members_adjusted"] == 2

    # two settlement_correction ledger rows, balances moved, sum preserved
    rows = db.connection.execute(
        "SELECT member_id, amount_ore FROM ledger_transactions "
        "WHERE txn_type = 'settlement_correction' AND settlement_id = ?",
        (sid,),
    ).fetchall()
    assert len(rows) == 2
    assert sum(r["amount_ore"] for r in rows) == 0
    assert ledger.balance(m1) == Decimal("-666.67")
    assert ledger.balance(m2) == Decimal("-333.33")

    # original settlement + its allocations untouched
    assert repo.get(sid)["status"] == "posted"
    assert repo.allocations(sid) == original_alloc

    # correction record + members rows
    corr = repo.corrections(sid)
    assert len(corr) == 1 and corr[0]["sequence"] == 1
    assert len(corr[0]["members"]) == 2

    # the month's late-session flag is now resolved
    flag = db.connection.execute(
        "SELECT resolved_at, note FROM late_session_flags WHERE period_month = ?", (MONTH,)
    ).fetchone()
    assert flag["resolved_at"] is not None
    assert "correction" in flag["note"]


async def test_equal_line_is_frozen_across_a_correction(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    _add_consumption(db, member_id=m1, kwh=10)
    _add_consumption(db, member_id=m2, kwh=10)
    repo, sid = await _posted(db, equal_nok="400", consumption_nok="600", invoice_kwh="20")

    _add_consumption(db, member_id=m1, kwh=30, sid="s-late")  # only consumption moves
    a = repo.assess_correction(sid)
    by_id = {m["member_id"]: m for m in a["members"]}
    # equal share stays 200 each; only the 600 consumption line re-splits 4:1
    # m1 corrected charge = 200 + 480 = 680 ; m2 = 200 + 120 = 320
    assert by_id[m1]["corrected_charge_ore"] == 68000
    assert by_id[m2]["corrected_charge_ore"] == 32000


async def test_second_correction_does_not_double_count(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    _add_consumption(db, member_id=m1, kwh=10)
    _add_consumption(db, member_id=m2, kwh=10)
    repo, sid = await _posted(db, consumption_nok="1000", invoice_kwh="20")

    _add_consumption(db, member_id=m1, kwh=10, sid="s-late-1")
    await repo.post_correction(sid, actor=SYS)

    # m1 now has 20 kWh, m2 gets +20 for 30 kWh -> 20:30 of the 1000 line
    _add_consumption(db, member_id=m2, kwh=20, sid="s-late-2")
    a2 = repo.assess_correction(sid)
    assert a2["sequence_next"] == 2
    by_id = {m["member_id"]: m for m in a2["members"]}
    assert by_id[m1]["corrected_charge_ore"] == 40000
    assert by_id[m2]["corrected_charge_ore"] == 60000

    r2 = await repo.post_correction(sid, actor=SYS)
    assert r2["sequence"] == 2
    ledger = LedgerRepo(db)
    # balances land on the fresh target, not a doubled one
    assert ledger.balance(m1) == Decimal("-400.00")
    assert ledger.balance(m2) == Decimal("-600.00")
