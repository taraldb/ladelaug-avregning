"""Imported charging data — sessions and 15-minute intervals (Epic 4).

``import_sessions`` takes parsed :class:`ZaptecSession` objects and writes them
idempotently (keyed by Zaptec id + local month). Sessions that cross a month
boundary are split (US-405): interval data first, pro-rata by duration as the
fallback. Each session part is attributed to the member holding the charger's
assignment on the part's start date; an unresolved part has ``member_id`` NULL
and counts as *unassigned consumption* (US-304).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.zaptec.client import ZaptecSession

# Session energy is stored to 2 decimals — the same precision Zaptec's
# "Charge history" report shows and totals — so our per-month kWh sum matches
# that report. ``_rebalance`` puts any cross-month rounding drift back on the
# largest part, so a split still sums to the (2-dp) session total.
_KWH = Decimal("0.01")
_SplitPart = tuple[str, datetime, datetime, Decimal, str]


def _q(value: Decimal) -> Decimal:
    return value.quantize(_KWH, rounding=ROUND_HALF_EVEN)


def _close(a: Decimal, b: Decimal) -> bool:
    """Interval sum is trusted only if it is within 1% (or 0.05 kWh) of the
    session total — otherwise fall back to duration apportionment."""
    diff = abs(a - b)
    return diff <= Decimal("0.05") or (b > 0 and diff / b <= Decimal("0.01"))


def _rebalance(parts: list[_SplitPart], total: Decimal, method: str) -> list[_SplitPart]:
    rounded = [(mk, ps, pe, _q(e), method) for (mk, ps, pe, e, _) in parts]
    drift = total - sum((p[3] for p in rounded), Decimal(0))
    if drift != 0:
        idx = max(range(len(rounded)), key=lambda i: rounded[i][3])
        mk, ps, pe, e, m = rounded[idx]
        rounded[idx] = (mk, ps, pe, e + drift, m)
    return rounded


class ChargingRepo:
    def __init__(self, db: Database, *, tz: str = clock.OSLO) -> None:
        self._db = db
        self._tz = tz

    # --- import ---------------------------------------------------------

    def _split(self, session: ZaptecSession) -> list[_SplitPart]:
        end_iso = session.ended_at or session.started_at
        spans = periods.split_across_months(session.started_at, end_iso, self._tz)
        total = _q(session.energy_kwh)
        if len(spans) == 1:
            mk, ps, pe = spans[0]
            return [(mk, ps, pe, total, "none")]

        if session.energy_details:
            by_month: dict[str, Decimal] = {}
            for pt in session.energy_details:
                mk = periods.month_key(pt.timestamp, self._tz)
                by_month[mk] = by_month.get(mk, Decimal(0)) + pt.energy_kwh
            covered = sum(by_month.values(), Decimal(0))
            if covered > 0 and _close(covered, total):
                parts = [
                    (mk, ps, pe, by_month.get(mk, Decimal(0)), "interval") for mk, ps, pe in spans
                ]
                return _rebalance(parts, total, "interval")

        secs = [periods.duration_seconds(ps, pe) for _, ps, pe in spans]
        span_total = sum(secs) or 1.0
        parts = [
            (mk, ps, pe, total * Decimal(str(sec)) / Decimal(str(span_total)), "duration")
            for (mk, ps, pe), sec in zip(spans, secs, strict=True)
        ]
        return _rebalance(parts, total, "duration")

    def _resolver(self, chargers: ChargerRepo):
        """Return ``(charger_id_for, member_for)`` closures that map an imported
        row to a local charger id (by zaptec_id, else by serial / DeviceId) and
        then to the member holding that charger on a given date."""
        idx = chargers.local_id_index()
        assignment_cache: dict[str, dict[int, int]] = {}

        def charger_id_for(zaptec_id: str, raw: Any) -> int | None:
            cid = idx["zaptec"].get(zaptec_id)
            if cid is not None:
                return cid
            dev = None
            if isinstance(raw, dict):
                dev = raw.get("DeviceId") or raw.get("SerialNo")
            if dev:
                return idx["serial"].get(str(dev).strip().lower())
            return None

        def member_for(charger_id: int | None, on_date: str) -> int | None:
            if charger_id is None:
                return None
            if on_date not in assignment_cache:
                assignment_cache[on_date] = chargers.assignment_map(on_date)
            return assignment_cache[on_date].get(charger_id)

        return charger_id_for, member_for

    async def import_sessions(
        self, sessions: list[ZaptecSession], *, actor: AuditContext
    ) -> dict[str, Any]:
        chargers = ChargerRepo(self._db)
        charger_id_for, member_for = self._resolver(chargers)

        now = clock.now_utc().isoformat()
        inserted = updated = interval_rows = split_sessions = 0
        touched_months: set[str] = set()

        async with self._db._write() as cur:
            for s in sessions:
                parts = self._split(s)
                if len(parts) > 1:
                    split_sessions += 1
                charger_id = charger_id_for(s.charger_zaptec_id, s.raw)
                payload = json.dumps(s.raw, sort_keys=True, default=str)

                for month, pstart, pend, energy, method in parts:
                    touched_months.add(month)
                    member_id = member_for(charger_id, pstart.date().isoformat())
                    energy_str = str(_q(energy))
                    row = cur.execute(
                        "SELECT id, energy_kwh, member_id, ended_at FROM charging_sessions "
                        "WHERE zaptec_session_id = ? AND period_month = ?",
                        (s.session_id, month),
                    ).fetchone()
                    if row is None:
                        cur.execute(
                            "INSERT INTO charging_sessions "
                            "(zaptec_session_id, charger_id, charger_zaptec_id, member_id, "
                            " period_month, started_at, ended_at, energy_kwh, split_method, "
                            " user_full_name, source, raw_json, imported_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'zaptec', ?, ?, ?)",
                            (
                                s.session_id,
                                charger_id,
                                s.charger_zaptec_id,
                                member_id,
                                month,
                                pstart.isoformat(),
                                pend.isoformat(),
                                energy_str,
                                method,
                                s.user_full_name,
                                payload,
                                now,
                                now,
                            ),
                        )
                        inserted += 1
                    else:
                        cur.execute(
                            "UPDATE charging_sessions SET charger_id = ?, member_id = ?, "
                            "started_at = ?, ended_at = ?, energy_kwh = ?, split_method = ?, "
                            "user_full_name = ?, raw_json = ?, updated_at = ? WHERE id = ?",
                            (
                                charger_id,
                                member_id,
                                pstart.isoformat(),
                                pend.isoformat(),
                                energy_str,
                                method,
                                s.user_full_name,
                                payload,
                                now,
                                row["id"],
                            ),
                        )
                        updated += 1

                for pt in s.energy_details:
                    imonth = periods.month_key(pt.timestamp, self._tz)
                    idate = periods.local_dt(pt.timestamp, self._tz).date().isoformat()
                    imember = member_for(charger_id, idate)
                    cur.execute(
                        "INSERT OR IGNORE INTO charging_intervals "
                        "(charger_zaptec_id, charger_id, member_id, period_month, interval_start, "
                        " energy_kwh, source_session_zaptec_id, raw_json, imported_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            s.charger_zaptec_id,
                            charger_id,
                            imember,
                            imonth,
                            pt.timestamp,
                            str(pt.energy_kwh),
                            s.session_id,
                            None,
                            now,
                        ),
                    )
                    interval_rows += max(cur.rowcount, 0)

            write_audit_row(
                cur,
                actor,
                event_type="charging.imported",
                entity_type="charging_import",
                entity_id=None,
                summary=(
                    f"Imported {inserted} new / {updated} updated session rows "
                    f"across {sorted(touched_months)}"
                ),
                detail={
                    "sessions_in": len(sessions),
                    "rows_inserted": inserted,
                    "rows_updated": updated,
                    "cross_month_sessions": split_sessions,
                    "interval_rows_inserted": interval_rows,
                    "months": sorted(touched_months),
                },
            )

        return {
            "sessions_in": len(sessions),
            "rows_inserted": inserted,
            "rows_updated": updated,
            "cross_month_sessions": split_sessions,
            "interval_rows_inserted": interval_rows,
            "months": sorted(touched_months),
        }

    async def reresolve_members(self, month: str, *, actor: AuditContext) -> dict[str, Any]:
        """Recompute ``charger_id`` and ``member_id`` for a month's sessions and
        intervals from the current chargers and assignments — run after an admin
        fills a gap that made consumption unassigned (US-304), or after a charger
        is created / adopted for usage that was imported before it existed."""
        chargers = ChargerRepo(self._db)
        charger_id_for, member_for = self._resolver(chargers)
        changed = 0
        async with self._db._write() as cur:
            rows = cur.execute(
                "SELECT id, charger_id, charger_zaptec_id, started_at, member_id, raw_json "
                "FROM charging_sessions WHERE period_month = ?",
                (month,),
            ).fetchall()
            for r in rows:
                raw = json.loads(r["raw_json"]) if r["raw_json"] else None
                cid = charger_id_for(r["charger_zaptec_id"], raw) or r["charger_id"]
                on_date = periods.local_dt(r["started_at"], self._tz).date().isoformat()
                resolved = member_for(cid, on_date)
                if cid != r["charger_id"] or resolved != r["member_id"]:
                    cur.execute(
                        "UPDATE charging_sessions SET charger_id = ?, member_id = ?, "
                        "updated_at = ? WHERE id = ?",
                        (cid, resolved, clock.now_utc().isoformat(), r["id"]),
                    )
                    changed += 1
            for r in cur.execute(
                "SELECT id, charger_id, charger_zaptec_id, interval_start, member_id "
                "FROM charging_intervals WHERE period_month = ?",
                (month,),
            ).fetchall():
                cid = charger_id_for(r["charger_zaptec_id"], None) or r["charger_id"]
                on_date = periods.local_dt(r["interval_start"], self._tz).date().isoformat()
                resolved = member_for(cid, on_date)
                if cid != r["charger_id"] or resolved != r["member_id"]:
                    cur.execute(
                        "UPDATE charging_intervals SET charger_id = ?, member_id = ? WHERE id = ?",
                        (cid, resolved, r["id"]),
                    )
            write_audit_row(
                cur,
                actor,
                event_type="charging.reresolved",
                entity_type="charging_import",
                entity_id=month,
                summary=f"Re-resolved members for {month}: {changed} session row(s) changed",
                detail={"month": month, "sessions_changed": changed},
            )
        return {"month": month, "sessions_changed": changed}

    def _posted_months(self) -> set[str]:
        rows = self._db.connection.execute(
            "SELECT period_month FROM settlements WHERE status = 'posted'"
        ).fetchall()
        return {r["period_month"] for r in rows}

    def _months_for_charger(self, charger_id: int, since_month: str | None) -> list[str]:
        row = self._db.connection.execute(
            "SELECT zaptec_id FROM chargers WHERE id = ?", (charger_id,)
        ).fetchone()
        zid = row["zaptec_id"] if row else None
        rows = self._db.connection.execute(
            "SELECT DISTINCT period_month FROM charging_sessions "
            "WHERE charger_id = ? OR (? IS NOT NULL AND charger_zaptec_id = ?) "
            "UNION "
            "SELECT DISTINCT period_month FROM charging_intervals "
            "WHERE charger_id = ? OR (? IS NOT NULL AND charger_zaptec_id = ?)",
            (charger_id, zid, zid, charger_id, zid, zid),
        ).fetchall()
        months = {r["period_month"] for r in rows}
        if since_month is not None:
            months = {m for m in months if m >= since_month}
        return sorted(months)

    async def reresolve_after_assignment(
        self, charger_id: int, *, since_month: str | None = None, actor: AuditContext
    ) -> dict[str, Any]:
        """Re-resolve every non-posted month that has usage for ``charger_id``.
        Called after an assignment is opened or closed so that already-imported
        sessions pick up the change without a re-sync."""
        posted = self._posted_months()
        touched = []
        for month in self._months_for_charger(charger_id, since_month):
            if month in posted:
                continue
            await self.reresolve_members(month, actor=actor)
            touched.append(month)
        return {"months": touched}

    async def reresolve_unresolved(self, *, actor: AuditContext) -> dict[str, Any]:
        """Re-resolve every non-posted month that still has unattributed sessions.
        Called after a charger sync so usage imported before the charger existed
        gets attributed once the charger (and its assignment) is present."""
        posted = self._posted_months()
        rows = self._db.connection.execute(
            "SELECT DISTINCT period_month FROM charging_sessions WHERE member_id IS NULL"
        ).fetchall()
        touched = []
        for r in rows:
            month = r["period_month"]
            if month in posted:
                continue
            await self.reresolve_members(month, actor=actor)
            touched.append(month)
        return {"months": touched}

    # --- reads --------------------------------------------------------

    def consumption_by_member(self, month: str) -> dict[int, Decimal]:
        rows = self._db.connection.execute(
            "SELECT member_id, energy_kwh FROM charging_sessions "
            "WHERE period_month = ? AND member_id IS NOT NULL",
            (month,),
        ).fetchall()
        out: dict[int, Decimal] = {}
        for r in rows:
            out[int(r["member_id"])] = out.get(int(r["member_id"]), Decimal(0)) + Decimal(
                r["energy_kwh"]
            )
        return out

    def member_consumption(self, member_id: int, month: str) -> Decimal:
        """That member's metered kWh for the month, before any settlement (US-902)."""
        return self.consumption_by_member(month).get(member_id, Decimal(0))

    def member_session_count(self, member_id: int, month: str) -> int:
        return int(
            self._db.connection.execute(
                "SELECT COUNT(*) FROM charging_sessions WHERE period_month = ? AND member_id = ?",
                (month, member_id),
            ).fetchone()[0]
        )

    def total_kwh(self, month: str) -> Decimal:
        rows = self._db.connection.execute(
            "SELECT energy_kwh FROM charging_sessions WHERE period_month = ?", (month,)
        ).fetchall()
        return sum((Decimal(r["energy_kwh"]) for r in rows), Decimal(0))

    def unassigned_consumption(self, month: str) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT cs.charger_zaptec_id AS zid, cs.charger_id AS cid, c.name AS name, "
            "       cs.energy_kwh AS e "
            "FROM charging_sessions cs LEFT JOIN chargers c ON c.id = cs.charger_id "
            "WHERE cs.period_month = ? AND cs.member_id IS NULL",
            (month,),
        ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for r in rows:
            g = grouped.setdefault(
                r["zid"],
                {
                    "charger_zaptec_id": r["zid"],
                    "charger_id": r["cid"],
                    "charger_name": r["name"],
                    "sessions": 0,
                    "energy_kwh": Decimal(0),
                },
            )
            g["sessions"] += 1
            g["energy_kwh"] += Decimal(r["e"])
        return sorted(grouped.values(), key=lambda g: str(g["charger_zaptec_id"]))

    def unassigned_total_kwh(self, month: str) -> Decimal:
        return sum((g["energy_kwh"] for g in self.unassigned_consumption(month)), Decimal(0))

    def list_sessions(
        self, month: str, *, member_id: int | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        conn = self._db.connection
        where = "period_month = ?"
        args: list[Any] = [month]
        if member_id is not None:
            where += " AND member_id = ?"
            args.append(member_id)
        total = conn.execute(
            f"SELECT COUNT(*) FROM charging_sessions WHERE {where}", args
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM charging_sessions WHERE {where} ORDER BY started_at, id "
            "LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], int(total)
