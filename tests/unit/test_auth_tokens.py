from __future__ import annotations

import re
from datetime import timedelta

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.auth_tokens import AuthTokenRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import DomainError

FETCH = {"X-Requested-With": "fetch"}


async def _user(db, email="kari@example.com", *, disabled=False):
    uid = await UserRepo(db).create(
        email=email,
        password="x" * 12,
        role="member",
        actor=AuditContext.system(),
        argon2=(1, 8192, 1),
    )
    if disabled:
        await UserRepo(db).set_disabled(uid, True, actor=AuditContext.system())
    return uid


# --- AuthTokenRepo ---------------------------------------------------


async def test_issue_then_consume_returns_user(db):
    uid = await _user(db)
    repo = AuthTokenRepo(db)
    token = await repo.issue(user_id=uid, kind="magic_link", ttl_minutes=30, ip=None)
    assert await repo.consume(token=token, kind="magic_link") == uid


async def test_token_is_single_use(db):
    uid = await _user(db)
    repo = AuthTokenRepo(db)
    token = await repo.issue(user_id=uid, kind="magic_link", ttl_minutes=30, ip=None)
    await repo.consume(token=token, kind="magic_link")
    with pytest.raises(DomainError) as ei:
        await repo.consume(token=token, kind="magic_link")
    assert ei.value.code == "invalid_token"


async def test_issuing_again_invalidates_the_previous(db):
    uid = await _user(db)
    repo = AuthTokenRepo(db)
    first = await repo.issue(user_id=uid, kind="magic_link", ttl_minutes=30, ip=None)
    await repo.issue(user_id=uid, kind="magic_link", ttl_minutes=30, ip=None)
    with pytest.raises(DomainError):
        await repo.consume(token=first, kind="magic_link")


async def test_wrong_kind_is_rejected(db):
    uid = await _user(db)
    repo = AuthTokenRepo(db)
    token = await repo.issue(user_id=uid, kind="magic_link", ttl_minutes=30, ip=None)
    with pytest.raises(DomainError):
        await repo.consume(token=token, kind="password_reset")


async def test_expired_token(db, frozen_now):
    uid = await _user(db)
    repo = AuthTokenRepo(db)
    token = await repo.issue(user_id=uid, kind="password_reset", ttl_minutes=15, ip=None)
    frozen_now["now"] = frozen_now["now"] + timedelta(minutes=16)
    with pytest.raises(DomainError) as ei:
        await repo.consume(token=token, kind="password_reset")
    assert ei.value.code == "expired_token"


# --- routes --------------------------------------------------------


def _token_from_last_email(db, contains: str) -> str:
    body = db.connection.execute(
        "SELECT body_text FROM email_messages WHERE body_text LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{contains}%",),
    ).fetchone()[0]
    m = re.search(r"token=([A-Za-z0-9_-]+)", body)
    assert m, body
    return m.group(1)


def test_magic_link_unknown_email_is_silent_200(client, db):
    resp = client.post("/api/auth/magic-link", json={"email": "nobody@example.com"}, headers=FETCH)
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    assert db.connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 0
    assert db.connection.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0] == 0


def test_magic_link_full_flow(client, db, seed_user_sync):
    seed_user_sync(email="kari@example.com", role="member")
    assert (
        client.post(
            "/api/auth/magic-link", json={"email": "kari@example.com"}, headers=FETCH
        ).status_code
        == 200
    )
    token = _token_from_last_email(db, "magic-link")

    consumed = client.post("/api/auth/magic-link/consume", json={"token": token}, headers=FETCH)
    assert consumed.status_code == 200
    assert consumed.json()["user"]["email"] == "kari@example.com"
    # cookie now works
    assert client.get("/api/auth/me").json()["email"] == "kari@example.com"
    # token is spent
    assert (
        client.post(
            "/api/auth/magic-link/consume", json={"token": token}, headers=FETCH
        ).status_code
        == 422
    )


def _last_email(db, template: str):
    return db.connection.execute(
        "SELECT status, attempts FROM email_messages WHERE template = ? ORDER BY id DESC LIMIT 1",
        (template,),
    ).fetchone()


def test_magic_link_email_is_sent_immediately(client, db, seed_user_sync):
    """The link goes out on the request, not on the next queue drain."""
    seed_user_sync(email="kari@example.com", role="member")
    client.post("/api/auth/magic-link", json={"email": "kari@example.com"}, headers=FETCH)
    assert _last_email(db, "magic_link")["status"] == "sent"


def test_password_reset_email_is_sent_immediately(client, db, seed_user_sync):
    seed_user_sync(email="kari@example.com", role="member", password="oldpassword12")
    client.post(
        "/api/auth/password-reset/request", json={"email": "kari@example.com"}, headers=FETCH
    )
    assert _last_email(db, "password_reset")["status"] == "sent"


def test_magic_link_survives_an_immediate_send_failure(client, db, seed_user_sync, monkeypatch):
    """A failing sender must not break sign-in: the request still 200s and the
    message stays queued for the scheduler to retry."""
    seed_user_sync(email="kari@example.com", role="member")

    class Boom:
        async def send(self, **_kw):
            raise RuntimeError("smtp down")

    monkeypatch.setattr(
        "ladelaug_avregning.webapp.routes.auth.build_sender", lambda *a, **k: Boom()
    )
    resp = client.post("/api/auth/magic-link", json={"email": "kari@example.com"}, headers=FETCH)
    assert resp.status_code == 200

    row = _last_email(db, "magic_link")
    assert row["status"] == "queued" and row["attempts"] == 1
    # the token flow still works once the queue drains it later
    token = _token_from_last_email(db, "magic-link")
    assert (
        client.post(
            "/api/auth/magic-link/consume", json={"token": token}, headers=FETCH
        ).status_code
        == 200
    )


def test_magic_link_disabled_user_gets_no_token(client, db, seed_user_sync):
    seed_user_sync(email="off@example.com", role="member", disabled=True)
    client.post("/api/auth/magic-link", json={"email": "off@example.com"}, headers=FETCH)
    assert db.connection.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0] == 0


def test_password_reset_flow_changes_password_and_revokes_sessions(
    client, db, seed_user_sync, make_session
):
    uid = seed_user_sync(email="kari@example.com", role="member", password="oldpassword12")
    live = make_session(uid)
    client.cookies.set("ladelaug_session", live)
    assert client.get("/api/auth/me").status_code == 200

    client.post(
        "/api/auth/password-reset/request", json={"email": "kari@example.com"}, headers=FETCH
    )
    token = _token_from_last_email(db, "reset")
    done = client.post(
        "/api/auth/password-reset/consume",
        json={"token": token, "password": "brandnewpass9"},
        headers=FETCH,
    )
    assert done.status_code == 200

    # old session revoked
    client.cookies.set("ladelaug_session", live)
    assert client.get("/api/auth/me").status_code == 401
    # new password works, old does not
    client.cookies.clear()
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "kari@example.com", "password": "brandnewpass9"},
            headers=FETCH,
        ).status_code
        == 200
    )
    assert (
        db.connection.execute(
            "SELECT COUNT(*) FROM email_messages WHERE template = 'password_changed'"
        ).fetchone()[0]
        == 1
    )


def test_reset_consume_rejects_short_password(client, db, seed_user_sync):
    seed_user_sync(email="kari@example.com", role="member")
    client.post(
        "/api/auth/password-reset/request", json={"email": "kari@example.com"}, headers=FETCH
    )
    token = _token_from_last_email(db, "reset")
    resp = client.post(
        "/api/auth/password-reset/consume",
        json={"token": token, "password": "short"},
        headers=FETCH,
    )
    assert resp.status_code == 422


def test_auth_token_routes_need_fetch_header(client):
    assert client.post("/api/auth/magic-link", json={"email": "a@example.com"}).status_code == 403


def _count(db, sql, *params):
    return db.connection.execute(sql, params).fetchone()[0]


def test_magic_link_issuance_is_rate_limited(client, db, seed_user_sync):
    seed_user_sync(email="kari@example.com", role="member")
    for _ in range(5):  # auth.request_max_per_email default
        assert (
            client.post(
                "/api/auth/magic-link", json={"email": "kari@example.com"}, headers=FETCH
            ).status_code
            == 200
        )
    tokens = _count(db, "SELECT COUNT(*) FROM auth_tokens")
    emails = _count(db, "SELECT COUNT(*) FROM email_messages")

    resp = client.post("/api/auth/magic-link", json={"email": "kari@example.com"}, headers=FETCH)
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    # nothing new issued or sent once over the cap
    assert _count(db, "SELECT COUNT(*) FROM auth_tokens") == tokens
    assert _count(db, "SELECT COUNT(*) FROM email_messages") == emails
    assert (
        _count(
            db, "SELECT COUNT(*) FROM audit_events WHERE event_type = 'auth.request_throttled'"
        )
        == 1
    )


def test_reset_issuance_rate_limit_is_independent_of_magic_link(client, db, seed_user_sync):
    seed_user_sync(email="kari@example.com", role="member", password="oldpassword12")
    for _ in range(5):
        client.post("/api/auth/magic-link", json={"email": "kari@example.com"}, headers=FETCH)
    # magic-link scope is now exhausted; password-reset scope is untouched
    resp = client.post(
        "/api/auth/password-reset/request", json={"email": "kari@example.com"}, headers=FETCH
    )
    assert resp.status_code == 200
    assert _last_email(db, "password_reset")["status"] == "sent"


def test_issuance_throttle_does_not_enumerate(client, db):
    # An unknown address that trips the cap behaves exactly like a known one:
    # always {"ok": true}, and a throttle audit row with no actor_user_id.
    for _ in range(6):
        resp = client.post(
            "/api/auth/magic-link", json={"email": "ghost@example.com"}, headers=FETCH
        )
        assert resp.status_code == 200 and resp.json() == {"ok": True}
    row = db.connection.execute(
        "SELECT actor_user_id, actor_label FROM audit_events "
        "WHERE event_type = 'auth.request_throttled' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["actor_user_id"] is None and row["actor_label"] == "ghost@example.com"
