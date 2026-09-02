from __future__ import annotations

from decimal import Decimal

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.zaptec.client import ZaptecIntervalPoint, ZaptecSession

FETCH = {"X-Requested-With": "fetch"}
TZ = "Europe/Oslo"


def _session(sid, charger_zid, start, end, energy, points=None):
    return ZaptecSession(
        session_id=sid,
        charger_zaptec_id=charger_zid,
        device_id="d",
        started_at=start,
        ended_at=end,
        energy_kwh=Decimal(str(energy)),
        user_id="u",
        user_full_name="Kari",
        energy_details=[
            ZaptecIntervalPoint(timestamp=ts, energy_kwh=Decimal(str(e)))
            for ts, e in (points or [])
        ],
        raw={"Id": sid},
    )


async def _member(db, ref):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=ref,
        email=None,
        join_date="2026-01-01",
        actor=AuditContext.system(),
    )
    return int(row["id"])


async def _charger(db, name, zid):
    return await ChargerRepo(db).create(name=name, zaptec_id=zid, actor=AuditContext.system())


# --- periods helpers -------------------------------------------------


def test_month_key_uses_local_zone():
    # 2026-06-30 23:30 UTC is 2026-07-01 01:30 in Oslo (CEST, +02:00)
    assert periods.month_key("2026-06-30T23:30:00+00:00", TZ) == "2026-07"
    assert periods.month_key("2026-06-30T20:00:00+00:00", TZ) == "2026-06"


def test_split_across_months_single_and_cross():
    one = periods.split_across_months("2026-07-05T10:00:00+00:00", "2026-07-05T12:00:00+00:00", TZ)
    assert [p[0] for p in one] == ["2026-07"]

    two = periods.split_across_months("2026-07-31T20:00:00+00:00", "2026-08-01T04:00:00+00:00", TZ)
    assert [p[0] for p in two] == ["2026-07", "2026-08"]
    # boundary is 2026-08-01T00:00 local == 2026-07-31T22:00Z
    assert two[0][2] == two[1][1]


def test_month_range_and_add_month():
    assert periods.add_month("2026-12") == "2027-01"
    assert periods.month_range("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]


# --- import --------------------------------------------------------


async def test_single_month_session_resolves_member_and_is_idempotent(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )
    repo = ChargingRepo(db, tz=TZ)

    s = _session("s-1", "z-1", "2026-07-05T10:00:00+00:00", "2026-07-05T12:00:00+00:00", "8.4")
    r1 = await repo.import_sessions([s], actor=AuditContext.system())
    assert r1["rows_inserted"] == 1 and r1["cross_month_sessions"] == 0

    row = db.connection.execute("SELECT * FROM charging_sessions").fetchone()
    assert row["member_id"] == m1 and row["period_month"] == "2026-07"
    assert Decimal(row["energy_kwh"]) == Decimal("8.400")
    assert row["split_method"] == "none"

    r2 = await repo.import_sessions([s], actor=AuditContext.system())
    assert r2["rows_inserted"] == 0 and r2["rows_updated"] == 1
    assert db.connection.execute("SELECT COUNT(*) FROM charging_sessions").fetchone()[0] == 1


async def test_session_energy_rounds_half_up_like_the_zaptec_report(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )
    repo = ChargingRepo(db, tz=TZ)

    # 3-dp Energy values from the API; the exact half-way case (…405) must round
    # UP to 34.41 (as Zaptec's charge-history report does), not half-even to 34.40.
    sessions = [
        _session("s-1", "z-1", "2026-07-05T10:00:00+00:00", "2026-07-05T12:00:00+00:00", "34.405"),
        _session("s-2", "z-1", "2026-07-06T10:00:00+00:00", "2026-07-06T12:00:00+00:00", "0.015"),
        _session("s-3", "z-1", "2026-07-07T10:00:00+00:00", "2026-07-07T12:00:00+00:00", "11.342"),
    ]
    await repo.import_sessions(sessions, actor=AuditContext.system())

    stored = {
        r["zaptec_session_id"]: r["energy_kwh"]
        for r in db.connection.execute(
            "SELECT zaptec_session_id, energy_kwh FROM charging_sessions"
        )
    }
    assert stored["s-1"] == "34.41"
    assert stored["s-2"] == "0.02"
    assert stored["s-3"] == "11.34"
    # 34.41 + 0.02 + 11.34
    assert repo.total_kwh("2026-07") == Decimal("45.77")
    assert repo.consumption_by_member("2026-07") == {m1: Decimal("45.77")}


async def test_cross_month_split_prefers_interval_data(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )
    repo = ChargingRepo(db, tz=TZ)

    # session spans the Jul/Aug boundary; interval points say 3 kWh in Jul, 7 in Aug
    s = _session(
        "s-2",
        "z-1",
        "2026-07-31T20:00:00+00:00",
        "2026-08-01T04:00:00+00:00",
        "10",
        points=[
            ("2026-07-31T20:00:00+00:00", "3"),
            ("2026-08-01T00:00:00+00:00", "7"),
        ],
    )
    await repo.import_sessions([s], actor=AuditContext.system())
    rows = {
        r["period_month"]: r
        for r in db.connection.execute("SELECT * FROM charging_sessions ORDER BY period_month")
    }
    assert set(rows) == {"2026-07", "2026-08"}
    assert Decimal(rows["2026-07"]["energy_kwh"]) == Decimal("3.000")
    assert Decimal(rows["2026-08"]["energy_kwh"]) == Decimal("7.000")
    assert rows["2026-07"]["split_method"] == "interval"
    # intervals stored too
    assert db.connection.execute("SELECT COUNT(*) FROM charging_intervals").fetchone()[0] == 2


async def test_session_detail_returns_month_parts_and_intervals(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )
    repo = ChargingRepo(db, tz=TZ)

    await repo.import_sessions(
        [
            _session(
                "s-detail",
                "z-1",
                "2026-07-31T20:00:00+00:00",
                "2026-08-01T04:00:00+00:00",
                "10",
                points=[
                    ("2026-07-31T20:00:00+00:00", "3"),
                    ("2026-08-01T00:00:00+00:00", "7"),
                ],
            )
        ],
        actor=AuditContext.system(),
    )

    detail = repo.session_detail("s-detail")
    assert detail is not None
    assert [p["period_month"] for p in detail["parts"]] == ["2026-07", "2026-08"]
    assert all(p["split_method"] == "interval" for p in detail["parts"])
    assert [i["interval_start"] for i in detail["intervals"]] == [
        "2026-07-31T20:00:00+00:00",
        "2026-08-01T00:00:00+00:00",
    ]
    assert detail["intervals"][0]["member_id"] == m1
    assert detail["intervals"][0]["period_month"] == "2026-07"

    assert repo.session_detail("no-such-session") is None


async def test_cross_month_split_falls_back_to_duration(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )
    repo = ChargingRepo(db, tz=TZ)

    # 2026-07-31 22:00Z .. 2026-08-01 02:00Z  -> boundary at 2026-07-31 22:00Z (00:00 local)
    # so the whole session is actually in August locally; use an earlier start.
    s = _session("s-3", "z-1", "2026-07-31T20:00:00+00:00", "2026-08-01T02:00:00+00:00", "12")
    await repo.import_sessions([s], actor=AuditContext.system())
    rows = {
        r["period_month"]: Decimal(r["energy_kwh"])
        for r in db.connection.execute("SELECT * FROM charging_sessions")
    }
    assert set(rows) == {"2026-07", "2026-08"}
    assert sum(rows.values()) == Decimal("12.000")
    assert all(
        r["split_method"] == "duration"
        for r in db.connection.execute("SELECT split_method FROM charging_sessions")
    )


async def test_unassigned_consumption_and_reresolve(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    repo = ChargingRepo(db, tz=TZ)

    s = _session("s-4", "z-1", "2026-07-10T10:00:00+00:00", "2026-07-10T12:00:00+00:00", "5")
    await repo.import_sessions([s], actor=AuditContext.system())

    un = repo.unassigned_consumption("2026-07")
    assert len(un) == 1 and un[0]["charger_zaptec_id"] == "z-1"
    assert repo.unassigned_total_kwh("2026-07") == Decimal("5.000")
    assert repo.consumption_by_member("2026-07") == {}

    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-07-01", actor=AuditContext.system()
    )
    res = await repo.reresolve_members("2026-07", actor=AuditContext.system())
    assert res["sessions_changed"] == 1
    assert repo.unassigned_consumption("2026-07") == []
    assert repo.consumption_by_member("2026-07") == {m1: Decimal("5.000")}


async def test_reresolve_backfills_charger_id_for_late_charger(db):
    # session imported before the charger row exists -> charger_id + member_id NULL
    repo = ChargingRepo(db, tz=TZ)
    s = _session("s-late", "z-1", "2026-08-10T10:00:00+00:00", "2026-08-10T12:00:00+00:00", "6")
    await repo.import_sessions([s], actor=AuditContext.system())
    row = db.connection.execute("SELECT charger_id, member_id FROM charging_sessions").fetchone()
    assert row["charger_id"] is None and row["member_id"] is None

    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-08-01", actor=AuditContext.system()
    )
    res = await repo.reresolve_members("2026-08", actor=AuditContext.system())
    assert res["sessions_changed"] == 1
    row = db.connection.execute("SELECT charger_id, member_id FROM charging_sessions").fetchone()
    assert row["charger_id"] == c["id"] and row["member_id"] == m1


async def test_reresolve_resolves_manual_charger_by_serial(db):
    m1 = await _member(db, "M1")
    manual = await ChargerRepo(db).create(
        name="146B", serial_no="ZPR333972", actor=AuditContext.system()
    )
    await ChargerRepo(db).assign(
        manual["id"], m1, effective_from="2026-08-01", actor=AuditContext.system()
    )
    repo = ChargingRepo(db, tz=TZ)
    s = ZaptecSession(
        session_id="s-serial",
        charger_zaptec_id="z-unknown",
        device_id="ZPR333972",
        started_at="2026-08-10T10:00:00+00:00",
        ended_at="2026-08-10T12:00:00+00:00",
        energy_kwh=Decimal("4.0"),
        user_id="u",
        user_full_name="Kari",
        energy_details=[],
        raw={"Id": "s-serial", "DeviceId": "ZPR333972"},
    )
    await repo.import_sessions([s], actor=AuditContext.system())
    row = db.connection.execute("SELECT charger_id, member_id FROM charging_sessions").fetchone()
    assert row["charger_id"] == manual["id"] and row["member_id"] == m1


async def test_reresolve_unresolved_skips_posted_months(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    repo = ChargingRepo(db, tz=TZ)
    await repo.import_sessions(
        [
            _session("p", "z-1", "2026-07-10T10:00:00+00:00", "2026-07-10T11:00:00+00:00", "2"),
            _session("q", "z-1", "2026-08-10T10:00:00+00:00", "2026-08-10T11:00:00+00:00", "3"),
        ],
        actor=AuditContext.system(),
    )
    db.connection.execute(
        "INSERT INTO settlements (period_month, status, created_at) "
        "VALUES ('2026-07', 'posted', '2026-08-01T00:00:00+00:00')"
    )
    db.connection.commit()
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )

    res = await repo.reresolve_unresolved(actor=AuditContext.system())
    assert res["months"] == ["2026-08"]
    assert repo.consumption_by_member("2026-07") == {}  # posted month left alone
    assert repo.consumption_by_member("2026-08") == {m1: Decimal("3.000")}


async def test_member_resolved_by_assignment_on_session_date(db):
    m1, m2 = await _member(db, "M1"), await _member(db, "M2")
    c = await _charger(db, "C1", "z-1")
    cr = ChargerRepo(db)
    await cr.assign(c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    await cr.assign(c["id"], m2, effective_from="2026-07-15", actor=AuditContext.system())
    repo = ChargingRepo(db, tz=TZ)

    await repo.import_sessions(
        [
            _session("a", "z-1", "2026-07-10T10:00:00+00:00", "2026-07-10T11:00:00+00:00", "2"),
            _session("b", "z-1", "2026-07-20T10:00:00+00:00", "2026-07-20T11:00:00+00:00", "3"),
        ],
        actor=AuditContext.system(),
    )
    assert repo.consumption_by_member("2026-07") == {m1: Decimal("2.000"), m2: Decimal("3.000")}


# --- routes ------------------------------------------------------------


def test_charging_routes(admin_client, make_member):
    m1 = make_member(member_reference="M1")
    admin_client.post("/api/chargers", json={"name": "C1", "zaptec_id": "z-1"}, headers=FETCH)
    cid = admin_client.get("/api/chargers").json()["chargers"][0]["id"]
    admin_client.post(
        f"/api/chargers/{cid}/assignments",
        json={"member_id": m1, "effective_from": "2026-07-01"},
        headers=FETCH,
    )
    # no data imported yet
    body = admin_client.get("/api/charging/consumption?month=2026-07").json()
    assert body["by_member"] == [] and body["total_kwh"] == "0.00"

    assert admin_client.get("/api/charging/consumption?month=nope").status_code == 422


async def test_session_detail_route(db, admin_client):
    m1 = await _member(db, "M1")
    c = await _charger(db, "C1", "z-1")
    await ChargerRepo(db).assign(
        c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system()
    )
    await ChargingRepo(db, tz=TZ).import_sessions(
        [
            _session(
                "s-route",
                "z-1",
                "2026-07-05T10:00:00+00:00",
                "2026-07-05T12:00:00+00:00",
                "8.4",
                points=[
                    ("2026-07-05T10:00:00+00:00", "4.4"),
                    ("2026-07-05T11:00:00+00:00", "4.0"),
                ],
            )
        ],
        actor=AuditContext.system(),
    )

    body = admin_client.get("/api/charging/sessions/s-route").json()
    assert body["zaptec_session_id"] == "s-route"
    assert len(body["parts"]) == 1
    assert len(body["intervals"]) == 2
    assert sum(Decimal(i["energy_kwh"]) for i in body["intervals"]) == Decimal("8.4")

    assert admin_client.get("/api/charging/sessions/does-not-exist").status_code == 404


def test_charging_routes_require_admin(member_client):
    assert member_client.get("/api/charging/consumption?month=2026-07").status_code == 403
    assert member_client.get("/api/charging/sessions/anything").status_code == 403
