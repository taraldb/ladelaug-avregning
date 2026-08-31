from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import ore_to_nok

FETCH = {"X-Requested-With": "fetch"}
SYS = AuditContext.system()


async def _member(db, ref="M-1"):
    row = await MemberRepo(db).create(
        member_reference=ref, full_name=ref, email=None, join_date="2026-01-01", actor=SYS
    )
    return row["id"]


def _sum_ore(db, member_id):
    return db.connection.execute(
        "SELECT COALESCE(SUM(amount_ore), 0) FROM ledger_transactions WHERE member_id = ?",
        (member_id,),
    ).fetchone()[0]


# --- LedgerRepo --------------------------------------------------------


async def test_balance_equals_sum_of_rows(db):
    m = await _member(db)
    repo = LedgerRepo(db)
    pay = await repo.record_payment(
        member_id=m,
        amount=Decimal("1500.00"),
        value_date="2026-08-01",
        reference="bank-1",
        actor=SYS,
    )
    await repo.adjust(
        member_id=m,
        direction="credit",
        amount=Decimal("10.00"),
        reason="goodwill",
        reference=None,
        actor=SYS,
    )
    await repo.adjust(
        member_id=m,
        direction="debit",
        amount=Decimal("50.00"),
        reason="korrigering",
        reference=None,
        actor=SYS,
    )
    await repo.reverse_payment(txn_id=pay["id"], actor=SYS)

    assert repo.balance(m) == ore_to_nok(_sum_ore(db, m))
    assert repo.balance(m) == Decimal("-40.00")  # 1500 + 10 - 50 - 1500


@pytest.mark.parametrize("amount", ["100.00", "0.01", "1234.56", "999999.99"])
async def test_amount_ore_and_nok_never_disagree(db, amount):
    m = await _member(db)
    row = await LedgerRepo(db).record_payment(
        member_id=m, amount=Decimal(amount), value_date="2026-08-01", reference=None, actor=SYS
    )
    assert ore_to_nok(row["amount_ore"]) == Decimal(row["amount_nok"])
    assert row["amount_nok"] == amount


async def test_reverse_twice_rejected(db):
    m = await _member(db)
    repo = LedgerRepo(db)
    pay = await repo.record_payment(
        member_id=m, amount=Decimal("100.00"), value_date="2026-08-01", reference=None, actor=SYS
    )
    await repo.reverse_payment(txn_id=pay["id"], actor=SYS)
    with pytest.raises(DomainError) as excinfo:
        await repo.reverse_payment(txn_id=pay["id"], actor=SYS)
    assert excinfo.value.code == "already_reversed"


async def test_reverse_non_payment_rejected(db):
    m = await _member(db)
    repo = LedgerRepo(db)
    adj = await repo.adjust(
        member_id=m,
        direction="credit",
        amount=Decimal("5.00"),
        reason="x",
        reference=None,
        actor=SYS,
    )
    with pytest.raises(DomainError) as excinfo:
        await repo.reverse_payment(txn_id=adj["id"], actor=SYS)
    assert excinfo.value.code == "not_a_payment"


async def test_reverse_unknown_txn(db):
    with pytest.raises(NotFoundError):
        await LedgerRepo(db).reverse_payment(txn_id=999, actor=SYS)


async def test_adjust_blank_reason_rejected(db):
    m = await _member(db)
    with pytest.raises(DomainError) as excinfo:
        await LedgerRepo(db).adjust(
            member_id=m,
            direction="debit",
            amount=Decimal("5.00"),
            reason="   ",
            reference=None,
            actor=SYS,
        )
    assert excinfo.value.code == "reason_required"


async def test_non_positive_amounts_rejected(db):
    m = await _member(db)
    repo = LedgerRepo(db)
    with pytest.raises(DomainError) as excinfo:
        await repo.record_payment(
            member_id=m, amount=Decimal("0.00"), value_date="2026-08-01", reference=None, actor=SYS
        )
    assert excinfo.value.code == "bad_amount"
    with pytest.raises(DomainError):
        await repo.adjust(
            member_id=m,
            direction="credit",
            amount=Decimal("-1.00"),
            reason="x",
            reference=None,
            actor=SYS,
        )


async def test_record_payment_unknown_member(db):
    with pytest.raises(NotFoundError):
        await LedgerRepo(db).record_payment(
            member_id=999,
            amount=Decimal("1.00"),
            value_date="2026-08-01",
            reference=None,
            actor=SYS,
        )


async def test_list_newest_first_and_pagination(db):
    m = await _member(db)
    repo = LedgerRepo(db)
    for i in range(5):
        await repo.record_payment(
            member_id=m,
            amount=Decimal("10.00"),
            value_date="2026-08-01",
            reference=f"r{i}",
            actor=SYS,
        )
    rows, total = repo.list(m, limit=2, offset=0)
    assert total == 5
    assert [r["reference"] for r in rows] == ["r4", "r3"]
    rows2, _ = repo.list(m, limit=2, offset=2)
    assert [r["reference"] for r in rows2] == ["r2", "r1"]


async def test_list_all_spans_members_with_join_and_filters(db):
    a = await _member(db, "M-A")
    b = await _member(db, "M-B")
    repo = LedgerRepo(db)
    await repo.record_payment(
        member_id=a, amount=Decimal("100.00"), value_date="2026-08-01", reference="pa", actor=SYS
    )
    await repo.record_payment(
        member_id=b, amount=Decimal("200.00"), value_date="2026-08-02", reference="pb", actor=SYS
    )
    await repo.adjust(
        member_id=b,
        direction="debit",
        amount=Decimal("5.00"),
        reason="x",
        reference=None,
        actor=SYS,
    )

    rows, total = repo.list_all(limit=10, offset=0)
    assert total == 3
    # newest first
    assert rows[0]["txn_type"] == "adjustment_debit"
    assert rows[0]["member_name"] == "M-B"
    assert rows[0]["member_reference"] == "M-B"

    only_b, total_b = repo.list_all(member_id=b)
    assert total_b == 2
    assert {r["member_id"] for r in only_b} == {b}

    pays, total_p = repo.list_all(txn_type="payment")
    assert total_p == 2
    assert {r["txn_type"] for r in pays} == {"payment"}


async def test_balance_ore_map(db):
    a = await _member(db, "M-A")
    b = await _member(db, "M-B")
    repo = LedgerRepo(db)
    await repo.record_payment(
        member_id=a, amount=Decimal("100.00"), value_date="2026-08-01", reference=None, actor=SYS
    )
    assert repo.balance_ore_map() == {a: 10000}
    assert b not in repo.balance_ore_map()


def test_ledger_transactions_route(admin_client, make_member):
    a = make_member(member_reference="M-A", email="a@example.com")
    b = make_member(member_reference="M-B", email="b@example.com")
    _pay(admin_client, a, amount="100.00")
    _pay(admin_client, b, amount="200.00")

    body = admin_client.get("/api/ledger-transactions").json()
    assert body["total"] == 2
    assert body["transactions"][0]["member_reference"] in {"M-A", "M-B"}
    assert "member_name" in body["transactions"][0]

    filtered = admin_client.get(f"/api/ledger-transactions?member_id={a}").json()
    assert filtered["total"] == 1
    assert filtered["transactions"][0]["member_id"] == a


def test_ledger_transactions_route_anonymous_401(client):
    assert client.get("/api/ledger-transactions").status_code == 401


def test_ledger_transactions_route_member_403(member_client):
    assert member_client.get("/api/ledger-transactions").status_code == 403


async def test_each_action_writes_one_audit_row(db):
    m = await _member(db)
    repo = LedgerRepo(db)
    pay = await repo.record_payment(
        member_id=m, amount=Decimal("1500.00"), value_date="2026-08-01", reference=None, actor=SYS
    )
    await repo.adjust(
        member_id=m,
        direction="debit",
        amount=Decimal("50.00"),
        reason="korrigering",
        reference=None,
        actor=SYS,
    )
    await repo.reverse_payment(txn_id=pay["id"], actor=SYS)

    def one(event_type):
        rows = db.connection.execute(
            "SELECT * FROM audit_events WHERE event_type = ?", (event_type,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["entity_type"] == "ledger_transaction"
        return rows[0]

    assert "1500" in one("ledger.payment_recorded")["summary"]
    assert f"member {m}" in one("ledger.adjusted")["summary"]
    assert f"member {m}" in one("ledger.payment_reversed")["summary"]


async def test_rows_are_append_only(db):
    m = await _member(db)
    await LedgerRepo(db).record_payment(
        member_id=m, amount=Decimal("1.00"), value_date="2026-08-01", reference=None, actor=SYS
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE ledger_transactions SET amount_ore = 0")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM ledger_transactions")


# --- routes ---------------------------------------------------------


def _pay(client, member_id, amount="1500.00", value_date="2026-08-01"):
    return client.post(
        f"/api/members/{member_id}/payments",
        json={"amount": amount, "value_date": value_date},
        headers=FETCH,
    )


def test_payment_and_balance_route(admin_client, make_member):
    m = make_member(member_reference="A-07")
    resp = _pay(admin_client, m)
    assert resp.status_code == 201
    assert resp.json()["txn_type"] == "payment"
    assert admin_client.get(f"/api/members/{m}/balance").json() == {
        "member_id": m,
        "balance_nok": "1500.00",
        "balance_ore": 150000,
    }


def test_adjustment_route_and_empty_reason(admin_client, make_member):
    m = make_member(member_reference="A-07")
    _pay(admin_client, m)
    resp = admin_client.post(
        f"/api/members/{m}/adjustments",
        json={"direction": "debit", "amount": "50.00", "reason": "korrigering"},
        headers=FETCH,
    )
    assert resp.status_code == 201
    assert admin_client.get(f"/api/members/{m}/balance").json()["balance_nok"] == "1450.00"

    bad = admin_client.post(
        f"/api/members/{m}/adjustments",
        json={"direction": "debit", "amount": "50.00", "reason": ""},
        headers=FETCH,
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "validation_error"


def test_reverse_route(admin_client, make_member):
    m = make_member(member_reference="A-07")
    pay_id = _pay(admin_client, m).json()["id"]
    resp = admin_client.post(f"/api/ledger-transactions/{pay_id}/reverse", headers=FETCH)
    assert resp.status_code == 201
    assert resp.json()["amount_nok"] == "-1500.00"
    assert admin_client.get(f"/api/members/{m}/balance").json()["balance_nok"] == "0.00"

    again = admin_client.post(f"/api/ledger-transactions/{pay_id}/reverse", headers=FETCH)
    assert again.status_code == 422
    assert again.json()["detail"]["code"] == "already_reversed"


def test_ledger_list_route(admin_client, make_member):
    m = make_member(member_reference="A-07")
    pay_id = _pay(admin_client, m).json()["id"]
    admin_client.post(
        f"/api/members/{m}/adjustments",
        json={"direction": "debit", "amount": "50.00", "reason": "k"},
        headers=FETCH,
    )
    admin_client.post(f"/api/ledger-transactions/{pay_id}/reverse", headers=FETCH)

    body = admin_client.get(f"/api/members/{m}/ledger").json()
    assert body["total"] == 3
    assert [t["txn_type"] for t in body["transactions"]] == [
        "payment_reversal",
        "adjustment_debit",
        "payment",
    ]
    assert body["balance_nok"] == "-50.00"


def test_ledger_anonymous_401(client, make_member):
    m = make_member(member_reference="A-07")
    assert client.get(f"/api/members/{m}/balance").status_code == 401
    assert client.get(f"/api/members/{m}/ledger").status_code == 401
    assert _pay(client, m).status_code == 401
    assert client.post("/api/ledger-transactions/1/reverse", headers=FETCH).status_code == 401


def test_ledger_member_403(member_client, make_member):
    m = make_member(member_reference="A-07")
    assert member_client.get(f"/api/members/{m}/balance").status_code == 403
    assert _pay(member_client, m).status_code == 403
    assert (
        member_client.post("/api/ledger-transactions/1/reverse", headers=FETCH).status_code == 403
    )


def test_ledger_unknown_member_404(admin_client):
    assert admin_client.get("/api/members/999/balance").status_code == 404
    assert admin_client.get("/api/members/999/ledger").status_code == 404
    assert _pay(admin_client, 999).status_code == 404
    assert (
        admin_client.post(
            "/api/members/999/adjustments",
            json={"direction": "credit", "amount": "1.00", "reason": "x"},
            headers=FETCH,
        ).status_code
        == 404
    )


def test_reverse_unknown_txn_404(admin_client):
    resp = admin_client.post("/api/ledger-transactions/999/reverse", headers=FETCH)
    assert resp.status_code == 404


def test_payment_requires_csrf_header(admin_client, make_member):
    m = make_member(member_reference="A-07")
    resp = admin_client.post(f"/api/members/{m}/payments", json={"amount": "1.00"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf"
