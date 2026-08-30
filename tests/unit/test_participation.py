from __future__ import annotations

import json

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError

FETCH = {"X-Requested-With": "fetch"}


async def _active_member(db, ref, active_from="2026-01-01"):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=ref,
        email=None,
        join_date="2026-01-01",
        actor=AuditContext.system(),
    )
    await MemberRepo(db).set_status(
        row["id"], "active", effective_from=active_from, actor=AuditContext.system()
    )
    return row["id"]


# --- MemberRepo participation -------------------------------------------


async def test_default_suggestions_are_the_active_members(db):
    a = await _active_member(db, "A")
    b = await _active_member(db, "B")
    sugg = MemberRepo(db).suggested_participants("2026-06-01")
    assert {s["member_id"] for s in sugg} == {a, b}
    assert all(s["participates"] and s["source"] == "default" for s in sugg)


async def test_exclude_records_history_audit_and_still_gets_consumption(db):
    a = await _active_member(db, "A")
    await _active_member(db, "B")
    repo = MemberRepo(db)

    await repo.set_participation(
        a, False, effective_from="2026-06-01", reason="borteboer", actor=AuditContext.system()
    )

    sugg = {s["member_id"]: s for s in repo.suggested_participants("2026-07-01")}
    assert sugg[a]["participates"] is False and sugg[a]["source"] == "explicit"

    event = db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = 'member.participation_changed'"
    ).fetchone()
    assert json.loads(event["detail_json"]) == {
        "from": None,
        "to": False,
        "effective_from": "2026-06-01",
    }

    # Excluded from equal-cost, but still an active member -> still gets consumption costs.
    assert a in repo.consumption_cost_recipients("2026-07-01")


async def test_reinclude_keeps_one_open_row(db):
    a = await _active_member(db, "A")
    repo = MemberRepo(db)
    await repo.set_participation(a, False, effective_from="2026-06-01", actor=AuditContext.system())
    await repo.set_participation(a, True, effective_from="2026-08-01", actor=AuditContext.system())

    hist = repo.participation_history(a)
    assert len(hist) == 2
    assert sum(1 for h in hist if h["effective_to"] is None) == 1
    assert repo.effective_participation(a, "2026-09-01") is True


async def test_setting_same_participation_value_is_rejected(db):
    a = await _active_member(db, "A")
    repo = MemberRepo(db)
    await repo.set_participation(a, True, effective_from="2026-06-01", actor=AuditContext.system())
    with pytest.raises(DomainError) as excinfo:
        await repo.set_participation(
            a, True, effective_from="2026-07-01", actor=AuditContext.system()
        )
    assert excinfo.value.code == "participation_unchanged"


async def test_inactive_member_never_suggested_even_if_explicitly_included(db):
    a = await _active_member(db, "A")
    repo = MemberRepo(db)
    await repo.set_participation(a, True, effective_from="2026-01-01", actor=AuditContext.system())
    await repo.set_status(a, "inactive", effective_from="2026-05-01", actor=AuditContext.system())

    assert repo.suggested_participants("2026-06-01") == []
    assert a not in repo.consumption_cost_recipients("2026-06-01")


# --- routes ------------------------------------------------------------


def test_suggested_participants_route(admin_client, make_member, frozen_now):
    member_id = make_member(member_reference="A-1")
    admin_client.post(f"/api/members/{member_id}/status", json={"status": "active"}, headers=FETCH)

    body = admin_client.get("/api/settlement/suggested-participants").json()
    assert body["on_date"] == "2026-08-30"
    assert [p["member_id"] for p in body["participants"]] == [member_id]
    assert body["participants"][0]["source"] == "default"


def test_suggested_participants_member_forbidden(member_client):
    assert member_client.get("/api/settlement/suggested-participants").status_code == 403


def test_suggested_participants_anonymous_401(client):
    assert client.get("/api/settlement/suggested-participants").status_code == 401


def test_participation_history_route(admin_client, make_member):
    member_id = make_member(member_reference="A-1")
    admin_client.post(f"/api/members/{member_id}/status", json={"status": "active"}, headers=FETCH)
    admin_client.post(
        f"/api/members/{member_id}/participation",
        json={"participates": False, "reason": "borteboer"},
        headers=FETCH,
    )
    periods = admin_client.get(f"/api/members/{member_id}/participation-history").json()["periods"]
    assert len(periods) == 1 and periods[0]["participates"] is False


def test_participation_route_unknown_member_404(admin_client):
    resp = admin_client.post(
        "/api/members/999/participation", json={"participates": False}, headers=FETCH
    )
    assert resp.status_code == 404
