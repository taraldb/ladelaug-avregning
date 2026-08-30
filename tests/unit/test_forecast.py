from __future__ import annotations

from decimal import Decimal

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.money import ore_to_nok

SYS = AuditContext.system()
_NOW = "2026-01-01T00:00:00+00:00"


async def _member(db, ref, *, active=True, participates=None):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=f"Name {ref}",
        email=f"{ref.lower()}@example.com",
        join_date="2026-01-01",
        actor=SYS,
    )
    mid = int(row["id"])
    if active:
        await MemberRepo(db).set_status(mid, "active", effective_from="2026-01-01", actor=SYS)
    if participates is not None:
        await MemberRepo(db).set_participation(
            mid, participates, effective_from="2026-01-01", actor=SYS
        )
    return mid


def _seed_settlement(db, month, *, grid_kwh, members, equal_ore=0, consumption_ore=0):
    """members: list of (member_id, consumption_kwh, participates_equal)."""
    conn = db.connection
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


async def _pay(db, member_id, nok):
    await LedgerRepo(db).record_payment(
        member_id=member_id, amount=Decimal(nok), value_date="2026-06-01", reference=None, actor=SYS
    )


# --- rate derivation -------------------------------------------------


async def test_rate_is_mean_of_historical_consumption_line_over_grid_kwh(db):
    m1 = await _member(db, "R-1")
    for month, kwh in (("2026-04", 10), ("2026-05", 20), ("2026-06", 30)):
        _seed_settlement(db, month, grid_kwh=100, consumption_ore=10_000, members=[(m1, kwh, 0)])

    fc = ForecastRepo(db).member_forecast(m1)
    assert fc["available"] is True
    assert fc["rate_source"] == "derived"
    assert fc["rate_ore_per_kwh"] == "100"
    assert fc["forecast_kwh"] == "20"
    # 20 kWh * 100 øre, no equal component
    assert fc["forecast_monthly_cost_ore"] == 2000
    assert fc["equal_share_ore"] == 0


async def test_admin_rate_override_wins_over_derived_rate(db):
    m1 = await _member(db, "O-1")
    for month in ("2026-04", "2026-05", "2026-06"):
        _seed_settlement(db, month, grid_kwh=100, consumption_ore=10_000, members=[(m1, 4, 0)])
    await ForecastRepo(db).update_settings(actor=SYS, rate_override_ore_per_kwh=250)

    fc = ForecastRepo(db).member_forecast(m1)
    assert fc["rate_source"] == "override"
    assert fc["rate_ore_per_kwh"] == "250"
    assert fc["forecast_monthly_cost_ore"] == 4 * 250


# --- availability --------------------------------------------------


async def test_fewer_than_lookback_postings_is_unavailable(db):
    m1 = await _member(db, "H-1")
    for month in ("2026-05", "2026-06"):  # only 2, default lookback is 3
        _seed_settlement(db, month, grid_kwh=100, consumption_ore=10_000, members=[(m1, 10, 0)])
    fc = ForecastRepo(db).member_forecast(m1)
    assert fc["available"] is False
    assert fc["reason"] == "insufficient_history"
    assert fc["forecast_monthly_cost_ore"] == 0


async def test_no_positive_grid_kwh_and_no_override_is_unavailable(db):
    m1 = await _member(db, "G-1")
    for month in ("2026-04", "2026-05", "2026-06"):
        _seed_settlement(db, month, grid_kwh=0, consumption_ore=10_000, members=[(m1, 10, 0)])
    fc = ForecastRepo(db).member_forecast(m1)
    assert fc["available"] is False
    assert fc["reason"] == "no_grid_kwh"


async def test_override_makes_forecast_available_without_grid_kwh(db):
    m1 = await _member(db, "GO-1")
    for month in ("2026-04", "2026-05", "2026-06"):
        _seed_settlement(db, month, grid_kwh=0, members=[(m1, 10, 0)])
    await ForecastRepo(db).update_settings(actor=SYS, rate_override_ore_per_kwh=200)

    fc = ForecastRepo(db).member_forecast(m1)
    assert fc["available"] is True
    assert fc["forecast_monthly_cost_ore"] == 10 * 200


# --- equal-cost share --------------------------------------------


async def test_equal_share_counted_only_when_member_currently_participates(db):
    m_in = await _member(db, "E-IN")
    m_out = await _member(db, "E-OUT", participates=False)
    m_fill = await _member(db, "E-FILL")
    for month in ("2026-04", "2026-05", "2026-06"):
        _seed_settlement(
            db,
            month,
            grid_kwh=100,
            consumption_ore=10_000,
            equal_ore=30_000,
            members=[(m_in, 5, 1), (m_out, 5, 1), (m_fill, 5, 1)],
        )

    repo = ForecastRepo(db)
    # 30000 øre / 3 equal participants = 10000 øre equal share (mean over 3 months)
    assert repo.history_stats()["equal_share_ore"] == 10_000

    fc_in = repo.member_forecast(m_in)
    fc_out = repo.member_forecast(m_out)
    # consumption: 5 kWh * 100 øre = 500 øre
    assert fc_in["equal_share_ore"] == 10_000
    assert fc_in["forecast_monthly_cost_ore"] == 500 + 10_000
    assert fc_out["equal_share_ore"] == 0
    assert fc_out["forecast_monthly_cost_ore"] == 500


# --- recommended minimum + severity -----------------------------


async def test_recommended_minimum_is_cost_times_buffer(db):
    m1 = await _member(db, "B-1")
    for month in ("2026-04", "2026-05", "2026-06"):
        _seed_settlement(db, month, grid_kwh=100, consumption_ore=10_000, members=[(m1, 20, 0)])
    repo = ForecastRepo(db)
    assert repo.member_forecast(m1)["recommended_minimum_ore"] == 2000 * 2  # default buffer 2.0

    await repo.update_settings(actor=SYS, buffer_months=2.5)
    fc = repo.member_forecast(m1)
    assert fc["forecast_monthly_cost_ore"] == 2000
    assert fc["recommended_minimum_ore"] == 5000


@pytest.mark.parametrize(
    ("paid_nok", "low_balance", "severity"),
    [
        ("40.00", False, None),  # balance == recommended minimum (4000 øre)
        ("39.99", True, "low"),  # below minimum, still covers next month
        ("20.00", True, "low"),  # balance == monthly cost (2000 øre)
        ("19.99", True, "critical"),  # cannot cover next month
    ],
)
async def test_low_balance_and_severity_boundaries(db, paid_nok, low_balance, severity):
    m1 = await _member(db, f"S-{paid_nok}")
    for month in ("2026-04", "2026-05", "2026-06"):
        _seed_settlement(db, month, grid_kwh=100, consumption_ore=10_000, members=[(m1, 20, 0)])
    await _pay(db, m1, paid_nok)

    fc = ForecastRepo(db).member_forecast(m1)
    assert fc["forecast_monthly_cost_ore"] == 2000
    assert fc["recommended_minimum_ore"] == 4000
    assert fc["low_balance"] is low_balance
    assert fc["severity"] == severity


async def test_forecast_money_is_exact_integer_ore(db):
    m1 = await _member(db, "X-1")
    for month, kwh in (("2026-04", 10), ("2026-05", 10), ("2026-06", 11)):
        _seed_settlement(db, month, grid_kwh=100, consumption_ore=10_000, members=[(m1, kwh, 0)])
    fc = ForecastRepo(db).member_forecast(m1)
    # mean 31/3 kWh * 100 øre = 1033.333... -> ROUND_HALF_EVEN -> 1033
    assert fc["forecast_monthly_cost_ore"] == 1033
    assert fc["recommended_minimum_ore"] == 2066
    for key in (
        "equal_share_ore",
        "forecast_monthly_cost_ore",
        "recommended_minimum_ore",
        "balance_ore",
        "recommended_topup_ore",
    ):
        assert isinstance(fc[key], int)


# --- settings validation ---------------------------------------


async def test_update_settings_rejects_bad_values_and_unknown_fields(db):
    repo = ForecastRepo(db)
    with pytest.raises(DomainError) as ei:
        await repo.update_settings(actor=SYS, buffer_months=0)
    assert ei.value.code == "bad_buffer"

    with pytest.raises(DomainError) as ei:
        await repo.update_settings(actor=SYS, lookback_settlements=0)
    assert ei.value.code == "bad_lookback"

    with pytest.raises(DomainError) as ei:
        await repo.update_settings(actor=SYS, rate_override_ore_per_kwh=-5)
    assert ei.value.code == "bad_rate"

    with pytest.raises(DomainError) as ei:
        await repo.update_settings(actor=SYS, nonsense=1)
    assert ei.value.code == "unknown_field"


async def test_update_settings_writes_one_audit_row_with_before_after(db):
    await ForecastRepo(db).update_settings(actor=SYS, buffer_months=3.0, notify_cooldown_days=30)
    rows = db.connection.execute(
        "SELECT detail_json FROM audit_events WHERE event_type = 'forecast.settings_updated'"
    ).fetchall()
    assert len(rows) == 1
    import json

    detail = json.loads(rows[0]["detail_json"])
    assert detail["before"]["buffer_months"] == 2.0
    assert detail["after"]["buffer_months"] == 3.0
    assert detail["after"]["notify_cooldown_days"] == 30
