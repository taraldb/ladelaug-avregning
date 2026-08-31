from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.job_schedules import JobScheduleRepo
from ladelaug_avregning.errors import DomainError

SYS = AuditContext.system()


def _audit_count(db, event_type: str = "system.job_schedule_updated") -> int:
    return db.connection.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = ?", (event_type,)
    ).fetchone()[0]


def test_migration_seeds_three_disabled_jobs(db) -> None:
    rows = JobScheduleRepo(db).list()
    assert [r["name"] for r in rows] == [
        "drain_mail",
        "low_balance_scan",
        "zaptec_sync_sessions",
    ]
    assert all(r["enabled"] is False for r in rows)
    assert all(r["next_run_at"] is None for r in rows)
    assert {r["cron"] for r in rows} == {"*/10 * * * *", "0 * * * *", "30 3 * * *"}


async def test_enable_sets_next_run_at_and_audits(frozen_now, db) -> None:
    frozen_now["now"] = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
    out = await JobScheduleRepo(db).update("low_balance_scan", actor=SYS, enabled=True)

    assert out["enabled"] is True
    assert out["next_run_at"] == "2026-08-30T13:00:00+00:00"
    assert out["updated_at"] == "2026-08-30T12:00:00+00:00"
    assert _audit_count(db) == 1


async def test_disable_clears_next_run_at(frozen_now, db) -> None:
    repo = JobScheduleRepo(db)
    await repo.update("drain_mail", actor=SYS, enabled=True)
    out = await repo.update("drain_mail", actor=SYS, enabled=False)
    assert out["enabled"] is False
    assert out["next_run_at"] is None


async def test_cron_change_recomputes_next_run_at(frozen_now, db) -> None:
    frozen_now["now"] = datetime(2026, 8, 30, 12, 30, 0, tzinfo=UTC)
    repo = JobScheduleRepo(db)
    await repo.update("drain_mail", actor=SYS, enabled=True, cron="*/10 * * * *")
    out = await repo.update("drain_mail", actor=SYS, cron="0 6 * * *")
    assert out["cron"] == "0 6 * * *"
    assert out["next_run_at"] == "2026-08-31T06:00:00+00:00"


async def test_bad_cron_rejected(db) -> None:
    with pytest.raises(DomainError) as exc:
        await JobScheduleRepo(db).update("drain_mail", actor=SYS, cron="not a cron")
    assert exc.value.code == "bad_cron"
    assert _audit_count(db) == 0


async def test_unknown_job_rejected(db) -> None:
    with pytest.raises(DomainError) as exc:
        await JobScheduleRepo(db).update("nope", actor=SYS, enabled=True)
    assert exc.value.code == "unknown_job"


async def test_empty_update_rejected(db) -> None:
    with pytest.raises(DomainError) as exc:
        await JobScheduleRepo(db).update("drain_mail", actor=SYS)
    assert exc.value.code == "no_changes"


async def test_noop_update_writes_no_audit_row(db) -> None:
    # drain_mail already ships disabled with this cron.
    out = await JobScheduleRepo(db).update(
        "drain_mail", actor=SYS, enabled=False, cron="*/10 * * * *"
    )
    assert out["enabled"] is False
    assert _audit_count(db) == 0


async def test_mark_started_and_finished_are_unaudited(frozen_now, db) -> None:
    repo = JobScheduleRepo(db)
    await repo.update("drain_mail", actor=SYS, enabled=True)
    audits_before = _audit_count(db)

    await repo.mark_started("drain_mail")
    assert repo.get("drain_mail")["last_status"] == "running"

    now = datetime(2026, 8, 30, 12, 5, 0, tzinfo=UTC)
    await repo.mark_finished(
        "drain_mail",
        now=now,
        status="ok",
        error=None,
        duration_ms=42,
        cron="*/10 * * * *",
    )
    row = repo.get("drain_mail")
    assert row["last_status"] == "ok"
    assert row["last_run_at"] == now.isoformat()
    assert row["last_duration_ms"] == 42
    assert row["next_run_at"] == "2026-08-30T12:10:00+00:00"
    assert _audit_count(db) == audits_before  # no new audit rows
