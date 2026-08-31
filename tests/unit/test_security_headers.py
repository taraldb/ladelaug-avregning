"""SecurityHeadersMiddleware stamps CSP / anti-clickjacking headers everywhere."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ladelaug_avregning.webapp.app import create_app

_EXPECTED = {
    "content-security-policy": "frame-ancestors 'none'",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "geolocation=()",
}


def test_headers_on_api_response(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    for name, needle in _EXPECTED.items():
        assert needle in resp.headers[name]


def test_headers_on_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]


def test_hsts_absent_without_cookie_secure(client):
    # conftest `config` fixture sets cookie_secure = False (plain-HTTP dev).
    assert "strict-transport-security" not in client.get("/api/health").headers


def test_hsts_present_with_cookie_secure(config, db):
    config.auth.cookie_secure = True
    with TestClient(create_app(config, db)) as secure_client:
        resp = secure_client.get("/api/health")
    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
