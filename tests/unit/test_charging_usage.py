"""``ChargingRepo.usage_timeseries`` / ``GET /api/charging/usage`` — the admin
"Bruk" hourly chart: average power and active-charging vs. plugged-in-idle
session counts, built from sparse ``charging_intervals`` points (Zaptec omits
rows during idle stretches rather than reporting zero-energy ones)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ladelaug_avregning.domain.charging import ChargingRepo

_NOW = "2026-01-01T00:00:00+00:00"
TZ = "Europe/Oslo"


def _seed_session(conn, *, sid: str, zid: str, started_at: str, ended_at: str) -> None:
    conn.execute(
        "INSERT INTO charging_sessions (zaptec_session_id, charger_zaptec_id, member_id, "
        "period_month, started_at, ended_at, energy_kwh, split_method, source, imported_at, "
        "updated_at) VALUES (?, ?, NULL, '2026-08', ?, ?, '2.50', 'none', 'test', ?, ?)",
        (sid, zid, started_at, ended_at, _NOW, _NOW),
    )
    conn.commit()


def _seed_interval(conn, *, zid: str, sid: str, ts: str, kwh: str) -> None:
    conn.execute(
        "INSERT INTO charging_intervals (charger_zaptec_id, member_id, period_month, "
        "interval_start, energy_kwh, source_session_zaptec_id, imported_at) "
        "VALUES (?, NULL, '2026-08', ?, ?, ?, ?)",
        (zid, ts, kwh, sid, _NOW),
    )
    conn.commit()


def _local(y, m, d, h) -> str:
    return datetime(y, m, d, h, tzinfo=ZoneInfo(TZ)).isoformat()


def test_hourly_buckets_split_charging_from_idle(frozen_now, db):
    """A session with a real 9-hour idle gap (from the captured Zaptec data
    shape: a single zero-energy point closes the gap, not a row per 15 min)
    reads as charging while intervals carry energy, idle everywhere else it's
    merely plugged in, and not present at all once it ends."""
    _seed_session(
        db.connection,
        sid="s1",
        zid="z1",
        started_at="2026-08-30T08:00:00+00:00",
        ended_at="2026-08-30T11:00:00+00:00",
    )
    # Local (Oslo, UTC+2 in August): session spans 10:00 -> 13:00.
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-30T08:00:00+00:00", kwh="0.00")
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-30T08:15:00+00:00", kwh="1.20")
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-30T08:30:00+00:00", kwh="1.30")
    # Gap: nothing reported between 08:30 and 10:45 UTC — the idle stretch.
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-30T10:45:00+00:00", kwh="0.00")
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-30T11:00:00+00:00", kwh="0.00")

    repo = ChargingRepo(db, tz=TZ)
    by_hour = {row["hour"]: row for row in repo.usage_timeseries(hours=24)}

    charging_hour = by_hour[_local(2026, 8, 30, 10)]
    assert charging_hour["avg_power_kw"] == "2.50"
    assert charging_hour["charging_sessions"] == 1
    assert charging_hour["idle_sessions"] == 0

    idle_hour = by_hour[_local(2026, 8, 30, 11)]
    assert idle_hour["avg_power_kw"] == "0.00"
    assert idle_hour["charging_sessions"] == 0
    assert idle_hour["idle_sessions"] == 1

    last_hour = by_hour[_local(2026, 8, 30, 12)]
    assert last_hour["avg_power_kw"] == "0.00"
    assert last_hour["charging_sessions"] == 0
    assert last_hour["idle_sessions"] == 1

    after_end = by_hour[_local(2026, 8, 30, 13)]
    assert after_end["charging_sessions"] == 0
    assert after_end["idle_sessions"] == 0


def test_usage_endpoint_defaults_and_validates_hours(frozen_now, admin_client):
    body = admin_client.get("/api/charging/usage").json()
    assert len(body["hours"]) == 168

    body = admin_client.get("/api/charging/usage?hours=24").json()
    assert len(body["hours"]) == 24

    assert admin_client.get("/api/charging/usage?hours=0").status_code == 422
    assert admin_client.get("/api/charging/usage?hours=721").status_code == 422


def test_usage_timeseries_end_pages_the_window_back(frozen_now, db):
    """`end` lets the window be pinned to a past instant instead of always
    trailing from "now" — the admin chart's back/forward paging."""
    _seed_session(
        db.connection,
        sid="s1",
        zid="z1",
        started_at="2026-08-20T10:00:00+00:00",
        ended_at="2026-08-20T11:00:00+00:00",
    )
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-20T10:00:00+00:00", kwh="3.00")

    repo = ChargingRepo(db, tz=TZ)

    # Trailing from "now" (2026-08-30T12:00 UTC, via frozen_now) doesn't reach back this far.
    assert all(r["avg_power_kw"] == "0.00" for r in repo.usage_timeseries(hours=24))

    # Local 12:00 on 2026-08-20 (UTC 10:00 + Oslo's +2h) sits inside a 24h window
    # ending at local 13:00 that same day.
    rows = repo.usage_timeseries(hours=24, end=_local(2026, 8, 20, 13))
    by_hour = {r["hour"]: r for r in rows}
    assert by_hour[_local(2026, 8, 20, 12)]["avg_power_kw"] == "3.00"
    assert len(rows) == 24


def test_usage_endpoint_month_overrides_hours(frozen_now, db, admin_client):
    _seed_session(
        db.connection,
        sid="s1",
        zid="z1",
        started_at="2026-08-09T18:00:00+00:00",
        ended_at="2026-08-09T19:00:00+00:00",
    )
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-09T18:00:00+00:00", kwh="7.50")

    body = admin_client.get("/api/charging/usage?month=2026-08&hours=24").json()
    by_hour = {row["hour"]: row for row in body["hours"]}
    assert len(body["hours"]) == 31 * 24
    assert by_hour[_local(2026, 8, 9, 20)]["avg_power_kw"] == "7.50"

    assert admin_client.get("/api/charging/usage?month=bad").status_code == 422


def test_usage_endpoint_validates_end(frozen_now, admin_client):
    assert admin_client.get("/api/charging/usage?end=not-a-date").status_code == 422


def test_top_hours_ranks_by_power_and_excludes_idle_only_hours(frozen_now, db):
    _seed_session(
        db.connection,
        sid="s1",
        zid="z1",
        started_at="2026-08-09T16:00:00+00:00",
        ended_at="2026-08-09T17:00:00+00:00",
    )
    _seed_session(
        db.connection,
        sid="s2",
        zid="z1",
        started_at="2026-08-09T18:00:00+00:00",  # local 09.08 kl. 20 -> highest.
        ended_at="2026-08-09T19:00:00+00:00",
    )
    _seed_session(
        db.connection,
        sid="s3",
        zid="z1",
        started_at="2026-08-10T18:00:00+00:00",  # never charges — idle only, excluded.
        ended_at="2026-08-10T19:00:00+00:00",
    )
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-09T16:00:00+00:00", kwh="3.00")
    _seed_interval(db.connection, zid="z1", sid="s2", ts="2026-08-09T18:00:00+00:00", kwh="7.50")
    _seed_interval(db.connection, zid="z1", sid="s3", ts="2026-08-10T18:00:00+00:00", kwh="0.00")

    repo = ChargingRepo(db, tz=TZ)

    top = repo.top_hours("2026-08", limit=10)
    assert [r["avg_power_kw"] for r in top] == ["7.50", "3.00"]
    assert top[0]["hour"] == _local(2026, 8, 9, 20)  # UTC 18:00 -> Oslo (CEST) 20:00.

    assert repo.top_hours("2026-08", limit=1) == top[:1]
    assert repo.top_hours("2026-07") == []


def test_peak_hours_endpoint_defaults_to_current_month(frozen_now, db, admin_client):
    _seed_session(
        db.connection,
        sid="s1",
        zid="z1",
        started_at="2026-08-09T18:00:00+00:00",
        ended_at="2026-08-09T19:00:00+00:00",
    )
    _seed_interval(db.connection, zid="z1", sid="s1", ts="2026-08-09T18:00:00+00:00", kwh="7.50")

    body = admin_client.get("/api/charging/peak-hours").json()  # frozen_now -> August.
    assert body["month"] == "2026-08"
    assert [r["avg_power_kw"] for r in body["hours"]] == ["7.50"]

    body = admin_client.get("/api/charging/peak-hours?month=2026-07&limit=5").json()
    assert body["month"] == "2026-07"
    assert body["hours"] == []

    assert admin_client.get("/api/charging/peak-hours?limit=0").status_code == 422
