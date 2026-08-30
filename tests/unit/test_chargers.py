from __future__ import annotations

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError, NotFoundError

FETCH = {"X-Requested-With": "fetch"}


async def _charger(db, name="C-1", **kw):
    return await ChargerRepo(db).create(name=name, actor=AuditContext.system(), **kw)


async def _member(db, ref):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=ref,
        email=None,
        join_date="2026-01-01",
        actor=AuditContext.system(),
    )
    return int(row["id"])


# --- ChargerRepo: records --------------------------------------------------


async def test_create_writes_row_and_audit(db):
    row = await _charger(db, name="Garage 1", serial_no="ZAP-001")
    assert row["name"] == "Garage 1" and row["is_active"] == 1
    event = db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = 'charger.created'"
    ).fetchone()
    assert event["entity_id"] == str(row["id"])


async def test_duplicate_zaptec_id_rejected(db):
    await _charger(db, name="A", zaptec_id="z-1")
    with pytest.raises(DomainError) as ei:
        await _charger(db, name="B", zaptec_id="z-1")
    assert ei.value.code == "zaptec_id_taken"


async def test_update_changes_only_given_fields(db):
    row = await _charger(db, name="A", serial_no="s1")
    updated = await ChargerRepo(db).update(
        row["id"], name="A2", is_active=False, actor=AuditContext.system()
    )
    assert updated["name"] == "A2" and updated["serial_no"] == "s1" and updated["is_active"] == 0


async def test_upsert_from_zaptec_is_idempotent(db):
    repo = ChargerRepo(db)
    kw = {
        "zaptec_id": "z-9",
        "name": "Zap 9",
        "serial_no": "ZS9",
        "installation_zaptec_id": "inst-1",
        "circuit_zaptec_id": "cir-1",
        "device_type": "Pro",
        "is_active": True,
        "raw": {"Id": "z-9"},
        "actor": AuditContext.system(),
    }
    _, created = await repo.upsert_from_zaptec(**kw)
    assert created is True
    row2, created2 = await repo.upsert_from_zaptec(**{**kw, "name": "Zap 9 renamed"})
    assert created2 is False and row2["name"] == "Zap 9 renamed"
    assert len(repo.list()) == 1


# --- ChargerRepo: assignments (US-302 / US-303) --------------------------


async def test_assign_then_reassign_closes_open_row(db):
    m1, m2 = await _member(db, "M1"), await _member(db, "M2")
    c = await _charger(db)
    repo = ChargerRepo(db)
    await repo.assign(c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    await repo.assign(c["id"], m2, effective_from="2026-06-01", actor=AuditContext.system())

    hist = repo.assignments(c["id"])
    assert len(hist) == 2
    assert sum(1 for h in hist if h["effective_to"] is None) == 1
    assert repo.assignment_on(c["id"], "2026-03-01") == m1
    assert repo.assignment_on(c["id"], "2026-07-01") == m2


async def test_assign_same_member_rejected(db):
    m1 = await _member(db, "M1")
    c = await _charger(db)
    repo = ChargerRepo(db)
    await repo.assign(c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    with pytest.raises(DomainError) as ei:
        await repo.assign(c["id"], m1, effective_from="2026-02-01", actor=AuditContext.system())
    assert ei.value.code == "already_assigned"


async def test_backdated_reassignment_rejected(db):
    m1, m2 = await _member(db, "M1"), await _member(db, "M2")
    c = await _charger(db)
    repo = ChargerRepo(db)
    await repo.assign(c["id"], m1, effective_from="2026-06-01", actor=AuditContext.system())
    with pytest.raises(DomainError) as ei:
        await repo.assign(c["id"], m2, effective_from="2026-01-01", actor=AuditContext.system())
    assert ei.value.code == "backdated"


async def test_unassign_closes_row_and_needs_open_row(db):
    m1 = await _member(db, "M1")
    c = await _charger(db)
    repo = ChargerRepo(db)
    with pytest.raises(DomainError) as ei:
        await repo.unassign(c["id"], effective_to="2026-06-01", actor=AuditContext.system())
    assert ei.value.code == "not_assigned"

    await repo.assign(c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    await repo.unassign(c["id"], effective_to="2026-06-01", actor=AuditContext.system())
    assert repo.assignment_on(c["id"], "2026-07-01") is None
    assert repo.assignment_on(c["id"], "2026-03-01") == m1


async def test_member_may_hold_several_chargers_at_once(db):
    m1 = await _member(db, "M1")
    c1, c2 = await _charger(db, name="C1"), await _charger(db, name="C2")
    repo = ChargerRepo(db)
    await repo.assign(c1["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    await repo.assign(c2["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    assert {c["id"] for c in repo.member_chargers(m1, "2026-02-01")} == {c1["id"], c2["id"]}


async def test_zaptec_assignment_map_and_unassigned(db):
    m1 = await _member(db, "M1")
    c1 = await _charger(db, name="C1", zaptec_id="z-1")
    c2 = await _charger(db, name="C2", zaptec_id="z-2")
    repo = ChargerRepo(db)
    await repo.assign(c1["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())
    assert repo.zaptec_assignment_map("2026-02-01") == {"z-1": m1}
    assert repo.unassigned_charger_ids("2026-02-01") == {c2["id"]}


def _seed_session(db, charger_id, *, zaptec_id="z-x"):
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_id, charger_zaptec_id, period_month, started_at, "
        " energy_kwh, source, imported_at, updated_at) "
        "VALUES ('s-1', ?, ?, '2026-08', '2026-08-10T10:00:00+00:00', '5.0', 'zaptec', "
        "'2026-08-11T00:00:00+00:00', '2026-08-11T00:00:00+00:00')",
        (charger_id, zaptec_id),
    )
    db.connection.commit()


async def test_delete_manual_charger_cascades_assignments(db):
    m1 = await _member(db, "M1")
    c = await _charger(db, name="Dup")
    repo = ChargerRepo(db)
    await repo.assign(c["id"], m1, effective_from="2026-01-01", actor=AuditContext.system())

    await repo.delete(c["id"], actor=AuditContext.system())

    assert repo.get(c["id"]) is None
    assert repo.assignments(c["id"]) == []
    event = db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = 'charger.deleted'"
    ).fetchone()
    assert event["entity_id"] == str(c["id"])


async def test_delete_blocked_when_usage_exists(db):
    c = await _charger(db, name="Used")
    _seed_session(db, c["id"])
    with pytest.raises(DomainError) as ei:
        await ChargerRepo(db).delete(c["id"], actor=AuditContext.system())
    assert ei.value.code == "charger_has_usage" and ei.value.status == 422
    assert ChargerRepo(db).get(c["id"]) is not None


async def test_delete_zaptec_charger_rejected(db):
    c = await _charger(db, name="Z", zaptec_id="z-1")
    with pytest.raises(DomainError) as ei:
        await ChargerRepo(db).delete(c["id"], actor=AuditContext.system())
    assert ei.value.code == "zaptec_charger"


async def test_delete_unknown_charger_404(db):
    with pytest.raises(NotFoundError):
        await ChargerRepo(db).delete(999, actor=AuditContext.system())


async def test_assign_unknown_charger_or_member_404(db):
    m1 = await _member(db, "M1")
    c = await _charger(db)
    repo = ChargerRepo(db)
    with pytest.raises(NotFoundError):
        await repo.assign(999, m1, actor=AuditContext.system())
    with pytest.raises(NotFoundError):
        await repo.assign(c["id"], 999, actor=AuditContext.system())


# --- routes --------------------------------------------------------------


def test_charger_crud_and_assignment_over_http(admin_client, make_member):
    m1 = make_member(member_reference="M1")
    created = admin_client.post(
        "/api/chargers", json={"name": "Garasje 1", "serial_no": "ZAP-1"}, headers=FETCH
    )
    assert created.status_code == 201
    cid = created.json()["id"]

    admin_client.post(
        f"/api/chargers/{cid}/assignments",
        json={"member_id": m1, "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    listed = admin_client.get("/api/chargers").json()["chargers"]
    assert listed[0]["assigned_member_id"] == m1

    admin_client.post(
        f"/api/chargers/{cid}/unassign", json={"effective_to": "2026-06-01"}, headers=FETCH
    )
    assert admin_client.get(f"/api/chargers/{cid}").json()["assigned_member_id"] is None
    hist = admin_client.get(f"/api/chargers/{cid}/assignments").json()["assignments"]
    assert len(hist) == 1 and hist[0]["effective_to"] == "2026-06-01"


def test_charger_delete_over_http(admin_client):
    cid = admin_client.post(
        "/api/chargers", json={"name": "Dup", "serial_no": "ZAP-9"}, headers=FETCH
    ).json()["id"]
    listed = admin_client.get("/api/chargers").json()["chargers"]
    assert next(c for c in listed if c["id"] == cid)["deletable"] is True

    assert admin_client.delete(f"/api/chargers/{cid}").status_code == 403  # needs fetch header
    assert admin_client.delete(f"/api/chargers/{cid}", headers=FETCH).status_code == 204
    assert admin_client.get(f"/api/chargers/{cid}").status_code == 404


def test_charger_delete_requires_admin(member_client):
    assert member_client.delete("/api/chargers/1", headers=FETCH).status_code == 403


def test_assign_route_reresolves_month(admin_client, make_member, db):
    m1 = make_member(member_reference="M1")
    cid = admin_client.post(
        "/api/chargers", json={"name": "C1", "zaptec_id": "z-1"}, headers=FETCH
    ).json()["id"]
    # a session already imported for August, not yet attributed to any member
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_id, charger_zaptec_id, period_month, started_at, "
        " energy_kwh, source, imported_at, updated_at) "
        "VALUES ('s-1', ?, 'z-1', '2026-08', '2026-08-10T10:00:00+00:00', '5.0', 'zaptec', "
        "'2026-08-11T00:00:00+00:00', '2026-08-11T00:00:00+00:00')",
        (cid,),
    )
    db.connection.commit()

    admin_client.post(
        f"/api/chargers/{cid}/assignments",
        json={"member_id": m1, "effective_from": "2026-08-01"},
        headers=FETCH,
    )
    row = db.connection.execute(
        "SELECT member_id FROM charging_sessions WHERE zaptec_session_id = 's-1'"
    ).fetchone()
    assert row["member_id"] == m1


def test_charger_routes_require_admin(member_client):
    assert member_client.get("/api/chargers").status_code == 403


def test_charger_mutations_need_fetch_header(admin_client):
    assert admin_client.post("/api/chargers", json={"name": "x"}).status_code == 403


def test_invalid_charger_body_is_uniform_422(admin_client):
    resp = admin_client.post("/api/chargers", json={"name": "   "}, headers=FETCH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"
