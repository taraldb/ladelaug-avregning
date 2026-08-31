from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.job_schedules import JobScheduleRepo
from ladelaug_avregning.scheduler import runner as runner_mod
from ladelaug_avregning.scheduler.runner import SchedulerRunner, run_job_once

SYS = AuditContext.system()


@pytest.fixture
def enabled_job(db):
    """Enable a job and force it due (next_run_at NULL)."""

    async def _enable(name: str) -> None:
        await JobScheduleRepo(db).update(name, actor=SYS, enabled=True)
        db.connection.execute("UPDATE job_schedules SET next_run_at = NULL WHERE name = ?", (name,))
        db.connection.commit()

    return _enable


async def test_tick_runs_due_job_and_advances(frozen_now, db, config, enabled_job, monkeypatch):
    frozen_now["now"] = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
    calls: list[str] = []

    async def fake(_db, _config):
        calls.append("drain_mail")
        return {"sent": 3}

    monkeypatch.setattr(runner_mod, "JOBS", {"drain_mail": fake})
    await enabled_job("drain_mail")

    await SchedulerRunner(db, config)._tick()

    assert calls == ["drain_mail"]
    row = JobScheduleRepo(db).get("drain_mail")
    assert row["last_status"] == "ok"
    assert row["last_run_at"] == "2026-08-30T12:00:00+00:00"
    assert row["last_error"] is None
    assert row["next_run_at"] == "2026-08-30T12:10:00+00:00"


async def test_tick_skips_disabled_job(db, config, monkeypatch):
    calls: list[str] = []

    async def fake(_db, _config):
        calls.append("x")
        return {}

    monkeypatch.setattr(runner_mod, "JOBS", {"drain_mail": fake})
    # drain_mail ships disabled; do not enable it.

    await SchedulerRunner(db, config)._tick()
    assert calls == []


async def test_failing_job_is_recorded_and_tick_continues(
    frozen_now, db, config, enabled_job, monkeypatch
):
    async def boom(_db, _config):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(runner_mod, "JOBS", {"drain_mail": boom})
    await enabled_job("drain_mail")

    await SchedulerRunner(db, config)._tick()  # must not raise

    row = JobScheduleRepo(db).get("drain_mail")
    assert row["last_status"] == "error"
    assert "kaboom" in row["last_error"]
    assert row["next_run_at"] is not None  # still rescheduled


async def test_jobs_run_one_at_a_time_in_order(frozen_now, db, config, enabled_job, monkeypatch):
    events: list[str] = []

    def make(name):
        async def job(_db, _config):
            events.append(f"{name}:start")
            await asyncio.sleep(0)
            events.append(f"{name}:end")
            return {}

        return job

    monkeypatch.setattr(
        runner_mod,
        "JOBS",
        {"drain_mail": make("drain_mail"), "low_balance_scan": make("low_balance_scan")},
    )
    await enabled_job("drain_mail")
    await enabled_job("low_balance_scan")

    await SchedulerRunner(db, config)._tick()

    # No interleaving: each job fully finishes before the next starts.
    assert events == [
        "drain_mail:start",
        "drain_mail:end",
        "low_balance_scan:start",
        "low_balance_scan:end",
    ]


async def test_run_job_once_returns_outcome(frozen_now, db, config, monkeypatch):
    async def fake(_db, _config):
        return {"due": 0}

    monkeypatch.setattr(runner_mod, "JOBS", {"drain_mail": fake})

    out = await run_job_once(db, config, "drain_mail")
    assert out["name"] == "drain_mail"
    assert out["status"] == "ok"
    assert out["summary"] == {"due": 0}
    assert JobScheduleRepo(db).get("drain_mail")["last_status"] == "ok"
