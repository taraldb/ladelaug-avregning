"""``job_schedules`` read/write — the admin-tunable schedule + run state for the
in-process scheduler (migration 0011).

Modelled on :class:`~ladelaug_avregning.domain.forecast.ForecastRepo`: reads go
straight to ``db.connection``; ``update`` validates, diffs, then writes the row
plus one audit event in a single ``_write()`` transaction. The scheduler's own
bookkeeping (``mark_started`` / ``mark_finished``) is deliberately unaudited — it
fires every few minutes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from croniter import croniter

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.scheduler.jobs import KNOWN_JOBS


def next_run_after(cron: str, after: datetime) -> str:
    """Next fire time strictly after ``after``, as an ISO8601 string."""
    return croniter(cron, after).get_next(datetime).isoformat()


class JobScheduleRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- reads -------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        rows = self._db.connection.execute("SELECT * FROM job_schedules ORDER BY name").fetchall()
        return [self._shape(r) for r in rows]

    def get(self, name: str) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM job_schedules WHERE name = ?", (name,)
        ).fetchone()
        return self._shape(row) if row is not None else None

    @staticmethod
    def _shape(row: Any) -> dict[str, Any]:
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    # --- admin update (audited) -----------------------------------

    async def update(
        self,
        name: str,
        *,
        actor: AuditContext,
        enabled: bool | None = None,
        cron: str | None = None,
    ) -> dict[str, Any]:
        if name not in KNOWN_JOBS:
            raise DomainError("unknown_job", f"unknown job {name!r}")
        current = self.get(name)
        if current is None:  # pragma: no cover - seeded by migration 0011
            raise DomainError("unknown_job", f"job {name!r} has no schedule row")

        if cron is not None and not croniter.is_valid(cron):
            raise DomainError("bad_cron", f"{cron!r} is not a valid cron expression")
        if enabled is None and cron is None:
            raise DomainError("no_changes", "Provide 'enabled' and/or 'cron'.")

        changed: dict[str, Any] = {}
        if enabled is not None and enabled != current["enabled"]:
            changed["enabled"] = 1 if enabled else 0
        if cron is not None and cron != current["cron"]:
            changed["cron"] = cron
        if not changed:
            return current

        now = clock.now_utc()
        eff_enabled = enabled if enabled is not None else current["enabled"]
        eff_cron = cron if cron is not None else current["cron"]
        if not eff_enabled:
            next_run_at: str | None = None
        elif "cron" in changed or "enabled" in changed or current["next_run_at"] is None:
            next_run_at = next_run_after(eff_cron, now)
        else:
            next_run_at = current["next_run_at"]

        assignments = ", ".join(f"{k} = ?" for k in changed)
        async with self._db._write() as cur:
            cur.execute(
                f"UPDATE job_schedules SET {assignments}, next_run_at = ?, "
                "updated_at = ?, updated_by_user_id = ? WHERE name = ?",
                (*changed.values(), next_run_at, now.isoformat(), actor.actor_user_id, name),
            )
            write_audit_row(
                cur,
                actor,
                event_type="system.job_schedule_updated",
                entity_type="job_schedules",
                entity_id=name,
                summary=f"Job schedule updated: {name} ({', '.join(sorted(changed))})",
                detail={
                    "before": {k: current[k] for k in changed},
                    "after": {k: (bool(v) if k == "enabled" else v) for k, v in changed.items()},
                },
            )
        return self.get(name)  # type: ignore[return-value]

    # --- scheduler bookkeeping (not audited) ----------------------

    async def mark_started(self, name: str) -> None:
        async with self._db._write() as cur:
            cur.execute("UPDATE job_schedules SET last_status = 'running' WHERE name = ?", (name,))

    async def mark_finished(
        self,
        name: str,
        *,
        now: datetime,
        status: str,
        error: str | None,
        duration_ms: int,
        cron: str,
    ) -> None:
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE job_schedules SET last_run_at = ?, last_status = ?, last_error = ?, "
                "last_duration_ms = ?, next_run_at = ? WHERE name = ?",
                (
                    now.isoformat(),
                    status,
                    error,
                    duration_ms,
                    next_run_after(cron, now),
                    name,
                ),
            )
