from __future__ import annotations

from ladelaug_avregning import security

FETCH = {"X-Requested-With": "fetch"}


def _login(client, email, password):
    return client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=FETCH
    )


def _count(db, event_type):
    return db.connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = ?", (event_type,)
    ).fetchone()[0]


def test_login_success_sets_cookie_and_audits(client, db, seed_user_sync):
    seed_user_sync(email="admin@example.com", password="changeme123", role="admin")

    resp = _login(client, "admin@example.com", "changeme123")

    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "admin@example.com"
    set_cookie = resp.headers["set-cookie"].lower()
    assert "ladelaug_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie  # cookie_secure is False in the test config
    assert _count(db, "user.signed_in") == 1


def test_bad_password_is_401_and_audited(client, db, seed_user_sync):
    seed_user_sync(email="admin@example.com", password="changeme123")

    resp = _login(client, "admin@example.com", "not-the-password")

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "not_authenticated"
    assert _count(db, "user.sign_in_failed") == 1
    assert _count(db, "user.signed_in") == 0


def test_unknown_email_and_disabled_user_are_indistinguishable(client, seed_user_sync):
    seed_user_sync(email="disabled@example.com", password="changeme123", disabled=True)

    unknown = _login(client, "nobody@example.com", "whatever-123")
    disabled = _login(client, "disabled@example.com", "changeme123")

    assert unknown.status_code == disabled.status_code == 401
    assert unknown.json() == disabled.json()


def test_rate_limit_returns_429_before_argon2(client, seed_user_sync, monkeypatch):
    seed_user_sync(email="admin@example.com", password="changeme123")

    calls = {"n": 0}
    real_verify = security.verify_password

    def counting_verify(*args, **kwargs):
        calls["n"] += 1
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(security, "verify_password", counting_verify)

    for _ in range(5):
        assert _login(client, "admin@example.com", "wrong-password").status_code == 401
    calls_after_five = calls["n"]
    assert calls_after_five == 5

    blocked = _login(client, "admin@example.com", "wrong-password")
    assert blocked.status_code == 429
    assert "retry-after" in {k.lower() for k in blocked.headers}
    assert calls["n"] == calls_after_five  # argon2 not touched on the blocked attempt


def test_logout_revokes_the_session(client, seed_user_sync):
    seed_user_sync(email="admin@example.com", password="changeme123")
    _login(client, "admin@example.com", "changeme123")

    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout", headers=FETCH).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_me_reports_identity_and_version(client, seed_user_sync):
    from ladelaug_avregning import __version__

    seed_user_sync(email="admin@example.com", password="changeme123", role="admin")
    _login(client, "admin@example.com", "changeme123")

    body = client.get("/api/auth/me").json()
    assert body["email"] == "admin@example.com"
    assert body["role"] == "admin"
    assert body["member_id"] is None
    assert body["version"] == __version__


def test_login_requires_fetch_header(client, seed_user_sync):
    seed_user_sync(email="admin@example.com", password="changeme123")

    resp = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "changeme123"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf"


def test_expired_session_is_rejected(client, config, seed_user_sync, make_session):
    uid = seed_user_sync(email="admin@example.com")
    client.cookies.set(config.auth.cookie_name, make_session(uid, ttl_hours=-1))
    assert client.get("/api/auth/me").status_code == 401


def test_touch_slides_expiry_then_throttles(
    client, db, config, seed_user_sync, make_session, frozen_now
):
    uid = seed_user_sync(email="admin@example.com")
    client.cookies.set(config.auth.cookie_name, make_session(uid))

    def last_seen():
        return db.connection.execute("SELECT last_seen_at FROM sessions").fetchone()[0]

    created_at = last_seen()

    frozen_now["now"] = frozen_now["now"].replace(minute=10)  # +10 min -> past throttle
    assert client.get("/api/auth/me").status_code == 200
    bumped = last_seen()
    assert bumped != created_at

    assert client.get("/api/auth/me").status_code == 200
    assert last_seen() == bumped  # same instant -> throttled, no second write
