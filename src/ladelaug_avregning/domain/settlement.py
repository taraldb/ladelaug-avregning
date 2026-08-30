"""Monthly settlement engine (Epic 6).

Lifecycle: ``create_draft`` -> add invoice lines / set invoice kWh / attach the
invoice PDF -> ``freeze`` (snapshot participation + consumption + balances) ->
``preview`` (compute allocations, no writes) -> ``post`` (write one
``settlement_charge`` ledger row per member; irreversible).

Allocation (US-606 / US-607 / US-610):

* ``equal`` lines split across members flagged ``participates_equal`` in the
  frozen snapshot;
* ``consumption`` lines split across every snapshot member by their kWh share
  (a member who did not charge pays 0);
* every line's øre are apportioned by :func:`money.allocate_by_weights`, which
  is total-preserving — the residual øre land on the largest weight.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import allocate_by_weights, nok_to_ore, ore_to_nok, parse_nok

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _ore_nok(ore: int) -> tuple[int, str]:
    return ore, str(ore_to_nok(ore))


class SettlementRepo:
    def __init__(
        self, db: Database, *, tz: str = clock.OSLO, state_dir: Path | str | None = None
    ) -> None:
        self._db = db
        self._tz = tz
        if state_dir is not None:
            self._state = Path(state_dir)
        elif db.path and db.path != ":memory:":
            self._state = Path(db.path).parent
        else:
            self._state = Path("state")

    # --- draft lifecycle (US-601) ---------------------------------------

    async def create_draft(self, period_month: str, *, actor: AuditContext) -> dict[str, Any]:
        if not periods.valid_month(period_month):
            raise DomainError("bad_month", "period_month must be YYYY-MM")
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            try:
                cur.execute(
                    "INSERT INTO settlements (period_month, status, created_at, created_by_user_id) "
                    "VALUES (?, 'draft', ?, ?)",
                    (period_month, now, actor.actor_user_id),
                )
            except sqlite3.IntegrityError as exc:
                if "period_month" in str(exc):
                    raise DomainError(
                        "month_taken", f"A settlement for {period_month} already exists."
                    ) from exc
                raise
            sid = int(cur.lastrowid or 0)
            write_audit_row(
                cur,
                actor,
                event_type="settlement.created",
                entity_type="settlement",
                entity_id=sid,
                summary=f"Settlement draft for {period_month} created",
                detail={"period_month": period_month},
            )
        return self._require(sid)

    def get(self, settlement_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM settlements WHERE id = ?", (settlement_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_month(self, month: str) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM settlements WHERE period_month = ?", (month,)
        ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM settlements ORDER BY period_month DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def lines(self, settlement_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM settlement_invoice_lines WHERE settlement_id = ? "
            "ORDER BY sort_order, id",
            (settlement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def snapshot_members(self, settlement_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM settlement_members WHERE settlement_id = ? ORDER BY member_id",
            (settlement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def allocations(self, settlement_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM settlement_allocations WHERE settlement_id = ? ORDER BY member_id, id",
            (settlement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- invoice + lines (US-603 / US-605) ----------------------------

    async def set_invoice(
        self,
        settlement_id: int,
        *,
        invoice_kwh: Decimal | str | None = None,
        note: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        self._require_draft(settlement_id)
        kwh = None if invoice_kwh in (None, "") else str(parse_nok(invoice_kwh))
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE settlements SET invoice_kwh = COALESCE(?, invoice_kwh), "
                "note = COALESCE(?, note) WHERE id = ?",
                (kwh, note, settlement_id),
            )
            write_audit_row(
                cur,
                actor,
                event_type="settlement.invoice_set",
                entity_type="settlement",
                entity_id=settlement_id,
                summary=f"Settlement {settlement_id} invoice kWh set to {kwh}",
                detail={"invoice_kwh": kwh, "note": note},
            )
        return self._require(settlement_id)

    async def add_line(
        self,
        settlement_id: int,
        *,
        description: str,
        allocation_method: str,
        amount: Decimal | str,
        category: str | None = None,
        sort_order: int | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        self._require_draft(settlement_id)
        description = (description or "").strip()
        if not description:
            raise DomainError("description_required", "An invoice line needs a description.")
        if allocation_method not in ("equal", "consumption"):
            raise DomainError("bad_method", "allocation_method must be 'equal' or 'consumption'.")
        amount_dec = parse_nok(amount)
        if amount_dec <= 0:
            raise DomainError("bad_amount", "line amount must be positive")
        ore, nok = _ore_nok(nok_to_ore(amount_dec))
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            order = (
                sort_order
                if sort_order is not None
                else int(
                    cur.execute(
                        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM settlement_invoice_lines "
                        "WHERE settlement_id = ?",
                        (settlement_id,),
                    ).fetchone()[0]
                )
            )
            cur.execute(
                "INSERT INTO settlement_invoice_lines "
                "(settlement_id, description, category, allocation_method, amount_ore, amount_nok, "
                " sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (settlement_id, description, category, allocation_method, ore, nok, order, now),
            )
            line_id = int(cur.lastrowid or 0)
            self._sync_invoice_total(cur, settlement_id)
            write_audit_row(
                cur,
                actor,
                event_type="settlement.line_added",
                entity_type="settlement",
                entity_id=settlement_id,
                summary=f"Line {description!r} ({allocation_method}, {nok} NOK) added",
                detail={
                    "line_id": line_id,
                    "description": description,
                    "allocation_method": allocation_method,
                    "amount_nok": nok,
                    "category": category,
                },
            )
        return dict(
            self._db.connection.execute(
                "SELECT * FROM settlement_invoice_lines WHERE id = ?", (line_id,)
            ).fetchone()
        )

    async def delete_line(self, settlement_id: int, line_id: int, *, actor: AuditContext) -> None:
        self._require_draft(settlement_id)
        async with self._db._write() as cur:
            row = cur.execute(
                "SELECT * FROM settlement_invoice_lines WHERE id = ? AND settlement_id = ?",
                (line_id, settlement_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"invoice line {line_id} not found")
            cur.execute("DELETE FROM settlement_invoice_lines WHERE id = ?", (line_id,))
            self._sync_invoice_total(cur, settlement_id)
            write_audit_row(
                cur,
                actor,
                event_type="settlement.line_deleted",
                entity_type="settlement",
                entity_id=settlement_id,
                summary=f"Line {line_id} ({row['description']!r}) removed",
                detail={"line_id": line_id, "description": row["description"]},
            )

    async def attach_invoice(
        self, settlement_id: int, *, filename: str, content: bytes, actor: AuditContext
    ) -> dict[str, Any]:
        self._require_draft(settlement_id)
        if not content:
            raise DomainError("empty_file", "The attachment is empty.")
        safe = _SAFE_NAME.sub("_", Path(filename or "invoice.pdf").name) or "invoice.pdf"
        rel = Path("attachments") / str(settlement_id) / safe
        dest = self._state / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        async with self._db._write() as cur:
            cur.execute(
                "UPDATE settlements SET attachment_filename = ?, attachment_path = ? WHERE id = ?",
                (safe, str(rel), settlement_id),
            )
            write_audit_row(
                cur,
                actor,
                event_type="settlement.invoice_attached",
                entity_type="settlement",
                entity_id=settlement_id,
                summary=f"Invoice attachment {safe!r} stored for settlement {settlement_id}",
                detail={"filename": safe, "bytes": len(content)},
            )
        return self._require(settlement_id)

    def attachment_path(self, settlement_id: int) -> Path | None:
        row = self.get(settlement_id)
        if not row or not row["attachment_path"]:
            return None
        return self._state / row["attachment_path"]

    # --- freeze (US-602) ---------------------------------------------

    async def freeze(self, settlement_id: int, *, actor: AuditContext) -> dict[str, Any]:
        row = self._require_draft(settlement_id)
        month = row["period_month"]
        as_of = periods.last_day(month)
        members = MemberRepo(self._db)
        charging = ChargingRepo(self._db, tz=self._tz)
        ledger = LedgerRepo(self._db)

        unassigned = charging.unassigned_total_kwh(month)
        if unassigned > 0:
            raise DomainError(
                "unassigned_consumption",
                f"{unassigned} kWh in {month} is on chargers with no member assignment — "
                "resolve it before freezing (US-304).",
                status=422,
            )

        consumption = charging.consumption_by_member(month)
        session_counts = self._session_counts(month)
        status_map = members.status_map(as_of)
        explicit = members.explicit_participation_map(as_of)
        active = {mid for mid, s in status_map.items() if s == "active"}

        def participates(mid: int) -> bool:
            if mid in explicit:
                return explicit[mid]
            return mid in active

        snapshot: list[dict[str, Any]] = []
        for m in members.list():
            mid = m["id"]
            is_active = mid in active
            kwh = consumption.get(mid, Decimal(0))
            if not is_active and kwh == 0:
                continue
            snapshot.append(
                {
                    "member_id": mid,
                    "member_reference": m["member_reference"],
                    "full_name": m["full_name"],
                    "is_active": int(is_active),
                    "participates_equal": int(is_active and participates(mid)),
                    "consumption_kwh": str(kwh),
                    "session_count": session_counts.get(mid, 0),
                    "balance_before_ore": ledger.balance_ore(mid),
                }
            )

        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            cur.execute("DELETE FROM settlement_members WHERE settlement_id = ?", (settlement_id,))
            cur.execute(
                "DELETE FROM settlement_allocations WHERE settlement_id = ?", (settlement_id,)
            )
            for s in snapshot:
                cur.execute(
                    "INSERT INTO settlement_members "
                    "(settlement_id, member_id, member_reference, full_name, is_active, "
                    " participates_equal, consumption_kwh, session_count, balance_before_ore, "
                    " snapshot_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        settlement_id,
                        s["member_id"],
                        s["member_reference"],
                        s["full_name"],
                        s["is_active"],
                        s["participates_equal"],
                        s["consumption_kwh"],
                        s["session_count"],
                        s["balance_before_ore"],
                        json.dumps(s),
                    ),
                )
            cur.execute(
                "UPDATE settlements SET usage_frozen_at = ?, grid_kwh = ? WHERE id = ?",
                (now, str(charging.total_kwh(month)), settlement_id),
            )
            write_audit_row(
                cur,
                actor,
                event_type="settlement.usage_frozen",
                entity_type="settlement",
                entity_id=settlement_id,
                summary=f"Settlement {settlement_id} usage frozen: {len(snapshot)} members, "
                f"{charging.total_kwh(month)} kWh metered",
                detail={
                    "as_of": as_of,
                    "member_count": len(snapshot),
                    "grid_kwh": str(charging.total_kwh(month)),
                    "equal_participants": sum(s["participates_equal"] for s in snapshot),
                },
            )
        return self._require(settlement_id)

    # --- compute / preview (US-606..610) ---------------------------

    def compute(self, settlement_id: int) -> dict[str, Any]:
        row = self._require(settlement_id)
        if not row["usage_frozen_at"]:
            raise DomainError("not_frozen", "Freeze the usage snapshot before computing.")
        snap = self.snapshot_members(settlement_id)
        lines = self.lines(settlement_id)
        month = row["period_month"]

        members_by_id = {m["member_id"]: m for m in snap}
        equal_ids = [m["member_id"] for m in snap if m["participates_equal"]]
        all_ids = [m["member_id"] for m in snap]

        per_member_lines: dict[int, list[dict[str, Any]]] = {mid: [] for mid in all_ids}
        line_breakdown: list[dict[str, Any]] = []

        for ln in lines:
            if ln["allocation_method"] == "equal":
                targets = equal_ids
                weights: list[Decimal] = [Decimal(1)] * len(targets)
            else:
                targets = all_ids
                weights = [Decimal(members_by_id[mid]["consumption_kwh"]) for mid in targets]
            if not targets:
                shares: list[int] = []
            else:
                shares = allocate_by_weights(int(ln["amount_ore"]), weights)
            for mid, share in zip(targets, shares, strict=True):
                if share == 0 and ln["allocation_method"] == "consumption":
                    continue
                per_member_lines[mid].append(
                    {
                        "invoice_line_id": ln["id"],
                        "description": ln["description"],
                        "kind": ln["allocation_method"],
                        "amount_ore": share,
                        "amount_nok": str(ore_to_nok(share)),
                    }
                )
            line_breakdown.append(
                {
                    "line_id": ln["id"],
                    "description": ln["description"],
                    "kind": ln["allocation_method"],
                    "amount_ore": int(ln["amount_ore"]),
                    "allocated_ore": sum(shares),
                    "recipients": len([s for s in shares if s != 0]),
                }
            )

        members_out: list[dict[str, Any]] = []
        total_charged = 0
        negatives: list[int] = []
        for m in snap:
            mid = m["member_id"]
            charge = sum(a["amount_ore"] for a in per_member_lines[mid])
            before = int(m["balance_before_ore"] or 0)
            after = before - charge
            total_charged += charge
            if after < 0:
                negatives.append(mid)
            members_out.append(
                {
                    "member_id": mid,
                    "member_reference": m["member_reference"],
                    "full_name": m["full_name"],
                    "is_active": bool(m["is_active"]),
                    "participates_equal": bool(m["participates_equal"]),
                    "consumption_kwh": m["consumption_kwh"],
                    "session_count": m["session_count"],
                    "balance_before_ore": before,
                    "balance_before_nok": str(ore_to_nok(before)),
                    "charge_ore": charge,
                    "charge_nok": str(ore_to_nok(charge)),
                    "balance_after_ore": after,
                    "balance_after_nok": str(ore_to_nok(after)),
                    "lines": per_member_lines[mid],
                }
            )

        invoice_lines_total = sum(int(ln["amount_ore"]) for ln in lines)
        warnings: list[dict[str, Any]] = []
        if negatives:
            warnings.append({"code": "negative_balances", "member_ids": negatives})
        if not row["invoice_kwh"]:
            warnings.append({"code": "invoice_kwh_missing"})
        if not row["attachment_path"]:
            warnings.append({"code": "attachment_missing"})
        if any(ln["allocation_method"] == "consumption" for ln in lines):
            csum = sum(Decimal(m["consumption_kwh"]) for m in snap)
            if csum == 0:
                warnings.append({"code": "zero_consumption"})
        late = self._unresolved_late(month)
        if late:
            warnings.append({"code": "late_sessions", "count": late})
        if self._usage_changed_since(month, row["usage_frozen_at"]):
            warnings.append({"code": "usage_stale"})
        if row["invoice_kwh"] and row["grid_kwh"]:
            diff = abs(Decimal(row["invoice_kwh"]) - Decimal(row["grid_kwh"]))
            if Decimal(row["grid_kwh"]) > 0 and diff / Decimal(row["grid_kwh"]) > Decimal("0.1"):
                warnings.append(
                    {
                        "code": "kwh_mismatch",
                        "invoice_kwh": row["invoice_kwh"],
                        "grid_kwh": row["grid_kwh"],
                    }
                )

        return {
            "settlement_id": settlement_id,
            "period_month": month,
            "status": row["status"],
            "invoice_kwh": row["invoice_kwh"],
            "grid_kwh": row["grid_kwh"],
            "invoice_lines_total_ore": invoice_lines_total,
            "invoice_lines_total_nok": str(ore_to_nok(invoice_lines_total)),
            "total_charged_ore": total_charged,
            "total_charged_nok": str(ore_to_nok(total_charged)),
            "members": members_out,
            "lines": line_breakdown,
            "warnings": warnings,
        }

    def preview(self, settlement_id: int) -> dict[str, Any]:
        return self.compute(settlement_id)

    def member_entry(self, settlement_id: int, member_id: int) -> dict[str, Any] | None:
        """``{"result": <compute>, "member": <that member's row>}`` or None if
        the member is not in the settlement's snapshot."""
        result = self.compute(settlement_id)
        for m in result["members"]:
            if m["member_id"] == member_id:
                return {"result": result, "member": m}
        return None

    def posted_for_member(self, member_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT s.* FROM settlements s "
            "JOIN settlement_members sm ON sm.settlement_id = s.id "
            "WHERE sm.member_id = ? AND s.status = 'posted' "
            "ORDER BY s.period_month DESC",
            (member_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- post (US-609) ---------------------------------------------

    async def post(self, settlement_id: int, *, actor: AuditContext) -> dict[str, Any]:
        row = self._require(settlement_id)
        if row["status"] == "posted":
            raise DomainError("already_posted", f"Settlement {settlement_id} is already posted.")
        if not row["usage_frozen_at"]:
            raise DomainError("not_frozen", "Freeze the usage snapshot before posting.")
        lines = self.lines(settlement_id)
        if not lines:
            raise DomainError("no_lines", "Add at least one invoice line before posting.")
        if not row["invoice_kwh"]:
            raise DomainError(
                "invoice_kwh_required", "Set the invoice kWh before posting (US-603)."
            )
        if not row["attachment_path"]:
            raise DomainError("attachment_required", "Attach the invoice before posting (US-604).")

        month = row["period_month"]
        charging = ChargingRepo(self._db, tz=self._tz)
        if charging.unassigned_total_kwh(month) > 0:
            raise DomainError(
                "unassigned_consumption", f"Unassigned consumption in {month} — re-freeze first."
            )
        result = self.compute(settlement_id)
        if (
            any(ln["allocation_method"] == "consumption" for ln in lines)
            and sum(Decimal(m["consumption_kwh"]) for m in self.snapshot_members(settlement_id))
            == 0
        ):
            raise DomainError(
                "zero_consumption",
                "A consumption line cannot be allocated when total consumption is zero (US-607).",
            )

        value_date = periods.last_day(month)
        now = clock.now_utc().isoformat()
        posted_members = 0
        async with self._db._write() as cur:
            cur.execute(
                "DELETE FROM settlement_allocations WHERE settlement_id = ?", (settlement_id,)
            )
            for m in result["members"]:
                for a in m["lines"]:
                    cur.execute(
                        "INSERT INTO settlement_allocations "
                        "(settlement_id, member_id, invoice_line_id, kind, amount_ore, amount_nok) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            settlement_id,
                            m["member_id"],
                            a["invoice_line_id"],
                            a["kind"],
                            a["amount_ore"],
                            a["amount_nok"],
                        ),
                    )
                if m["charge_ore"] == 0:
                    continue
                ore, nok = _ore_nok(-int(m["charge_ore"]))
                cur.execute(
                    "INSERT INTO ledger_transactions "
                    "(member_id, txn_type, amount_ore, amount_nok, currency, value_date, reason, "
                    " reference, settlement_id, created_by_user_id, recorded_at) "
                    "VALUES (?, 'settlement_charge', ?, ?, 'NOK', ?, ?, ?, ?, ?, ?)",
                    (
                        m["member_id"],
                        ore,
                        nok,
                        value_date,
                        f"Settlement {month}",
                        month,
                        settlement_id,
                        actor.actor_user_id,
                        now,
                    ),
                )
                posted_members += 1
            cur.execute(
                "UPDATE settlements SET status = 'posted', posted_at = ?, posted_by_user_id = ? "
                "WHERE id = ?",
                (now, actor.actor_user_id, settlement_id),
            )
            write_audit_row(
                cur,
                actor,
                event_type="settlement.posted",
                entity_type="settlement",
                entity_id=settlement_id,
                summary=f"Settlement {month} posted: {posted_members} members charged "
                f"{result['total_charged_nok']} NOK total",
                detail={
                    "period_month": month,
                    "total_charged_ore": result["total_charged_ore"],
                    "members_charged": posted_members,
                    "lines": result["lines"],
                    "per_member": [
                        {"member_id": m["member_id"], "charge_ore": m["charge_ore"]}
                        for m in result["members"]
                    ],
                    "warnings": result["warnings"],
                },
            )

        posted = {**result, "status": "posted", "members_charged": posted_members}

        # Forecast per member, computed *after* the ledger rows land so the
        # report's balance reflects the just-posted charge (decision C10).
        # Best-effort — a forecast failure must never break a post.
        forecasts: dict[int, dict[str, Any]] = {}
        with contextlib.suppress(Exception):
            from ladelaug_avregning.domain.forecast import ForecastRepo

            frepo = ForecastRepo(self._db)
            forecasts = {
                m["member_id"]: frepo.member_forecast(m["member_id"]) for m in result["members"]
            }
        try:
            from ladelaug_avregning.reports import write_reports

            write_reports(
                posted,
                self.snapshot_members(settlement_id),
                self._state / "reports" / month,
                forecasts,
            )
        except OSError:  # pragma: no cover - report write must not break a post
            pass
        return posted

    # --- internals -----------------------------------------------

    def _require(self, settlement_id: int) -> dict[str, Any]:
        row = self.get(settlement_id)
        if row is None:
            raise NotFoundError(f"settlement {settlement_id} not found")
        return row

    def _require_draft(self, settlement_id: int) -> dict[str, Any]:
        row = self._require(settlement_id)
        if row["status"] != "draft":
            raise DomainError("not_draft", f"Settlement {settlement_id} is {row['status']}.")
        return row

    @staticmethod
    def _sync_invoice_total(cur: sqlite3.Cursor, settlement_id: int) -> None:
        total = cur.execute(
            "SELECT COALESCE(SUM(amount_ore), 0) FROM settlement_invoice_lines "
            "WHERE settlement_id = ?",
            (settlement_id,),
        ).fetchone()[0]
        cur.execute(
            "UPDATE settlements SET invoice_total_nok = ? WHERE id = ?",
            (str(ore_to_nok(int(total))), settlement_id),
        )

    def _session_counts(self, month: str) -> dict[int, int]:
        rows = self._db.connection.execute(
            "SELECT member_id, COUNT(*) AS n FROM charging_sessions "
            "WHERE period_month = ? AND member_id IS NOT NULL GROUP BY member_id",
            (month,),
        ).fetchall()
        return {int(r["member_id"]): int(r["n"]) for r in rows}

    def _usage_changed_since(self, month: str, frozen_at: str | None) -> bool:
        """True if the month still has unassigned consumption, or any session
        row was imported / re-resolved after the snapshot was frozen — the
        frozen numbers no longer match the imported usage, so re-freeze."""
        if not frozen_at:
            return False
        if ChargingRepo(self._db, tz=self._tz).unassigned_total_kwh(month) > 0:
            return True
        latest = self._db.connection.execute(
            "SELECT MAX(updated_at) FROM charging_sessions WHERE period_month = ?",
            (month,),
        ).fetchone()[0]
        return bool(latest and latest > frozen_at)

    def _unresolved_late(self, month: str) -> int:
        return int(
            self._db.connection.execute(
                "SELECT COUNT(*) FROM late_session_flags "
                "WHERE period_month = ? AND resolved_at IS NULL",
                (month,),
            ).fetchone()[0]
        )
