from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.money import ore_to_nok

SYS = AuditContext.system()
FETCH = {"X-Requested-With": "fetch"}
_NOW = "2026-01-01T00:00:00+00:00"


def _make_member(db, ref, email):
    db.connection.execute(
        "INSERT INTO members (member_reference, full_name, email, join_date, created_at, "
        "updated_at) VALUES (?, 'X', ?, '2026-01-01', ?, ?)",
        (ref, email, _NOW, _NOW),
    )
    db.connection.commit()
    return db.connection.execute(
        "SELECT id FROM members WHERE member_reference = ?", (ref,)
    ).fetchone()[0]


def _seed_settlement(conn, month, member_id, kwh):
    cur = conn.execute(
        "INSERT INTO settlements (period_month, status, grid_kwh, invoice_kwh, created_at, "
        "usage_frozen_at, posted_at) VALUES (?, 'posted', '100', '100', ?, ?, ?)",
        (month, _NOW, _NOW, _NOW),
    )
    sid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO settlement_invoice_lines (settlement_id, description, allocation_method, "
        "amount_ore, amount_nok, created_at) VALUES (?, 'Energy', 'consumption', 10000, ?, ?)",
        (sid, str(ore_to_nok(10000)), _NOW),
    )
    conn.execute(
        "INSERT INTO settlement_members (settlement_id, member_id, member_reference, full_name, "
        "is_active, participates_equal, consumption_kwh, session_count, balance_before_ore) "
        "VALUES (?, ?, 'M', 'X', 1, 0, ?, 0, 0)",
        (sid, member_id, str(kwh)),
    )
    conn.commit()


def _seed_history(db, member_id, *, kwh=20, months=("2026-04", "2026-05", "2026-06")):
    for month in months:
        _seed_settlement(db.connection, month, member_id, kwh)


async def _pay(db, member_id, nok):
    await LedgerRepo(db).record_payment(
        member_id=member_id, amount=Decimal(nok), value_date="2026-06-01", reference=None, actor=SYS
    )


async def _debit(db, member_id, nok):
    await LedgerRepo(db).adjust(
        member_id=member_id,
        direction="debit",
        amount=Decimal(nok),
        reason="test",
        reference=None,
        actor=SYS,
    )


# rate 100 øre/kWh, 20 kWh -> forecast_monthly_cost 2000 øre,
# recommended minimum 4000 øre (default buffer 2.0)


async def test_first_scan_enqueues_email_history_and_audit(frozen_now, db):
    mid = _make_member(db, "L-1", "l1@example.com")
    _seed_history(db, mid)  # balance 0 -> critical

    out = await NotificationRepo(db).scan_low_balances(actor=SYS)
    assert out == {"scanned": 1, "below": 1, "queued": 1, "suppressed": 0}

    email = db.connection.execute("SELECT * FROM email_messages").fetchone()
    assert email["template"] == "low_balance_warning"
    assert email["status"] == "queued"
    assert email["to_address"] == "l1@example.com"
    assert email["related_entity_id"] == str(mid)

    hist = db.connection.execute("SELECT * FROM low_balance_notifications").fetchall()
    assert len(hist) == 1
    assert hist[0]["member_id"] == mid
    assert hist[0]["email_message_id"] == email["id"]
    assert hist[0]["severity"] == "critical"
    assert hist[0]["balance_ore"] == 0

    audit = db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = 'notifications.low_balance_warned'"
    ).fetchall()
    assert len(audit) == 1
    assert audit[0]["entity_id"] == str(mid)


async def test_second_scan_within_cooldown_suppresses(frozen_now, db):
    mid = _make_member(db, "L-2", "l2@example.com")
    _seed_history(db, mid)

    repo = NotificationRepo(db)
    await repo.scan_low_balances(actor=SYS)
    out = await repo.scan_low_balances(actor=SYS)
    assert out == {"scanned": 1, "below": 1, "queued": 0, "suppressed": 1}
    assert db.connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 1
    assert (
        db.connection.execute("SELECT COUNT(*) FROM low_balance_notifications").fetchone()[0] == 1
    )


async def test_balance_drop_resends_within_cooldown(frozen_now, db):
    mid = _make_member(db, "L-3", "l3@example.com")
    _seed_history(db, mid)
    await _pay(db, mid, "30.00")  # balance 3000 -> low

    repo = NotificationRepo(db)
    assert (await repo.scan_low_balances(actor=SYS))["queued"] == 1
    await _debit(db, mid, "1.00")  # balance 2900, still low, dropped 100 øre

    out = await repo.scan_low_balances(actor=SYS)
    assert out["queued"] == 1
    assert db.connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 2


async def test_low_to_critical_escalation_resends_within_cooldown(frozen_now, db):
    mid = _make_member(db, "L-4", "l4@example.com")
    _seed_history(db, mid)
    await _pay(db, mid, "20.30")  # balance 2030 -> low (>= 2000)

    repo = NotificationRepo(db)
    assert (await repo.scan_low_balances(actor=SYS))["queued"] == 1
    await _debit(db, mid, "0.50")  # balance 1980 -> critical, drop only 50 øre

    out = await repo.scan_low_balances(actor=SYS)
    assert out["queued"] == 1
    rows = db.connection.execute(
        "SELECT severity FROM low_balance_notifications ORDER BY id"
    ).fetchall()
    assert [r["severity"] for r in rows] == ["low", "critical"]


async def test_cooldown_elapsed_resends(frozen_now, db):
    mid = _make_member(db, "L-5", "l5@example.com")
    _seed_history(db, mid)

    repo = NotificationRepo(db)
    assert (await repo.scan_low_balances(actor=SYS))["queued"] == 1
    frozen_now["now"] = frozen_now["now"] + timedelta(days=15)  # cooldown is 14 days

    assert (await repo.scan_low_balances(actor=SYS))["queued"] == 1
    assert db.connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 2


async def test_unavailable_forecast_is_never_emailed(frozen_now, db):
    mid = _make_member(db, "L-6", "l6@example.com")
    _seed_history(db, mid, months=("2026-05", "2026-06"))  # only 2 < lookback 3

    out = await NotificationRepo(db).scan_low_balances(actor=SYS)
    assert out == {"scanned": 0, "below": 0, "queued": 0, "suppressed": 0}
    assert db.connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 0


# --- route + health --------------------------------------------------


def test_low_balance_scan_route(admin_client):
    out = admin_client.post("/api/notifications/low-balance-scan", headers=FETCH)
    assert out.status_code == 200
    assert set(out.json()) == {"scanned", "below", "queued", "suppressed"}


def test_low_balance_scan_route_needs_fetch_and_admin(admin_client, member_client):
    assert admin_client.post("/api/notifications/low-balance-scan").status_code == 403
    assert (
        member_client.post("/api/notifications/low-balance-scan", headers=FETCH).status_code == 403
    )


def test_health_payload_has_low_balance_counters(admin_client):
    body = admin_client.get("/api/system/health").json()
    assert body["low_balance"] == {"warned_total": 0, "members_below": 0}
