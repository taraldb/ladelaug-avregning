"""Member self-service: PATCH /api/me (name / email) and POST /api/me/password.

Both live on the ``/api/me`` router, resolve the member from the session, and
require the ``X-Requested-With: fetch`` CSRF header.
"""

from __future__ import annotations

from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.security import verify_password

FETCH = {"X-Requested-With": "fetch"}


def _uid(db: Database, email: str = "kari@example.com") -> int:
    return int(
        db.connection.execute(
            "SELECT id FROM users WHERE email_normalized = ?", (email.lower(),)
        ).fetchone()[0]
    )


# --- PATCH /api/me ----------------------------------------------------


def test_member_updates_own_name_and_email(member_client, db):
    out = member_client.patch(
        "/api/me",
        json={"full_name": "Kari Nordmann", "email": "kari.n@example.com"},
        headers=FETCH,
    )
    assert out.status_code == 200
    body = out.json()
    assert body["full_name"] == "Kari Nordmann"
    assert body["email"] == "kari.n@example.com"

    row = db.connection.execute(
        "SELECT full_name, email, member_reference FROM members WHERE id = 1"
    ).fetchone()
    assert row["full_name"] == "Kari Nordmann"
    assert row["email"] == "kari.n@example.com"
    assert row["member_reference"] == "M-100"  # untouched


def test_patch_me_ignores_admin_only_fields_and_422s_when_nothing_left(member_client, db):
    before = db.connection.execute(
        "SELECT member_reference, join_date FROM members WHERE id = 1"
    ).fetchone()
    out = member_client.patch(
        "/api/me",
        json={"member_reference": "M-999", "join_date": "2000-01-01"},
        headers=FETCH,
    )
    assert out.status_code == 422
    after = db.connection.execute(
        "SELECT member_reference, join_date FROM members WHERE id = 1"
    ).fetchone()
    assert dict(after) == dict(before)


def test_patch_me_rejects_bad_email(member_client):
    assert (
        member_client.patch("/api/me", json={"email": "not-an-email"}, headers=FETCH).status_code
        == 422
    )


def test_patch_me_empty_body_422(member_client):
    assert member_client.patch("/api/me", json={}, headers=FETCH).status_code == 422


def test_patch_me_forbidden_for_pure_admin(admin_client):
    assert admin_client.patch("/api/me", json={"full_name": "X"}, headers=FETCH).status_code == 403


def test_patch_me_requires_csrf_header(member_client):
    assert member_client.patch("/api/me", json={"full_name": "X"}).status_code == 403


def test_patch_me_requires_authentication(client):
    assert client.patch("/api/me", json={"full_name": "X"}, headers=FETCH).status_code == 401


# --- POST /api/me/password -----------------------------------------


def test_change_password_rehashes_and_revokes_other_sessions(
    member_client, config: AppConfig, db, make_session
):
    uid = _uid(db)
    before_hash = db.connection.execute(
        "SELECT password_hash FROM users WHERE id = ?", (uid,)
    ).fetchone()[0]

    other_token = make_session(uid)  # a second logged-in device
    current_token = member_client.cookies.get(config.auth.cookie_name)

    out = member_client.post(
        "/api/me/password",
        json={"new_password": "a-brand-new-secret-2026"},
        headers=FETCH,
    )
    assert out.status_code == 200 and out.json() == {"ok": True}

    new_hash = db.connection.execute(
        "SELECT password_hash FROM users WHERE id = ?", (uid,)
    ).fetchone()[0]
    assert new_hash != before_hash
    assert verify_password(new_hash, "a-brand-new-secret-2026")

    sessions = SessionRepo(db)
    assert sessions.get_valid(current_token) is not None  # current device stays in
    assert sessions.get_valid(other_token) is None  # every other device is out

    queued = db.connection.execute(
        "SELECT COUNT(*) FROM email_messages WHERE template = 'password_changed'"
    ).fetchone()[0]
    assert queued == 1

    events = db.connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = 'auth.password_changed'"
    ).fetchone()[0]
    assert events == 1


def test_change_password_rejects_short_and_known_weak(member_client):
    assert (
        member_client.post(
            "/api/me/password", json={"new_password": "short"}, headers=FETCH
        ).status_code
        == 422
    )
    assert (
        member_client.post(
            "/api/me/password", json={"new_password": "0123456789"}, headers=FETCH
        ).status_code
        == 422
    )


_PW_BODY = {"new_password": "a-brand-new-secret-2026"}


def test_change_password_forbidden_for_pure_admin(admin_client):
    assert admin_client.post("/api/me/password", json=_PW_BODY, headers=FETCH).status_code == 403


def test_change_password_requires_csrf_header(member_client):
    assert member_client.post("/api/me/password", json=_PW_BODY).status_code == 403


def test_change_password_requires_authentication(client):
    assert client.post("/api/me/password", json=_PW_BODY, headers=FETCH).status_code == 401
