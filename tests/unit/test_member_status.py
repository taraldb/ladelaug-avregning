from __future__ import annotations

import json

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError, NotFoundError

FETCH = {"X-Requested-With": "fetch"}


async def _member(db, ref="M-1"):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=ref,
        email=None,
        join_date="2026-01-01",
        actor=AuditContext.system(),
    )
    return row["id"]


# --- MemberRepo.set_status ------------------------------------------------


async def test_timeline_activate_deactivate_reactivate(db, frozen_now):
    member_id = await _member(db)
    repo = MemberRepo(db)

    frozen_now["now"] = frozen_now["now"].replace(month=1, day=1)
    await repo.set_status(member_id, "active", actor=AuditContext.system())
    frozen_now["now"] = frozen_now["now"].replace(month=3, day=1)
    await repo.set_status(member_id, "inactive", actor=AuditContext.system())
    frozen_now["now"] = frozen_now["now"].replace(month=6, day=1)
    await repo.set_status(member_id, "active", actor=AuditContext.system())

    hist = repo.status_history(member_id)
    assert [h["status"] for h in hist] == ["active", "inactive", "active"]
    assert [h["effective_from"] for h in hist] == ["2026-01-01", "2026-03-01", "2026-06-01"]
    assert [h["effective_to"] for h in hist] == ["2026-03-01", "2026-06-01", None]
    assert sum(1 for h in hist if h["effective_to"] is None) == 1


async def test_active_member_ids_and_current_status_as_of_date(db):
    member_id = await _member(db)
    repo = MemberRepo(db)
    await repo.set_status(
        member_id, "active", effective_from="2026-02-01", actor=AuditContext.system()
    )
    await repo.set_status(
        member_id, "inactive", effective_from="2026-05-01", actor=AuditContext.system()
    )

    assert repo.active_member_ids("2026-01-15") == set()
    assert repo.active_member_ids("2026-03-01") == {member_id}
    assert repo.active_member_ids("2026-05-01") == set()  # half-open: closed on the boundary
    assert repo.current_status(member_id, "2026-03-01") == "active"
    assert repo.current_status(member_id, "2026-05-15") == "inactive"


async def test_backdate_before_open_period_is_rejected(db):
    member_id = await _member(db)
    repo = MemberRepo(db)
    await repo.set_status(
        member_id, "active", effective_from="2026-03-01", actor=AuditContext.system()
    )
    with pytest.raises(DomainError) as excinfo:
        await repo.set_status(
            member_id, "inactive", effective_from="2026-02-01", actor=AuditContext.system()
        )
    assert excinfo.value.code == "backdated"


async def test_same_status_is_rejected(db):
    member_id = await _member(db)
    repo = MemberRepo(db)
    await repo.set_status(
        member_id, "active", effective_from="2026-03-01", actor=AuditContext.system()
    )
    with pytest.raises(DomainError) as excinfo:
        await repo.set_status(
            member_id, "active", effective_from="2026-04-01", actor=AuditContext.system()
        )
    assert excinfo.value.code == "status_unchanged"


async def test_status_change_writes_audit_detail(db):
    member_id = await _member(db)
    await MemberRepo(db).set_status(
        member_id, "active", effective_from="2026-03-01", note="joined", actor=AuditContext.system()
    )
    event = db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = 'member.status_changed'"
    ).fetchone()
    assert json.loads(event["detail_json"]) == {
        "from": None,
        "to": "active",
        "effective_from": "2026-03-01",
    }


async def test_set_status_unknown_member(db):
    with pytest.raises(NotFoundError):
        await MemberRepo(db).set_status(999, "active", actor=AuditContext.system())


# --- routes ------------------------------------------------------------


def test_status_route_and_history(admin_client, make_member):
    member_id = make_member()
    resp = admin_client.post(
        f"/api/members/{member_id}/status",
        json={"status": "active", "effective_from": "2026-08-01"},
        headers=FETCH,
    )
    assert resp.status_code == 200
    assert resp.json()["period"]["status"] == "active"

    hist = admin_client.get(f"/api/members/{member_id}/status-history").json()["periods"]
    assert len(hist) == 1 and hist[0]["effective_to"] is None


def test_status_route_member_forbidden(member_client):
    resp = member_client.post("/api/members/1/status", json={"status": "active"}, headers=FETCH)
    assert resp.status_code == 403


def test_status_route_unknown_member_404(admin_client):
    resp = admin_client.post("/api/members/999/status", json={"status": "active"}, headers=FETCH)
    assert resp.status_code == 404


def test_status_route_backdate_422(admin_client, make_member):
    member_id = make_member()
    admin_client.post(
        f"/api/members/{member_id}/status",
        json={"status": "active", "effective_from": "2026-06-01"},
        headers=FETCH,
    )
    resp = admin_client.post(
        f"/api/members/{member_id}/status",
        json={"status": "inactive", "effective_from": "2026-05-01"},
        headers=FETCH,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "backdated"


def test_status_route_bad_status_value_422(admin_client, make_member):
    member_id = make_member()
    resp = admin_client.post(
        f"/api/members/{member_id}/status", json={"status": "paused"}, headers=FETCH
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"
