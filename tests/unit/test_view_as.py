"""Admin "view the portal as a member" — read-only impersonation (US: portal QA).

The target member id is stamped on the admin's own session row; ``/api/me/*``
then serves that member's data, and every ``/api/me`` write is refused.
"""

from __future__ import annotations

import pytest

FETCH = {"X-Requested-With": "fetch"}


def _audit(db, event_type):
    return db.connection.execute(
        "SELECT * FROM audit_events WHERE event_type = ? ORDER BY id", (event_type,)
    ).fetchall()


@pytest.fixture
def admin_and_member(client, config, seed_user_sync, make_member, make_session):
    member_id = make_member(
        member_reference="M-500", full_name="Kari Nordmann", email="kari@example.com"
    )
    admin_uid = seed_user_sync(email="admin@example.com", role="admin")
    client.cookies.set(config.auth.cookie_name, make_session(admin_uid))
    return client, member_id


def test_admin_without_view_as_cannot_use_me(admin_and_member):
    client, _ = admin_and_member
    assert client.get("/api/me").status_code == 403


def test_view_as_lets_admin_read_the_member_portal(admin_and_member, db):
    client, member_id = admin_and_member

    started = client.post(f"/api/admin/view-as/{member_id}", headers=FETCH)
    assert started.status_code == 200
    assert started.json() == {"member_id": member_id, "member_name": "Kari Nordmann"}

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["full_name"] == "Kari Nordmann"

    bal = client.get("/api/me/balance")
    assert bal.status_code == 200
    assert bal.json()["member_id"] == member_id

    who = client.get("/api/auth/me").json()
    assert who["role"] == "admin"
    assert who["view_as"] == {"member_id": member_id, "member_name": "Kari Nordmann"}

    assert len(_audit(db, "admin.view_as_started")) == 1


def test_view_as_is_strictly_read_only(admin_and_member):
    client, member_id = admin_and_member
    client.post(f"/api/admin/view-as/{member_id}", headers=FETCH)

    r = client.patch("/api/me", json={"full_name": "Hacked"}, headers=FETCH)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "view_as_read_only"

    r = client.post("/api/me/password", json={"new_password": "a-brand-new-secret"}, headers=FETCH)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "view_as_read_only"


def test_stop_view_as_restores_the_admin(admin_and_member, db):
    client, member_id = admin_and_member
    client.post(f"/api/admin/view-as/{member_id}", headers=FETCH)

    assert client.delete("/api/admin/view-as", headers=FETCH).status_code == 200
    assert client.get("/api/me").status_code == 403
    assert client.get("/api/auth/me").json()["view_as"] is None
    assert len(_audit(db, "admin.view_as_stopped")) == 1


def test_view_as_unknown_member_is_404(admin_and_member):
    client, _ = admin_and_member
    assert client.post("/api/admin/view-as/999999", headers=FETCH).status_code == 404


def test_view_as_needs_the_csrf_header(admin_and_member):
    client, member_id = admin_and_member
    assert client.post(f"/api/admin/view-as/{member_id}").status_code == 403


def test_a_member_cannot_start_view_as(member_client, make_member):
    other = make_member(member_reference="M-900", full_name="Someone Else")
    assert member_client.post(f"/api/admin/view-as/{other}", headers=FETCH).status_code == 403
