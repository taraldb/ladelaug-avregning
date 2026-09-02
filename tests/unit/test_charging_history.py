"""GET /api/charging/history — the admin "Forbruk" page's rolling month strip.

Covers the window construction, the assigned/unassigned/grid kWh split (which must
reconcile), the grid-wide session count, and the settled-only fields
(``invoice_kwh`` / ``cost_per_kwh_nok``) that come from a posted settlement.
``ChargingRepo.session_count`` is unit-tested directly here too.
"""

from __future__ import annotations

from ladelaug_avregning.domain.charging import ChargingRepo

_NOW = "2026-01-01T00:00:00+00:00"


def _seed_session(
    conn,
    *,
    month: str,
    kwh: str,
    member_id: int | None,
    zid: str = "z1",
    sid: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO charging_sessions (zaptec_session_id, charger_zaptec_id, member_id, "
        "period_month, started_at, ended_at, energy_kwh, split_method, source, imported_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'none', 'test', ?, ?)",
        (
            sid or f"cs-{zid}-{member_id}-{month}",
            zid,
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


def _seed_posted_settlement(conn, *, month: str, invoice_kwh: str, invoice_total_nok: str) -> None:
    conn.execute(
        "INSERT INTO settlements (period_month, status, grid_kwh, invoice_kwh, "
        "invoice_total_nok, created_at, usage_frozen_at, posted_at) "
        "VALUES (?, 'posted', ?, ?, ?, ?, ?, ?)",
        (month, invoice_kwh, invoice_kwh, invoice_total_nok, _NOW, _NOW, _NOW),
    )
    conn.commit()


def _by_month(body: dict) -> dict[str, dict]:
    return {row["month"]: row for row in body["months"]}


def test_session_count_is_grid_wide(db, make_member):
    m1 = make_member(member_reference="H1")
    _seed_session(db.connection, month="2026-07", kwh="5.00", member_id=m1)
    _seed_session(db.connection, month="2026-07", kwh="3.00", member_id=None)
    _seed_session(db.connection, month="2026-08", kwh="1.00", member_id=m1)

    repo = ChargingRepo(db, tz="Europe/Oslo")
    assert repo.session_count("2026-07") == 2
    assert repo.session_count("2026-08") == 1
    assert repo.session_count("2026-09") == 0


def test_history_window_and_reconciled_totals(frozen_now, db, admin_client, make_member):
    m1 = make_member(member_reference="H2")
    _seed_session(db.connection, month="2026-07", kwh="10.00", member_id=m1)
    _seed_session(db.connection, month="2026-07", kwh="4.00", member_id=None, zid="z2")
    _seed_session(db.connection, month="2026-08", kwh="6.00", member_id=m1)

    body = admin_client.get("/api/charging/history?months=3").json()
    assert [r["month"] for r in body["months"]] == ["2026-06", "2026-07", "2026-08"]

    rows = _by_month(body)
    assert rows["2026-06"]["grid_kwh"] == "0.00"
    assert rows["2026-06"]["session_count"] == 0

    jul = rows["2026-07"]
    assert jul["assigned_kwh"] == "10.00"
    assert jul["unassigned_kwh"] == "4.00"
    assert jul["grid_kwh"] == "14.00"
    assert jul["session_count"] == 2
    assert jul["settled"] is False
    assert jul["invoice_kwh"] is None
    assert jul["cost_per_kwh_nok"] is None

    aug = rows["2026-08"]
    assert aug["assigned_kwh"] == "6.00"
    assert aug["unassigned_kwh"] == "0.00"
    assert aug["grid_kwh"] == "6.00"


def test_history_settled_month_carries_invoice_and_rate(frozen_now, db, admin_client, make_member):
    m1 = make_member(member_reference="H3")
    _seed_session(db.connection, month="2026-07", kwh="10.00", member_id=m1)
    _seed_posted_settlement(
        db.connection, month="2026-07", invoice_kwh="100.00", invoice_total_nok="250.00"
    )

    rows = _by_month(admin_client.get("/api/charging/history?months=3").json())
    jul = rows["2026-07"]
    assert jul["settled"] is True
    assert jul["invoice_kwh"] == "100.00"
    assert jul["invoice_total_nok"] == "250.00"
    assert jul["cost_per_kwh_nok"] == "2.5000"

    assert rows["2026-08"]["settled"] is False
    assert rows["2026-08"]["invoice_total_nok"] is None
    assert rows["2026-08"]["cost_per_kwh_nok"] is None


def test_history_months_out_of_bounds_is_422(admin_client):
    assert admin_client.get("/api/charging/history?months=0").status_code == 422
    assert admin_client.get("/api/charging/history?months=25").status_code == 422


def test_history_requires_admin(member_client):
    assert member_client.get("/api/charging/history?months=6").status_code == 403
