from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from ladelaug_avregning.webapp.app import create_app
from ladelaug_avregning.webapp.deps import get_current_member, require_admin


@pytest.fixture
def rbac_client(config, db):
    app = create_app(config, db)

    @app.get("/api/whoami")
    def whoami(user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {"id": user["id"], "role": user["role"]}

    @app.get("/api/whoami-member")
    def whoami_member(member_id: int = Depends(get_current_member)) -> dict[str, int]:
        return {"member_id": member_id}

    with TestClient(app) as test_client:
        yield test_client


def _auth(client, config, make_session, uid):
    client.cookies.set(config.auth.cookie_name, make_session(uid))


def test_anonymous_gets_401(rbac_client):
    assert rbac_client.get("/api/whoami").status_code == 401


def test_admin_passes_require_admin(rbac_client, config, seed_user_sync, make_session):
    uid = seed_user_sync(email="admin@example.com", role="admin")
    _auth(rbac_client, config, make_session, uid)

    resp = rbac_client.get("/api/whoami")
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_member_is_forbidden_on_admin_route(
    rbac_client, config, seed_user_sync, seed_member_sync, make_session
):
    member_id = seed_member_sync()
    uid = seed_user_sync(email="kari@example.com", role="member", member_id=member_id)
    _auth(rbac_client, config, make_session, uid)

    assert rbac_client.get("/api/whoami").status_code == 403


def test_pure_admin_is_forbidden_on_member_route(rbac_client, config, seed_user_sync, make_session):
    uid = seed_user_sync(email="admin@example.com", role="admin")
    _auth(rbac_client, config, make_session, uid)

    assert rbac_client.get("/api/whoami-member").status_code == 403


def test_member_passes_member_route(
    rbac_client, config, seed_user_sync, seed_member_sync, make_session
):
    member_id = seed_member_sync()
    uid = seed_user_sync(email="kari@example.com", role="member", member_id=member_id)
    _auth(rbac_client, config, make_session, uid)

    resp = rbac_client.get("/api/whoami-member")
    assert resp.status_code == 200
    assert resp.json()["member_id"] == member_id
