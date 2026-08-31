from __future__ import annotations

import json

from ladelaug_avregning.money import ore_to_nok

FETCH = {"X-Requested-With": "fetch"}
_NOW = "2026-01-01T00:00:00+00:00"


def _seed_settlement(conn, month, *, grid_kwh, members, equal_ore=0, consumption_ore=0):
    """members: list of (member_id, consumption_kwh, participates_equal)."""
    cur = conn.execute(
        "INSERT INTO settlements (period_month, status, grid_kwh, invoice_kwh, created_at, "
        "usage_frozen_at, posted_at) VALUES (?, 'posted', ?, ?, ?, ?, ?)",
        (month, str(grid_kwh), str(grid_kwh), _NOW, _NOW, _NOW),
    )
    sid = int(cur.lastrowid)
    for method, ore in (("equal", equal_ore), ("consumption", consumption_ore)):
        if ore:
            conn.execute(
                "INSERT INTO settlement_invoice_lines (settlement_id, description, "
                "allocation_method, amount_ore, amount_nok, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (sid, method, method, ore, str(ore_to_nok(ore)), _NOW),
            )
    for mid, kwh, pe in members:
        conn.execute(
            "INSERT INTO settlement_members (settlement_id, member_id, member_reference, "
            "full_name, is_active, participates_equal, consumption_kwh, session_count, "
            "balance_before_ore) VALUES (?, ?, ?, ?, 1, ?, ?, 0, 0)",
            (sid, mid, f"M{mid}", f"Name {mid}", 1 if pe else 0, str(kwh)),
        )
    conn.commit()
    return sid


def _seed_history(conn, member_id, *, months=("2026-04", "2026-05", "2026-06"), kwh=20):
    for month in months:
        _seed_settlement(
            conn, month, grid_kwh=100, consumption_ore=10_000, members=[(member_id, kwh, 0)]
        )


# --- admin: settings ------------------------------------------------


def test_settings_get_returns_seeded_defaults(admin_client):
    body = admin_client.get("/api/forecast/settings").json()
    assert body["buffer_months"] == 2.0
    assert body["notify_cooldown_days"] == 14
    assert body["lookback_settlements"] == 3
    assert body["rate_override_ore_per_kwh"] is None


def test_settings_put_updates_and_writes_one_audit_row(admin_client):
    out = admin_client.put(
        "/api/forecast/settings",
        json={"buffer_months": 3.0, "rate_override_ore_per_kwh": 210},
        headers=FETCH,
    )
    assert out.status_code == 200
    body = out.json()
    assert body["buffer_months"] == 3.0
    assert body["rate_override_ore_per_kwh"] == 210
    assert body["updated_at"] is not None

    rows = admin_client.app.state.db.connection.execute(
        "SELECT detail_json FROM audit_events WHERE event_type = 'forecast.settings_updated'"
    ).fetchall()
    assert len(rows) == 1
    detail = json.loads(rows[0]["detail_json"])
    assert detail["before"]["buffer_months"] == 2.0
    assert detail["after"]["buffer_months"] == 3.0
    assert detail["after"]["rate_override_ore_per_kwh"] == 210


def test_settings_put_rejects_bad_values(admin_client):
    assert (
        admin_client.put(
            "/api/forecast/settings", json={"buffer_months": 0}, headers=FETCH
        ).status_code
        == 422
    )
    assert (
        admin_client.put(
            "/api/forecast/settings", json={"lookback_settlements": 0}, headers=FETCH
        ).status_code
        == 422
    )


def test_settings_put_needs_fetch_header(admin_client):
    assert (
        admin_client.put("/api/forecast/settings", json={"buffer_months": 3.0}).status_code == 403
    )


def test_forecast_router_requires_admin(member_client):
    assert member_client.get("/api/forecast/settings").status_code == 403
    assert member_client.get("/api/forecast/members").status_code == 403
    assert (
        member_client.put(
            "/api/forecast/settings", json={"buffer_months": 3.0}, headers=FETCH
        ).status_code
        == 403
    )


def test_forecast_members_overview(admin_client, make_member):
    m1 = make_member(member_reference="F-1", email="f1@example.com")
    _seed_history(admin_client.app.state.db.connection, m1, kwh=20)

    body = admin_client.get("/api/forecast/members").json()
    entry = next(m for m in body["members"] if m["member_id"] == m1)
    assert entry["available"] is True
    assert entry["forecast_monthly_cost_ore"] == 2000
    assert entry["rate_source"] == "derived"


# --- member: /api/me/forecast + /api/me/consumption ---------------


def test_me_forecast_available(member_client):
    _seed_history(member_client.app.state.db.connection, 1, kwh=20)
    body = member_client.get("/api/me/forecast").json()
    assert body["member_id"] == 1
    assert body["available"] is True
    assert body["forecast_monthly_cost_ore"] == 2000
    assert body["recommended_minimum_ore"] == 4000


def test_me_forecast_unavailable_without_history(member_client):
    body = member_client.get("/api/me/forecast").json()
    assert body["available"] is False
    assert body["reason"] == "insufficient_history"
    assert body["forecast_monthly_cost_ore"] == 0


def test_me_consumption_defaults_to_current_oslo_month(frozen_now, member_client):
    conn = member_client.app.state.db.connection
    for sid, kwh in (("cs-1", "5.500"), ("cs-2", "4.000")):
        conn.execute(
            "INSERT INTO charging_sessions (zaptec_session_id, charger_zaptec_id, member_id, "
            "period_month, started_at, ended_at, energy_kwh, split_method, source, imported_at, "
            "updated_at) VALUES (?, 'z1', 1, '2026-08', '2026-08-10T10:00:00+00:00', "
            "'2026-08-10T12:00:00+00:00', ?, 'none', 'test', ?, ?)",
            (sid, kwh, _NOW, _NOW),
        )
    conn.commit()

    body = member_client.get("/api/me/consumption").json()
    assert body["member_id"] == 1
    assert body["month"] == "2026-08"
    assert body["consumption_kwh"] == "9.50"
    assert body["session_count"] == 2

    other = member_client.get("/api/me/consumption?month=2026-07").json()
    assert other["month"] == "2026-07"
    assert other["consumption_kwh"] == "0.00"
    assert other["session_count"] == 0


def test_me_consumption_rejects_bad_month(member_client):
    assert member_client.get("/api/me/consumption?month=nope").status_code == 422
