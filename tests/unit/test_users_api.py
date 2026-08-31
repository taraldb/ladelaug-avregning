from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

FETCH = {"X-Requested-With": "fetch"}


def test_users_list_anonymous_401(client: Any) -> None:
    assert client.get("/api/users").status_code == 401


def test_users_list_member_403(member_client: Any) -> None:
    assert member_client.get("/api/users").status_code == 403


def test_create_admin_login(admin_client: Any) -> None:
    out = admin_client.post(
        "/api/users",
        json={"email": "boss@example.com", "password": "supersecret1", "role": "admin"},
        headers=FETCH,
    )
    assert out.status_code == 201
    body = out.json()
    assert body["role"] == "admin"
    assert body["member_id"] is None
    assert body["disabled"] is False


def test_create_member_login_without_password_leaves_hash_null(
    admin_client: Any, make_member: Callable[..., int]
) -> None:
    member_id = make_member(member_reference="M-77", email="m77@example.com")
    out = admin_client.post(
        "/api/users",
        json={"email": "m77@example.com", "role": "member", "member_id": member_id},
        headers=FETCH,
    )
    assert out.status_code == 201
    uid = out.json()["id"]

    row = admin_client.app.state.db.connection.execute(
        "SELECT password_hash, member_id FROM users WHERE id = ?", (uid,)
    ).fetchone()
    assert row["password_hash"] is None
    assert row["member_id"] == member_id


def test_create_member_login_requires_member_id(admin_client: Any) -> None:
    out = admin_client.post(
        "/api/users",
        json={"email": "x@example.com", "role": "member"},
        headers=FETCH,
    )
    assert out.status_code == 422


def test_create_rejects_duplicate_email(admin_client: Any) -> None:
    admin_client.post(
        "/api/users",
        json={"email": "dupe@example.com", "password": "supersecret1", "role": "admin"},
        headers=FETCH,
    )
    out = admin_client.post(
        "/api/users",
        json={"email": "DUPE@example.com", "password": "supersecret1", "role": "admin"},
        headers=FETCH,
    )
    assert out.status_code == 422
    assert out.json()["detail"]["code"] == "email_taken"


def test_create_rejects_second_login_for_member(
    admin_client: Any, make_member: Callable[..., int]
) -> None:
    member_id = make_member(member_reference="M-9", email="nine@example.com")
    admin_client.post(
        "/api/users",
        json={"email": "nine@example.com", "role": "member", "member_id": member_id},
        headers=FETCH,
    )
    out = admin_client.post(
        "/api/users",
        json={"email": "nine-2@example.com", "role": "member", "member_id": member_id},
        headers=FETCH,
    )
    assert out.status_code == 422
    assert out.json()["detail"]["code"] == "member_linked"


def test_admin_cannot_disable_self(admin_client: Any) -> None:
    uid = admin_client.get("/api/auth/me").json()["id"]
    out = admin_client.post(f"/api/users/{uid}/disable", headers=FETCH)
    assert out.status_code == 422
    assert out.json()["detail"]["code"] == "cannot_disable_self"


def test_disable_and_enable_member_login_revokes_sessions(
    admin_client: Any,
    config: Any,
    make_member: Callable[..., int],
    seed_user_sync: Callable[..., int],
    make_session: Callable[..., str],
) -> None:
    member_id = make_member(member_reference="M-5", email="five@example.com")
    uid = seed_user_sync(email="five@example.com", role="member", member_id=member_id)
    token = make_session(uid)

    with TestClient(admin_client.app) as member:
        member.cookies.set(config.auth.cookie_name, token)
        assert member.get("/api/me").status_code == 200

        assert admin_client.post(f"/api/users/{uid}/disable", headers=FETCH).status_code == 200
        assert member.get("/api/me").status_code == 401

    body = admin_client.post(f"/api/users/{uid}/enable", headers=FETCH).json()
    assert body["disabled"] is False


def test_set_password(
    admin_client: Any,
    make_member: Callable[..., int],
    seed_user_sync: Callable[..., int],
) -> None:
    member_id = make_member(member_reference="M-3", email="three@example.com")
    uid = seed_user_sync(email="three@example.com", role="member", member_id=member_id)

    short = admin_client.post(
        f"/api/users/{uid}/password", json={"password": "short"}, headers=FETCH
    )
    assert short.status_code == 422

    ok = admin_client.post(
        f"/api/users/{uid}/password", json={"password": "brandnewpass1"}, headers=FETCH
    )
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}
