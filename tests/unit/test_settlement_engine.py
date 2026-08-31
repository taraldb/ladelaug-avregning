from __future__ import annotations

from decimal import Decimal

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError, NotFoundError

FETCH = {"X-Requested-With": "fetch"}
MONTH = "2026-07"


async def _member(db, ref, *, active=True, participates=None):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=f"Name {ref}",
        email=None,
        join_date="2026-01-01",
        actor=AuditContext.system(),
    )
    mid = int(row["id"])
    if active:
        await MemberRepo(db).set_status(
            mid, "active", effective_from="2026-01-01", actor=AuditContext.system()
        )
    if participates is not None:
        await MemberRepo(db).set_participation(
            mid, participates, effective_from="2026-01-01", actor=AuditContext.system()
        )
    return mid


def _add_consumption(db, *, member_id, kwh, month=MONTH, charger_zid="z-1", sid=None):
    sid = sid or f"s-{member_id}-{kwh}"
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'none', 'test', ?, ?)",
        (
            sid,
            charger_zid,
            member_id,
            month,
            f"{month}-10T10:00:00+00:00",
            f"{month}-10T12:00:00+00:00",
            str(Decimal(kwh)),
            "x",
            "x",
        ),
    )
    db.connection.commit()


async def _pay(db, member_id, nok):
    await LedgerRepo(db).record_payment(
        member_id=member_id,
        amount=Decimal(nok),
        value_date="2026-06-01",
        reference=None,
        actor=AuditContext.system(),
    )


async def _draft_with_lines(db, *, equal_nok=None, consumption_nok=None):
    repo = SettlementRepo(db)
    s = await repo.create_draft(MONTH, actor=AuditContext.system())
    sid = int(s["id"])
    if equal_nok is not None:
        await repo.add_line(
            sid,
            description="Fixed",
            allocation_method="equal",
            amount=Decimal(equal_nok),
            actor=AuditContext.system(),
        )
    if consumption_nok is not None:
        await repo.add_line(
            sid,
            description="Energy",
            allocation_method="consumption",
            amount=Decimal(consumption_nok),
            actor=AuditContext.system(),
        )
    await repo.set_invoice(sid, invoice_kwh="35", actor=AuditContext.system())
    await repo.add_attachment(
        sid, filename="faktura.pdf", content=b"%PDF-1.4 fake", actor=AuditContext.system()
    )
    return repo, sid


# --- invoice lines -------------------------------------------------


async def test_update_line_partial_edit_and_total_resync(db):
    repo, sid = await _draft_with_lines(db, equal_nok="900")
    line = repo.lines(sid)[0]

    updated = await repo.update_line(
        sid,
        line["id"],
        description="Fastledd Q3",
        allocation_method="consumption",
        amount=Decimal("1200.50"),
        actor=AuditContext.system(),
    )
    assert updated["description"] == "Fastledd Q3"
    assert updated["allocation_method"] == "consumption"
    assert updated["amount_nok"] == "1200.50"
    assert repo.get(sid)["invoice_total_nok"] == "1200.50"

    ev = db.connection.execute(
        "SELECT event_type FROM audit_events WHERE event_type = 'settlement.line_updated'"
    ).fetchone()
    assert ev is not None


async def test_update_line_only_amount(db):
    repo, sid = await _draft_with_lines(db, equal_nok="100", consumption_nok="50")
    equal_line = next(l for l in repo.lines(sid) if l["allocation_method"] == "equal")
    await repo.update_line(sid, equal_line["id"], amount=Decimal(250), actor=AuditContext.system())
    row = next(l for l in repo.lines(sid) if l["id"] == equal_line["id"])
    assert row["amount_nok"] == "250.00" and row["allocation_method"] == "equal"
    assert repo.get(sid)["invoice_total_nok"] == "300.00"  # 250 + 50


async def test_update_line_validation_and_not_found(db):
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    line = repo.lines(sid)[0]
    with pytest.raises(DomainError) as ei:
        await repo.update_line(sid, line["id"], amount=Decimal(0), actor=AuditContext.system())
    assert ei.value.code == "bad_amount"
    with pytest.raises(DomainError):
        await repo.update_line(sid, line["id"], description="  ", actor=AuditContext.system())
    with pytest.raises(NotFoundError):
        await repo.update_line(sid, 99999, description="x", actor=AuditContext.system())


async def test_update_line_rejected_once_posted(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    await repo.freeze(sid, actor=AuditContext.system())
    await repo.post(sid, actor=AuditContext.system())
    with pytest.raises(DomainError) as ei:
        await repo.update_line(
            sid, repo.lines(sid)[0]["id"], amount=Decimal(5), actor=AuditContext.system()
        )
    assert ei.value.code == "not_draft"


def test_update_line_route(admin_client):
    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": MONTH}, headers=FETCH
    ).json()["settlement"]["id"]
    line = admin_client.post(
        f"/api/settlement/{sid}/lines",
        json={"description": "Fast", "allocation_method": "equal", "amount": "500"},
        headers=FETCH,
    ).json()["line"]

    resp = admin_client.patch(
        f"/api/settlement/{sid}/lines/{line['id']}",
        json={"allocation_method": "consumption", "amount": "750"},
        headers=FETCH,
    )
    assert resp.status_code == 200
    body = resp.json()
    edited = next(x for x in body["lines"] if x["id"] == line["id"])
    assert edited["allocation_method"] == "consumption" and edited["amount_nok"] == "750.00"

    # empty body -> 422; no CSRF header -> 403
    assert (
        admin_client.patch(
            f"/api/settlement/{sid}/lines/{line['id']}", json={}, headers=FETCH
        ).status_code
        == 422
    )
    assert (
        admin_client.patch(
            f"/api/settlement/{sid}/lines/{line['id']}", json={"amount": "1"}
        ).status_code
        == 403
    )


# --- freeze ----------------------------------------------------------


async def test_freeze_snapshots_participation_consumption_and_grid(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    m3 = await _member(db, "M3", participates=False)  # excluded from equal-cost
    for mid, kwh in ((m1, 10), (m2, 20), (m3, 5)):
        _add_consumption(db, member_id=mid, kwh=kwh)

    repo, sid = await _draft_with_lines(db, equal_nok="900")
    await repo.freeze(sid, actor=AuditContext.system())

    snap = {m["member_id"]: m for m in repo.snapshot_members(sid)}
    assert snap[m1]["participates_equal"] == 1 and snap[m3]["participates_equal"] == 0
    assert Decimal(snap[m2]["consumption_kwh"]) == Decimal(20)
    assert repo.get(sid)["grid_kwh"] == "35.00"
    assert repo.get(sid)["usage_frozen_at"] is not None


async def test_freeze_blocked_by_unassigned_consumption(db):
    await _member(db, "M1")
    _add_consumption(db, member_id=None, kwh=7, charger_zid="z-orphan")
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    with pytest.raises(DomainError) as ei:
        await repo.freeze(sid, actor=AuditContext.system())
    assert ei.value.code == "unassigned_consumption"


async def test_freeze_is_rerunnable_while_draft(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    await repo.freeze(sid, actor=AuditContext.system())
    _add_consumption(db, member_id=m1, kwh=5, sid="s-extra")
    await repo.freeze(sid, actor=AuditContext.system())
    snap = repo.snapshot_members(sid)
    assert len(snap) == 1 and Decimal(snap[0]["consumption_kwh"]) == Decimal(15)


# --- compute / allocation -----------------------------------------


async def test_equal_and_consumption_allocation_sums_to_invoice(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    m3 = await _member(db, "M3", participates=False)
    for mid, kwh in ((m1, 10), (m2, 20), (m3, 5)):
        _add_consumption(db, member_id=mid, kwh=kwh)
    repo, sid = await _draft_with_lines(db, equal_nok="900", consumption_nok="350")
    await repo.freeze(sid, actor=AuditContext.system())

    result = repo.preview(sid)
    charges = {m["member_id"]: m["charge_ore"] for m in result["members"]}
    # equal 90000 øre / 2 participants -> 45000 each (m3 excluded)
    # consumption 35000 øre by 10:20:5 -> 10000 / 20000 / 5000
    assert charges[m1] == 45000 + 10000
    assert charges[m2] == 45000 + 20000
    assert charges[m3] == 5000
    assert result["total_charged_ore"] == 125000
    assert sum(charges.values()) == 125000


async def test_rounding_residual_lands_on_first_equal_member(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    m3 = await _member(db, "M3")
    for mid in (m1, m2, m3):
        _add_consumption(db, member_id=mid, kwh=1)
    repo, sid = await _draft_with_lines(db, equal_nok="100.01")  # 10001 øre / 3
    await repo.freeze(sid, actor=AuditContext.system())
    charges = {m["member_id"]: m["charge_ore"] for m in repo.preview(sid)["members"]}
    assert sorted(charges.values()) == [3333, 3333, 3335]
    assert charges[m1] == 3335
    assert sum(charges.values()) == 10001


async def test_negative_balance_is_warned(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    await _pay(db, m1, "50")  # 50 NOK balance, will be charged 100
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    await repo.freeze(sid, actor=AuditContext.system())
    result = repo.preview(sid)
    codes = {w["code"] for w in result["warnings"]}
    assert "negative_balances" in codes
    row = next(m for m in result["members"] if m["member_id"] == m1)
    assert row["balance_after_ore"] == 5000 - 10000


async def test_usage_stale_warning_after_session_changes(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    db.connection.execute("UPDATE charging_sessions SET updated_at = '2000-01-01T00:00:00+00:00'")
    db.connection.commit()
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    await repo.freeze(sid, actor=AuditContext.system())
    assert not any(w["code"] == "usage_stale" for w in repo.preview(sid)["warnings"])

    # a session for the month is re-imported / re-resolved after the freeze
    db.connection.execute(
        "UPDATE charging_sessions SET updated_at = '2999-01-01T00:00:00+00:00' "
        "WHERE period_month = ?",
        (MONTH,),
    )
    db.connection.commit()
    assert any(w["code"] == "usage_stale" for w in repo.preview(sid)["warnings"])


async def test_usage_stale_warning_when_unassigned_appears_after_freeze(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    db.connection.execute("UPDATE charging_sessions SET updated_at = '2000-01-01T00:00:00+00:00'")
    db.connection.commit()
    repo, sid = await _draft_with_lines(db, equal_nok="100")
    await repo.freeze(sid, actor=AuditContext.system())
    assert not any(w["code"] == "usage_stale" for w in repo.preview(sid)["warnings"])

    _add_consumption(db, member_id=None, kwh=4, sid="s-unassigned", charger_zid="z-9")
    db.connection.execute("UPDATE charging_sessions SET updated_at = '2000-01-01T00:00:00+00:00'")
    db.connection.commit()
    assert any(w["code"] == "usage_stale" for w in repo.preview(sid)["warnings"])


# --- post -------------------------------------------------------


async def test_post_writes_ledger_rows_and_is_idempotent(db):
    m1 = await _member(db, "M1")
    m2 = await _member(db, "M2")
    for mid, kwh in ((m1, 10), (m2, 30)):
        _add_consumption(db, member_id=mid, kwh=kwh)
    await _pay(db, m1, "1000")
    await _pay(db, m2, "1000")
    repo, sid = await _draft_with_lines(db, equal_nok="400", consumption_nok="200")
    await repo.freeze(sid, actor=AuditContext.system())

    out = await repo.post(sid, actor=AuditContext.system())
    assert out["status"] == "posted" and out["members_charged"] == 2

    ledger = LedgerRepo(db)
    # m1: equal 20000 + consumption 5000 = 25000 -> balance 100000 - 25000
    assert ledger.balance_ore(m1) == 100000 - 25000
    assert ledger.balance_ore(m2) == 100000 - (20000 + 15000)
    rows = db.connection.execute(
        "SELECT * FROM ledger_transactions WHERE txn_type = 'settlement_charge'"
    ).fetchall()
    assert len(rows) == 2 and all(r["settlement_id"] == sid and r["amount_ore"] < 0 for r in rows)
    assert db.connection.execute("SELECT COUNT(*) FROM settlement_allocations").fetchone()[0] == 4

    with pytest.raises(DomainError) as ei:
        await repo.post(sid, actor=AuditContext.system())
    assert ei.value.code == "already_posted"
    # no duplicate ledger rows
    assert (
        db.connection.execute(
            "SELECT COUNT(*) FROM ledger_transactions WHERE txn_type = 'settlement_charge'"
        ).fetchone()[0]
        == 2
    )


async def test_post_guards(db):
    m1 = await _member(db, "M1")
    _add_consumption(db, member_id=m1, kwh=10)
    repo = SettlementRepo(db)
    s = await repo.create_draft(MONTH, actor=AuditContext.system())
    sid = int(s["id"])

    with pytest.raises(DomainError) as ei:
        await repo.post(sid, actor=AuditContext.system())
    assert ei.value.code == "not_frozen"

    await repo.add_line(
        sid,
        description="Fixed",
        allocation_method="equal",
        amount=Decimal(100),
        actor=AuditContext.system(),
    )
    await repo.freeze(sid, actor=AuditContext.system())
    with pytest.raises(DomainError) as ei:
        await repo.post(sid, actor=AuditContext.system())
    assert ei.value.code == "invoice_kwh_required"

    await repo.set_invoice(sid, invoice_kwh="10", actor=AuditContext.system())
    with pytest.raises(DomainError) as ei:
        await repo.post(sid, actor=AuditContext.system())
    assert ei.value.code == "attachment_required"


async def test_zero_consumption_blocks_a_consumption_line(db):
    await _member(db, "M1")
    repo, sid = await _draft_with_lines(db, consumption_nok="200")
    await repo.freeze(sid, actor=AuditContext.system())  # no consumption at all
    assert any(w["code"] == "zero_consumption" for w in repo.preview(sid)["warnings"])
    with pytest.raises(DomainError) as ei:
        await repo.post(sid, actor=AuditContext.system())
    assert ei.value.code == "zero_consumption"


async def test_duplicate_month_rejected(db):
    repo = SettlementRepo(db)
    await repo.create_draft(MONTH, actor=AuditContext.system())
    with pytest.raises(DomainError) as ei:
        await repo.create_draft(MONTH, actor=AuditContext.system())
    assert ei.value.code == "month_taken"


# --- routes ----------------------------------------------------------


def test_settlement_http_happy_path(admin_client, make_member):
    m1 = make_member(member_reference="M1")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    admin_client.app.state.db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES ('s1','z1',?,?, '2026-07-10T10:00:00+00:00','2026-07-10T12:00:00+00:00', "
        "'12','none','test','x','x')",
        (m1, MONTH),
    )
    admin_client.app.state.db.connection.commit()

    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": MONTH}, headers=FETCH
    ).json()["settlement"]["id"]
    admin_client.post(
        f"/api/settlement/{sid}/lines",
        json={"description": "Fastledd", "allocation_method": "equal", "amount": "500"},
        headers=FETCH,
    )
    admin_client.put(f"/api/settlement/{sid}/invoice", json={"invoice_kwh": "12"}, headers=FETCH)
    admin_client.post(
        f"/api/settlement/{sid}/attachments",
        files={"files": ("f.pdf", b"%PDF fake", "application/pdf")},
        headers=FETCH,
    )
    admin_client.post(f"/api/settlement/{sid}/freeze", headers=FETCH)
    preview = admin_client.get(f"/api/settlement/{sid}/preview").json()
    assert preview["total_charged_ore"] == 50000

    posted = admin_client.post(f"/api/settlement/{sid}/post", headers=FETCH)
    assert posted.status_code == 200 and posted.json()["status"] == "posted"
    assert admin_client.get("/api/me/balance") is not None  # sanity


def test_settlement_routes_require_admin(member_client):
    assert member_client.get("/api/settlement").status_code == 403


def test_settlement_mutation_needs_fetch_header(admin_client):
    assert (
        admin_client.post("/api/settlement/drafts", json={"period_month": "2026-07"}).status_code
        == 403
    )
