from __future__ import annotations

FETCH = {"X-Requested-With": "fetch"}


def test_anonymous_gets_401(client):
    assert client.get("/api/audit-events").status_code == 401


def test_member_gets_403(member_client):
    assert member_client.get("/api/audit-events").status_code == 403


def test_admin_gets_paginated_list_with_counts(admin_client):
    # a failed login writes a user.sign_in_failed event
    admin_client.post(
        "/api/auth/login", json={"email": "x@y.no", "password": "nope"}, headers=FETCH
    )

    body = admin_client.get("/api/audit-events").json()
    assert set(body) == {"events", "total", "counts"}
    assert body["total"] >= 2  # user.created (admin seed) + user.sign_in_failed
    assert body["counts"].get("user.created", 0) >= 1

    stamps = [e["occurred_at"] for e in body["events"]]
    assert stamps == sorted(stamps, reverse=True)


def test_filter_by_entity_type(admin_client):
    resp = admin_client.get("/api/audit-events", params={"entity_type": "user"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert events and all(e["entity_type"] == "user" for e in events)


def test_unknown_event_id_is_404(admin_client):
    resp = admin_client.get("/api/audit-events/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not_found"


def test_invalid_sort_by_is_422(admin_client):
    assert admin_client.get("/api/audit-events", params={"sort_by": "ip"}).status_code == 422


def test_filter_by_actor_substring(admin_client):
    admin_client.post(
        "/api/auth/login", json={"email": "mallory@evil.test", "password": "nope"}, headers=FETCH
    )
    events = admin_client.get("/api/audit-events", params={"actor": "mallory@evil.test"}).json()[
        "events"
    ]
    assert events and all("mallory@evil.test" in e["actor_label"] for e in events)


def test_csv_export_member_forbidden(member_client):
    assert member_client.get("/api/audit-events/export.csv").status_code == 403


def test_csv_export_admin_streams_rows(admin_client):
    admin_client.post(
        "/api/members",
        json={"member_reference": "M-9", "full_name": "Ola", "join_date": "2026-01-01"},
        headers=FETCH,
    )
    resp = admin_client.get("/api/audit-events/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "revisjonslogg.csv" in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("id,occurred_at,actor_label,actor_role")
    assert any("member.created" in ln for ln in lines[1:])
