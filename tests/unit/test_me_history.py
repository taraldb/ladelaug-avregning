"""GET /api/me/history — the member dashboard's rolling 6-month strip.

Covers the three data dimensions the endpoint stitches together: metered kWh per
month (available before any settlement), the kr charge for months whose
settlement is posted, and the running ledger balance at each month's end. Scoping
(own member only, 401/403) lives in ``test_me_scoping.py`` via ``_ME_PATHS``.
"""

from __future__ import annotations

from ladelaug_avregning.money import ore_to_nok

# member_client seeds member "M-100" as member id 1, linked to kari@example.com.
MY_ID = 1
_NOW = "2026-01-01T00:00:00+00:00"


def _seed_session(conn, member_id: int, month: str, kwh: str, *, sid: str = "cs") -> None:
    conn.execute(
        "INSERT INTO charging_sessions (zaptec_session_id, charger_zaptec_id, member_id, "
        "period_month, started_at, ended_at, energy_kwh, split_method, source, imported_at, "
        "updated_at) VALUES (?, 'z1', ?, ?, ?, ?, ?, 'none', 'test', ?, ?)",
        (
            f"{sid}-{member_id}-{month}",
            member_id,
            month,
            f"{month}-10T10:00:00+00:00",
            f"{month}-10T12:00:00+00:00",
            kwh,
            _NOW,
            _NOW,
        ),
    )
    conn.commit()


def _seed_posted_settlement(conn, month: str, member_id: int, kwh: str, line_ore: int) -> int:
    cur = conn.execute(
        "INSERT INTO settlements (period_month, status, grid_kwh, invoice_kwh, created_at, "
        "usage_frozen_at, posted_at) VALUES (?, 'posted', ?, ?, ?, ?, ?)",
        (month, kwh, kwh, _NOW, _NOW, _NOW),
    )
    sid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO settlement_invoice_lines (settlement_id, description, allocation_method, "
        "amount_ore, amount_nok, created_at) VALUES (?, 'Strøm', 'consumption', ?, ?, ?)",
        (sid, line_ore, str(ore_to_nok(line_ore)), _NOW),
    )
    conn.execute(
        "INSERT INTO settlement_members (settlement_id, member_id, member_reference, full_name, "
        "is_active, participates_equal, consumption_kwh, session_count, balance_before_ore) "
        "VALUES (?, ?, 'M-100', 'Kari', 1, 0, ?, 1, 0)",
        (sid, member_id, kwh),
    )
    conn.commit()
    return sid


def _seed_payment(conn, member_id: int, amount_ore: int, value_date: str, ref: str) -> None:
    conn.execute(
        "INSERT INTO ledger_transactions (member_id, txn_type, amount_ore, amount_nok, "
        "currency, value_date, reference, recorded_at) "
        "VALUES (?, 'payment', ?, ?, 'NOK', ?, ?, ?)",
        (member_id, amount_ore, str(ore_to_nok(amount_ore)), value_date, ref, _NOW),
    )
    conn.commit()


def _add_member(conn, reference: str) -> int:
    cur = conn.execute(
        "INSERT INTO members (member_reference, full_name, join_date, created_at, updated_at) "
        "VALUES (?, 'Other', '2026-01-01', ?, ?)",
        (reference, _NOW, _NOW),
    )
    conn.commit()
    return int(cur.lastrowid)


def _by_month(body: dict) -> dict[str, dict]:
    return {row["month"]: row for row in body["months"]}


def test_window_is_six_months_ending_current_month(frozen_now, member_client):
    body = member_client.get("/api/me/history").json()
    assert [r["month"] for r in body["months"]] == [
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
    ]


def test_kwh_reported_per_month_including_current_unsettled_month(frozen_now, member_client):
    conn = member_client.app.state.db.connection
    _seed_session(conn, MY_ID, "2026-06", "30.000")
    _seed_session(conn, MY_ID, "2026-07", "20.000", sid="a")
    _seed_session(conn, MY_ID, "2026-07", "30.000", sid="b")
    _seed_session(conn, MY_ID, "2026-08", "10.000")  # current month, no settlement

    rows = _by_month(member_client.get("/api/me/history").json())
    assert rows["2026-06"]["consumption_kwh"] == "30.00"
    assert rows["2026-07"]["consumption_kwh"] == "50.00"
    assert rows["2026-07"]["session_count"] == 2
    assert rows["2026-08"]["consumption_kwh"] == "10.00"
    assert rows["2026-08"]["session_count"] == 1
    assert rows["2026-05"]["consumption_kwh"] == "0.00"
    assert rows["2026-05"]["session_count"] == 0


def test_charge_populated_only_for_posted_settlement_months(frozen_now, member_client):
    conn = member_client.app.state.db.connection
    _seed_session(conn, MY_ID, "2026-07", "50.000")
    _seed_session(conn, MY_ID, "2026-08", "10.000")
    _seed_posted_settlement(conn, "2026-07", MY_ID, "50.000", line_ore=12_345)

    rows = _by_month(member_client.get("/api/me/history").json())
    assert rows["2026-07"]["settled"] is True
    assert rows["2026-07"]["charge_nok"] == "123.45"
    assert rows["2026-07"]["charge_ore"] == 12_345
    # unsettled months carry no cost
    assert rows["2026-08"]["settled"] is False
    assert rows["2026-08"]["charge_nok"] is None
    assert rows["2026-08"]["charge_ore"] is None
    assert rows["2026-06"]["settled"] is False
    assert rows["2026-06"]["charge_nok"] is None


def test_balance_is_running_ledger_total_at_each_month_end(frozen_now, member_client):
    conn = member_client.app.state.db.connection
    _seed_payment(conn, MY_ID, 10_000, "2026-04-10", "p1")
    _seed_payment(conn, MY_ID, 5_000, "2026-06-20", "p2")

    rows = _by_month(member_client.get("/api/me/history").json())
    assert rows["2026-03"]["balance_end_ore"] == 0
    assert rows["2026-04"]["balance_end_ore"] == 10_000
    assert rows["2026-05"]["balance_end_ore"] == 10_000  # forward-filled, no activity
    assert rows["2026-06"]["balance_end_ore"] == 15_000
    assert rows["2026-06"]["balance_end_nok"] == "150.00"
    assert rows["2026-08"]["balance_end_ore"] == 15_000


def test_other_members_data_is_excluded(frozen_now, member_client):
    conn = member_client.app.state.db.connection
    other = _add_member(conn, "M-200")
    _seed_session(conn, other, "2026-07", "99.000")
    _seed_payment(conn, other, 999_00, "2026-05-01", "theirs")
    _seed_session(conn, MY_ID, "2026-07", "5.000")

    rows = _by_month(member_client.get("/api/me/history").json())
    assert rows["2026-07"]["consumption_kwh"] == "5.00"
    assert all(r["balance_end_ore"] == 0 for r in rows.values())


def test_months_query_param_is_honoured_and_clamped(frozen_now, member_client):
    body = member_client.get("/api/me/history?months=3").json()
    assert [r["month"] for r in body["months"]] == ["2026-06", "2026-07", "2026-08"]

    assert member_client.get("/api/me/history?months=0").status_code == 422
    assert member_client.get("/api/me/history?months=99").status_code == 422
