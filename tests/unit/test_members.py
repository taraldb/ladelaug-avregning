from __future__ import annotations

import json

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError, NotFoundError

FETCH = {"X-Requested-With": "fetch"}


def _audit(db, event_type):
    return db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = ? ORDER BY id", (event_type,)
    ).fetchall()


# --- MemberRepo -----------------------------------------------------------


async def test_repo_create_writes_row_and_audit(db):
    repo = MemberRepo(db)
    row = await repo.create(
        member_reference="A-07",
        full_name="Kari Nordmann",
        email="kari@example.com",
        join_date="2026-08-01",
        actor=AuditContext.system(),
    )
    assert row["member_reference"] == "A-07"
    assert repo.get(row["id"])["full_name"] == "Kari Nordmann"

    events = _audit(db, "member.created")
    assert len(events) == 1
    assert events[0]["entity_id"] == str(row["id"])
    assert events[0]["actor_label"] == "system"


async def test_repo_create_duplicate_reference(db):
    repo = MemberRepo(db)
    await repo.create(
        member_reference="A-07",
        full_name="A",
        email=None,
        join_date="2026-08-01",
        actor=AuditContext.system(),
    )
    with pytest.raises(DomainError) as excinfo:
        await repo.create(
            member_reference="A-07",
            full_name="B",
            email=None,
            join_date="2026-08-01",
            actor=AuditContext.system(),
        )
    assert excinfo.value.code == "reference_taken"


async def test_repo_update_records_before_and_after(db):
    repo = MemberRepo(db)
    row = await repo.create(
        member_reference="A-07",
        full_name="Old Name",
        email=None,
        join_date="2026-08-01",
        actor=AuditContext.system(),
    )
    updated = await repo.update(row["id"], full_name="New Name", actor=AuditContext.system())
    assert updated["full_name"] == "New Name"

    detail = json.loads(_audit(db, "member.updated")[0]["detail_json"])
    assert detail["before"]["full_name"] == "Old Name"
    assert detail["after"]["full_name"] == "New Name"


async def test_repo_update_unknown_member(db):
    with pytest.raises(NotFoundError):
        await MemberRepo(db).update(999, full_name="x", actor=AuditContext.system())


# --- routes -------------------------------------------------------------


def test_create_member_route(admin_client, db):
    resp = admin_client.post(
        "/api/members",
        json={"member_reference": "A-07", "full_name": "Kari", "join_date": "2026-08-01"},
        headers=FETCH,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] and body["member_reference"] == "A-07"
    assert body["status"] is None and body["participates"] is None
    assert len(_audit(db, "member.created")) == 1


def test_create_member_duplicate_reference_is_422(admin_client):
    payload = {"member_reference": "A-07", "full_name": "Kari", "join_date": "2026-08-01"}
    assert admin_client.post("/api/members", json=payload, headers=FETCH).status_code == 201
    resp = admin_client.post("/api/members", json=payload, headers=FETCH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "reference_taken"


def test_create_member_invalid_email_is_422(admin_client):
    resp = admin_client.post(
        "/api/members",
        json={
            "member_reference": "A-1",
            "full_name": "K",
            "join_date": "2026-08-01",
            "email": "not-an-email",
        },
        headers=FETCH,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"


def test_create_member_missing_field_is_422(admin_client):
    resp = admin_client.post("/api/members", json={"member_reference": "A-1"}, headers=FETCH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"


def test_create_member_requires_csrf_header(admin_client):
    resp = admin_client.post(
        "/api/members",
        json={"member_reference": "A-1", "full_name": "K", "join_date": "2026-08-01"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf"


def test_list_members_anonymous_401(client):
    assert client.get("/api/members").status_code == 401


def test_list_members_member_403(member_client):
    assert member_client.get("/api/members").status_code == 403


def test_list_members_admin_200(admin_client, make_member):
    make_member(member_reference="A-07")
    body = admin_client.get("/api/members").json()
    assert [m["member_reference"] for m in body["members"]] == ["A-07"]


def test_list_and_get_member_carry_balance(admin_client, make_member):
    member_id = make_member(member_reference="A-08", email="a08@example.com")
    admin_client.post(
        f"/api/members/{member_id}/payments",
        json={"amount": "250.00", "value_date": "2026-08-01"},
        headers=FETCH,
    )

    listed = admin_client.get("/api/members").json()["members"][0]
    assert listed["balance_ore"] == 25000
    assert listed["balance_nok"] == "250.00"

    fetched = admin_client.get(f"/api/members/{member_id}").json()
    assert fetched["balance_ore"] == 25000


def test_get_member_unknown_404(admin_client):
    resp = admin_client.get("/api/members/999")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not_found"


def test_patch_member_route(admin_client, make_member, db):
    member_id = make_member(member_reference="A-07", full_name="Old")
    resp = admin_client.patch(f"/api/members/{member_id}", json={"full_name": "New"}, headers=FETCH)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "New"
    assert len(_audit(db, "member.updated")) == 1


def test_patch_member_unknown_404(admin_client):
    resp = admin_client.patch("/api/members/999", json={"full_name": "x"}, headers=FETCH)
    assert resp.status_code == 404


def test_patch_member_empty_body_422(admin_client, make_member):
    member_id = make_member(member_reference="A-07")
    resp = admin_client.patch(f"/api/members/{member_id}", json={}, headers=FETCH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"
