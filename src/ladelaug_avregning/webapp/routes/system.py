"""Operational health for admins (US-1104): Zaptec sync state, email queue,
failed jobs, versions — plus the in-process job scheduler (migration 0011):
``/api/system/jobs`` lists the schedules, ``PUT`` tunes one, ``POST .../run``
fires one now. The audit row for a schedule change is written by
``JobScheduleRepo.update`` inside its own locked transaction.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning import __version__
from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.access import AccessRepo
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.domain.job_schedules import JobScheduleRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.scheduler.runner import run_job_once
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import JobScheduleIn, JobScheduleOut

router = APIRouter(prefix="/api/system", dependencies=[Depends(require_admin)], tags=["system"])


@router.get("/health")
async def health(
    db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    from ladelaug_avregning.reports.pdf import PDF_AVAILABLE, PDF_IMPORT_ERROR

    runs = SyncRunRepo(db)
    notif = NotificationRepo(db)
    schema_version = db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
        0
    ]
    email_stats = notif.stats()
    warned_total = db.connection.execute(
        "SELECT COUNT(*) FROM low_balance_notifications"
    ).fetchone()[0]
    members_below = sum(
        1 for f in ForecastRepo(db).all_member_forecasts() if f["available"] and f["low_balance"]
    )
    low_balance = {"warned_total": int(warned_total), "members_below": members_below}
    srepo = SettlementRepo(db, tz=config.timezone)
    corrections = {
        "settlements_with_pending": sum(
            1
            for s in srepo.list()
            if s["status"] == "posted" and srepo.has_pending_correction(int(s["id"]))
        )
    }
    access = {"disabled": AccessRepo(db).disabled_count()}
    zaptec = {
        "enabled": config.zaptec.enabled,
        "installation_id": config.zaptec.installation_id or None,
        "last": {k: runs.latest(k) for k in ("chargers", "sessions", "intervals")},
        "failed_runs": runs.failure_count(),
    }
    jobs = JobScheduleRepo(db).list()
    jobs_failed = sum(1 for j in jobs if j["last_status"] == "error")
    return {
        "version": __version__,
        "schema_version": schema_version,
        "scheduler": {"enabled": config.scheduler.enabled, "jobs": jobs},
        "zaptec": zaptec,
        "email": email_stats,
        "pdf": {"available": PDF_AVAILABLE, "error": PDF_IMPORT_ERROR},
        "low_balance": low_balance,
        "corrections": corrections,
        "access": access,
        "failed_jobs": email_stats["failed"] + zaptec["failed_runs"] + jobs_failed,
        "ok": email_stats["failed"] == 0 and zaptec["failed_runs"] == 0 and jobs_failed == 0,
    }


@router.get("/jobs")
async def list_jobs(db: Database = Depends(get_db)) -> dict[str, Any]:
    return {"jobs": [JobScheduleOut.from_row(r) for r in JobScheduleRepo(db).list()]}


@router.put("/jobs/{name}", dependencies=[Depends(require_fetch)])
async def update_job(
    name: str,
    body: JobScheduleIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> JobScheduleOut:
    updated = await JobScheduleRepo(db).update(name, actor=actor, **body.to_update_kwargs())
    return JobScheduleOut.from_row(updated)


@router.post("/jobs/{name}/run", dependencies=[Depends(require_fetch)])
async def run_job_now(
    name: str,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    if JobScheduleRepo(db).get(name) is None:
        raise DomainError("unknown_job", f"unknown job {name!r}")
    outcome = await run_job_once(db, config, name)
    await record_audit(
        db,
        actor,
        event_type="system.job_triggered",
        entity_type="job_schedule",
        entity_id=name,
        summary=f"Admin ran job {name!r} manually ({outcome['status']})",
        detail={
            "status": outcome["status"],
            "error": outcome["error"],
            "duration_ms": outcome["duration_ms"],
        },
    )
    return outcome
