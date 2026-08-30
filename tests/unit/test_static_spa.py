"""The built SPA is served at / with a client-side-routing fallback."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ladelaug_avregning.webapp.app import create_app


@pytest.fixture
def spa_client(config, db, tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('app')")
    config.server.static_dir = str(dist)
    with TestClient(create_app(config, db)) as client:
        yield client


def test_root_serves_index(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert "id=root" in resp.text


def test_asset_is_served(spa_client):
    resp = spa_client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_client_side_route_falls_back_to_index(spa_client):
    resp = spa_client.get("/members/42")
    assert resp.status_code == 200
    assert "id=root" in resp.text


def test_api_paths_are_not_shadowed_by_the_spa(spa_client):
    assert spa_client.get("/api/health").json()["status"] == "ok"
    # an unknown /api path still gets a JSON 404, not index.html
    resp = spa_client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
