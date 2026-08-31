from __future__ import annotations

from typing import Any

FETCH = {"X-Requested-With": "fetch"}


def test_jobs_list_anonymous_401(client: Any) -> None:
    assert client.get("/api/system/jobs").status_code == 401


def test_jobs_list_member_403(member_client: Any) -> None:
    assert member_client.get("/api/system/jobs").status_code == 403


def test_jobs_list_admin(admin_client: Any) -> None:
    body = admin_client.get("/api/system/jobs").json()
    names = [j["name"] for j in body["jobs"]]
    assert names == ["drain_mail", "low_balance_scan", "zaptec_sync_sessions"]
    assert all(j["enabled"] is False for j in body["jobs"])


def test_enable_job(admin_client: Any) -> None:
    out = admin_client.put("/api/system/jobs/drain_mail", json={"enabled": True}, headers=FETCH)
    assert out.status_code == 200
    body = out.json()
    assert body["enabled"] is True
    assert body["next_run_at"] is not None


def test_update_job_needs_fetch_header(admin_client: Any) -> None:
    out = admin_client.put("/api/system/jobs/drain_mail", json={"enabled": True})
    assert out.status_code == 403


def test_update_job_bad_cron(admin_client: Any) -> None:
    out = admin_client.put("/api/system/jobs/drain_mail", json={"cron": "nope"}, headers=FETCH)
    assert out.status_code == 422
    assert out.json()["detail"]["code"] == "bad_cron"


def test_update_unknown_job(admin_client: Any) -> None:
    out = admin_client.put("/api/system/jobs/made_up", json={"enabled": True}, headers=FETCH)
    assert out.status_code == 422
    assert out.json()["detail"]["code"] == "unknown_job"


def test_update_job_empty_body(admin_client: Any) -> None:
    out = admin_client.put("/api/system/jobs/drain_mail", json={}, headers=FETCH)
    assert out.status_code == 422


def test_run_job_now(admin_client: Any) -> None:
    out = admin_client.post("/api/system/jobs/drain_mail/run", headers=FETCH)
    assert out.status_code == 200
    body = out.json()
    assert body["name"] == "drain_mail"
    assert body["status"] == "ok"


def test_run_unknown_job(admin_client: Any) -> None:
    out = admin_client.post("/api/system/jobs/made_up/run", headers=FETCH)
    assert out.status_code == 422
    assert out.json()["detail"]["code"] == "unknown_job"


def test_health_reports_scheduler(admin_client: Any) -> None:
    body = admin_client.get("/api/system/health").json()
    assert body["scheduler"]["enabled"] is False
    assert [j["name"] for j in body["scheduler"]["jobs"]] == [
        "drain_mail",
        "low_balance_scan",
        "zaptec_sync_sessions",
    ]
