"""The ``gmail_token_check`` scheduler job (migration 0016): probes the Gmail
OAuth refresh token so an expired one fails the job (and flips
``/api/system/health`` ``ok`` to false) before the next queued email does."""

from __future__ import annotations

import httpx
import respx

from ladelaug_avregning.domain.job_schedules import JobScheduleRepo
from ladelaug_avregning.scheduler.jobs import JOBS, gmail_token_check
from ladelaug_avregning.scheduler.runner import run_job_once

TOKEN_URL = "https://oauth2.googleapis.com/token"


def _with_gmail(config):
    return config.model_copy(
        update={
            "email": config.email.model_copy(
                update={
                    "backend": "gmail",
                    "gmail_client_id": "cid",
                    "gmail_client_secret": "secret",
                    "gmail_refresh_token": "rt",
                    "gmail_sender": "coop@gmail.com",
                }
            )
        }
    )


def test_job_is_registered_and_seeded(db):
    assert JOBS["gmail_token_check"] is gmail_token_check
    row = JobScheduleRepo(db).get("gmail_token_check")
    assert row is not None
    assert row["enabled"] is False
    assert row["cron"] == "0 7 * * *"


async def test_noop_when_backend_not_gmail(config, db):
    out = await gmail_token_check(db, config)
    assert out == {"skipped": "backend_not_gmail", "backend": "console"}


@respx.mock
async def test_ok_when_token_still_valid(config, db, respx_mock):
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    out = await gmail_token_check(db, _with_gmail(config))
    assert out["ok"] is True


@respx.mock
async def test_run_job_once_records_error_on_revoked_token(config, db, respx_mock):
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    out = await run_job_once(db, _with_gmail(config), "gmail_token_check")

    assert out["status"] == "error"
    assert "Gmail token refresh failed" in out["error"]
    assert JobScheduleRepo(db).get("gmail_token_check")["last_status"] == "error"
