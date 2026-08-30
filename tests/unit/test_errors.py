import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import (
    AuthError,
    DomainError,
    NotFoundError,
    RateLimitError,
    register_exception_handlers,
)
from ladelaug_avregning.webapp.app import create_app
from tests.conftest import MIGRATIONS_DIR


@pytest.fixture
def error_client():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/domain")
    def _domain():
        raise DomainError("bad_state", "cannot do that")

    @app.get("/auth")
    def _auth():
        raise AuthError()

    @app.get("/forbidden")
    def _forbidden():
        raise AuthError("nope", status=403)

    @app.get("/missing")
    def _missing():
        raise NotFoundError("gone")

    @app.get("/slow")
    def _slow():
        raise RateLimitError("try later", retry_after=42)

    @app.get("/boom")
    def _boom():
        raise RuntimeError("kaboom")

    class _Body(BaseModel):
        n: int

    @app.post("/validate")
    def _validate(body: _Body):
        return {"ok": body.n}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "path,status,code",
    [
        ("/domain", 422, "bad_state"),
        ("/auth", 401, "not_authenticated"),
        ("/forbidden", 403, "forbidden"),
        ("/missing", 404, "not_found"),
        ("/slow", 429, "rate_limited"),
        ("/boom", 500, "internal_error"),
    ],
)
def test_error_shapes(error_client, path, status, code):
    r = error_client.get(path)
    assert r.status_code == status
    assert r.json() == {"detail": {"code": code, "message": r.json()["detail"]["message"]}}


def test_rate_limit_sets_retry_after(error_client):
    r = error_client.get("/slow")
    assert r.headers["Retry-After"] == "42"


def test_request_validation_error_uses_uniform_shape(error_client):
    r = error_client.post("/validate", json={"n": "not-an-int"})
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["code"] == "validation_error"
    assert "n" in body["detail"]["message"]


def test_health_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LADELAUG_SECRET_KEY", "x")
    cfg = AppConfig()
    db = Database(tmp_path / "h.db", migrations_dir=MIGRATIONS_DIR)
    client = TestClient(create_app(cfg, db))
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    db.close()
