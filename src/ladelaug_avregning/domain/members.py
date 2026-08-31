"""Member records and their effective-dated status / settlement participation.

A *member* is the billing entity the monthly settlement is split across; its
login, if any, is `users.member_id`. Two effective-dated timelines hang off a
member, both half-open `[effective_from, effective_to)` with `effective_to IS
NULL` = open and at most one open row (partial unique indexes `idx_msp_one_open`
/ `idx_sp_one_open`):

* `member_status_periods` — active / inactive (US-202).
* `settlement_participation` — included in / excluded from *equal-cost*
  allocation (US-203). Excluded members still receive *consumption* costs.

Changing a timeline closes the current open row at the new `effective_from` and
inserts a new open row, under the write lock, in the same transaction as its
audit event.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import DomainError, NotFoundError

_UNSET: Any = object()


def _iso_date(value: str | None) -> str:
    """Normalise an optional YYYY-MM-DD string, defaulting to today (Europe/Oslo)."""
    if value is None:
        return clock.today_oslo().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise DomainError("bad_date", f"{value!r} is not a valid YYYY-MM-DD date.") from exc


class MemberRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- member records (US-201) -------------------------------------------------

    async def create(
        self,
        *,
        member_reference: str,
        full_name: str,
        email: str | None,
        join_date: str,
        actor: AuditContext,
    ) -> dict[str, Any]:
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            try:
                cur.execute(
                    "INSERT INTO members "
                    "(member_reference, full_name, email, join_date, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (member_reference, full_name, email, join_date, now, now),
                )
            except sqlite3.IntegrityError as exc:
                if "member_reference" in str(exc):
                    raise DomainError(
                        "reference_taken", "That member reference is already in use."
                    ) from exc
                raise
            member_id = int(cur.lastrowid or 0)
            write_audit_row(
                cur,
                actor,
                event_type="member.created",
                entity_type="member",
                entity_id=member_id,
                summary=f"Member {member_reference} ({full_name}) created",
                detail={"full_name": full_name, "email": email, "join_date": join_date},
            )
        return self._require(member_id)

    def get(self, member_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM members ORDER BY member_reference"
        ).fetchall()
        return [dict(r) for r in rows]

    async def update(
        self,
        member_id: int,
        *,
        member_reference: Any = _UNSET,
        full_name: Any = _UNSET,
        email: Any = _UNSET,
        join_date: Any = _UNSET,
        actor: AuditContext,
    ) -> dict[str, Any]:
        incoming = {
            "member_reference": member_reference,
            "full_name": full_name,
            "email": email,
            "join_date": join_date,
        }
        fields = {k: v for k, v in incoming.items() if v is not _UNSET}
        if not fields:
            raise DomainError("no_changes", "No fields to update.")
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            row = cur.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"member {member_id} not found")
            before = dict(row)
            changed = {k: v for k, v in fields.items() if v != before[k]}
            if changed:
                assignments = ", ".join(f"{k} = ?" for k in changed)
                try:
                    cur.execute(
                        f"UPDATE members SET {assignments}, updated_at = ? WHERE id = ?",
                        (*changed.values(), now, member_id),
                    )
                except sqlite3.IntegrityError as exc:
                    if "member_reference" in str(exc):
                        raise DomainError(
                            "reference_taken", "That member reference is already in use."
                        ) from exc
                    raise
                write_audit_row(
                    cur,
                    actor,
                    event_type="member.updated",
                    entity_type="member",
                    entity_id=member_id,
                    summary=f"Member {member_id} updated: {', '.join(sorted(changed))}",
                    detail={
                        "before": {k: before[k] for k in changed},
                        "after": dict(changed),
                    },
                )
        return self._require(member_id)

    # --- effective-dated status (US-202) ---------------------------------------

    async def set_status(
        self,
        member_id: int,
        status: str,
        *,
        effective_from: str | None = None,
        note: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        if status not in ("active", "inactive"):
            raise DomainError("bad_status", "status must be 'active' or 'inactive'.")
        eff = _iso_date(effective_from)
        async with self._db._write() as cur:
            new_row, prev = self._replace_open_period(
                cur,
                table="member_status_periods",
                open_index="idx_msp_one_open",
                member_id=member_id,
                value_col="status",
                new_value=status,
                effective_from=eff,
                extra_col="note",
                extra_val=note,
                created_by=actor.actor_user_id,
                unchanged_code="status_unchanged",
                unchanged_msg=f"Member is already {status}.",
            )
            write_audit_row(
                cur,
                actor,
                event_type="member.status_changed",
                entity_type="member",
                entity_id=member_id,
                summary=f"Member {member_id} status -> {status} (from {eff})",
                detail={"from": prev, "to": status, "effective_from": eff},
            )
        return new_row

    def status_history(self, member_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM member_status_periods WHERE member_id = ? ORDER BY effective_from, id",
            (member_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def status_map(self, on_date: str | None = None) -> dict[int, str]:
        """member_id -> status for every member with a period covering on_date."""
        d = on_date or clock.today_oslo().isoformat()
        rows = self._db.connection.execute(
            "SELECT member_id, status FROM member_status_periods "
            "WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)",
            (d, d),
        ).fetchall()
        return {int(r["member_id"]): r["status"] for r in rows}

    def current_status(self, member_id: int, on_date: str | None = None) -> str | None:
        return self.status_map(on_date).get(member_id)

    def active_member_ids(self, on_date: str | None = None) -> set[int]:
        return {mid for mid, status in self.status_map(on_date).items() if status == "active"}

    # --- settlement participation (US-203) -----------------------------------

    async def set_participation(
        self,
        member_id: int,
        participates: bool,
        *,
        effective_from: str | None = None,
        reason: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        # NOTE: this records only the *current* wish. The 1B settlement engine
        # must snapshot settlement_participation at post time ("frozen on
        # settlement posting", US-203) so later edits never move a posted split.
        eff = _iso_date(effective_from)
        async with self._db._write() as cur:
            new_row, prev = self._replace_open_period(
                cur,
                table="settlement_participation",
                open_index="idx_sp_one_open",
                member_id=member_id,
                value_col="participates",
                new_value=1 if participates else 0,
                effective_from=eff,
                extra_col="reason",
                extra_val=reason,
                created_by=actor.actor_user_id,
                unchanged_code="participation_unchanged",
                unchanged_msg=f"Participation is already {'included' if participates else 'excluded'}.",
            )
            write_audit_row(
                cur,
                actor,
                event_type="member.participation_changed",
                entity_type="member",
                entity_id=member_id,
                summary=f"Member {member_id} participation -> {participates} (from {eff})",
                detail={
                    "from": None if prev is None else bool(prev),
                    "to": bool(participates),
                    "effective_from": eff,
                },
            )
        return new_row

    def participation_history(self, member_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM settlement_participation WHERE member_id = ? "
            "ORDER BY effective_from, id",
            (member_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def explicit_participation_map(self, on_date: str | None = None) -> dict[int, bool]:
        """member_id -> explicit participates flag, for rows covering on_date."""
        d = on_date or clock.today_oslo().isoformat()
        rows = self._db.connection.execute(
            "SELECT member_id, participates FROM settlement_participation "
            "WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)",
            (d, d),
        ).fetchall()
        return {int(r["member_id"]): bool(r["participates"]) for r in rows}

    def effective_participation(self, member_id: int, on_date: str | None = None) -> bool | None:
        """True/False if the member is active (explicit row wins, else default
        True); None if the member is not active on that date."""
        d = on_date or clock.today_oslo().isoformat()
        explicit = self.explicit_participation_map(d)
        if member_id in explicit:
            return explicit[member_id]
        return True if member_id in self.active_member_ids(d) else None

    def suggested_participants(self, on_date: str | None = None) -> list[dict[str, Any]]:
        """Active members with their effective equal-cost participation. An
        explicit settlement_participation row wins; otherwise an active member
        defaults to participating. Inactive members are never suggested."""
        d = on_date or clock.today_oslo().isoformat()
        active = self.active_member_ids(d)
        explicit = self.explicit_participation_map(d)
        out: list[dict[str, Any]] = []
        for m in self.list():
            if m["id"] not in active:
                continue
            if m["id"] in explicit:
                participates, source = explicit[m["id"]], "explicit"
            else:
                participates, source = True, "default"
            out.append(
                {
                    "member_id": m["id"],
                    "member_reference": m["member_reference"],
                    "full_name": m["full_name"],
                    "participates": participates,
                    "source": source,
                }
            )
        return out

    def consumption_cost_recipients(self, on_date: str | None = None) -> set[int]:
        """Everyone active receives consumption-based (kWh) costs regardless of
        the equal-cost participation flag (US-203: "excluded users can still
        receive consumption costs"; US-607). The 1B settlement engine reads this
        for consumption allocation and `suggested_participants` for equal-cost."""
        return self.active_member_ids(on_date)

    # --- departure (US-204) ------------------------------------------------

    def departure_check(
        self, member_id: int, *, effective_date: str | None = None
    ) -> dict[str, Any]:
        """Everything an admin needs before processing a departure: the open
        charger assignments that would be closed, any month with the member's
        consumption not yet in a posted settlement (blocks a refund), and the
        current balance that a refund would pay back. Pure read."""
        from ladelaug_avregning.domain.ledger import LedgerRepo

        self._require(member_id)
        eff = _iso_date(effective_date)
        conn = self._db.connection
        open_assignments = [
            {
                "charger_id": int(r["charger_id"]),
                "charger_name": r["name"],
                "effective_from": r["effective_from"],
            }
            for r in conn.execute(
                "SELECT a.charger_id, a.effective_from, c.name FROM charger_assignments a "
                "JOIN chargers c ON c.id = a.charger_id "
                "WHERE a.member_id = ? AND a.effective_to IS NULL "
                "ORDER BY c.name, a.charger_id",
                (member_id,),
            ).fetchall()
        ]
        unsettled_months = [
            r["period_month"]
            for r in conn.execute(
                "SELECT DISTINCT period_month FROM charging_sessions "
                "WHERE member_id = ? AND period_month <= ? "
                "AND period_month NOT IN (SELECT period_month FROM settlements WHERE status = 'posted') "
                "ORDER BY period_month",
                (member_id, eff[:7]),
            ).fetchall()
        ]
        balance_ore = LedgerRepo(self._db).balance_ore(member_id)
        from ladelaug_avregning.money import ore_to_nok

        return {
            "member_id": member_id,
            "effective_date": eff,
            "current_status": self.current_status(member_id),
            "open_assignments": open_assignments,
            "unsettled_months": unsettled_months,
            "balance_ore": balance_ore,
            "balance_nok": str(ore_to_nok(balance_ore)),
            "would_refund_ore": max(balance_ore, 0),
        }

    async def process_departure(
        self,
        member_id: int,
        *,
        effective_date: str | None = None,
        refund: bool = False,
        refund_reference: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        """End the membership (US-204): set the status inactive from
        ``effective_date``, close every open charger assignment on that date
        (re-resolving the affected non-posted months), and — if ``refund`` and
        nothing is unsettled — pay the whole positive balance back. Each step
        writes its own audit row; one extra ``member.departed`` row summarises
        the lot. Nothing is deleted."""
        from ladelaug_avregning.audit import record_audit
        from ladelaug_avregning.domain.chargers import ChargerRepo
        from ladelaug_avregning.domain.charging import ChargingRepo
        from ladelaug_avregning.domain.ledger import LedgerRepo
        from ladelaug_avregning.money import ore_to_nok

        check = self.departure_check(member_id, effective_date=effective_date)
        eff = check["effective_date"]
        if refund and check["unsettled_months"]:
            raise DomainError(
                "unsettled_consumption",
                f"{', '.join(check['unsettled_months'])} still has consumption outside a posted "
                "settlement — settle or correct those months before refunding.",
            )

        status_changed = False
        if check["current_status"] != "inactive":
            await self.set_status(
                member_id, "inactive", effective_from=eff, note="Utmelding (US-204)", actor=actor
            )
            status_changed = True

        chargers = ChargerRepo(self._db)
        charging = ChargingRepo(self._db)
        closed: list[int] = []
        for a in check["open_assignments"]:
            await chargers.unassign(a["charger_id"], effective_to=eff, actor=actor)
            await charging.reresolve_after_assignment(
                a["charger_id"], since_month=eff[:7], actor=actor
            )
            closed.append(a["charger_id"])

        refund_txn_id: int | None = None
        ledger = LedgerRepo(self._db)
        balance_ore = ledger.balance_ore(member_id)
        if refund and balance_ore > 0:
            txn = await ledger.refund(
                member_id=member_id,
                amount=ore_to_nok(balance_ore),
                value_date=eff,
                reference=refund_reference or f"Utmelding {eff}",
                actor=actor,
            )
            refund_txn_id = int(txn["id"])

        await record_audit(
            self._db,
            actor,
            event_type="member.departed",
            entity_type="member",
            entity_id=member_id,
            summary=(
                f"Member {member_id} departed {eff}: {len(closed)} assignment(s) closed, "
                f"refund {'#' + str(refund_txn_id) if refund_txn_id else 'none'}"
            ),
            detail={
                "effective_date": eff,
                "status_changed": status_changed,
                "assignments_closed": closed,
                "refund_txn_id": refund_txn_id,
                "refunded_ore": balance_ore if refund_txn_id else 0,
                "unsettled_months": check["unsettled_months"],
            },
        )
        return {
            **check,
            "status_changed": status_changed,
            "assignments_closed": closed,
            "refund_txn_id": refund_txn_id,
            "refunded_ore": balance_ore if refund_txn_id else 0,
        }

    # --- internals -----------------------------------------------------------

    def _require(self, member_id: int) -> dict[str, Any]:
        row = self.get(member_id)
        if row is None:
            raise NotFoundError(f"member {member_id} not found")
        return row

    def _replace_open_period(
        self,
        cur: sqlite3.Cursor,
        *,
        table: str,
        open_index: str,
        member_id: int,
        value_col: str,
        new_value: Any,
        effective_from: str,
        extra_col: str,
        extra_val: str | None,
        created_by: int | None,
        unchanged_code: str,
        unchanged_msg: str,
    ) -> tuple[dict[str, Any], Any]:
        """Close the member's open row (if any) at `effective_from` and insert a
        new open one. Returns (new_row, previous_value). The caller writes the
        tailored audit row on the same cursor."""
        if cur.execute("SELECT 1 FROM members WHERE id = ?", (member_id,)).fetchone() is None:
            raise NotFoundError(f"member {member_id} not found")

        open_row = cur.execute(
            f"SELECT * FROM {table} WHERE member_id = ? AND effective_to IS NULL",
            (member_id,),
        ).fetchone()
        prev_value = None
        if open_row is not None:
            open_row = dict(open_row)
            prev_value = open_row[value_col]
            if prev_value == new_value:
                raise DomainError(unchanged_code, unchanged_msg)
            if effective_from < open_row["effective_from"]:
                raise DomainError(
                    "backdated",
                    f"effective_from {effective_from} is before the current period start "
                    f"{open_row['effective_from']}.",
                )
            cur.execute(
                f"UPDATE {table} SET effective_to = ? WHERE id = ?",
                (effective_from, open_row["id"]),
            )

        now = clock.now_utc().isoformat()
        try:
            cur.execute(
                f"INSERT INTO {table} "
                f"(member_id, {value_col}, effective_from, effective_to, {extra_col}, "
                f" created_at, created_by_user_id) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                (member_id, new_value, effective_from, extra_val, now, created_by),
            )
        except sqlite3.IntegrityError as exc:
            if open_index in str(exc):
                raise DomainError(
                    "period_conflict", "A concurrent change won the race; retry."
                ) from exc
            raise
        new_row = dict(
            cur.execute(f"SELECT * FROM {table} WHERE id = ?", (cur.lastrowid,)).fetchone()
        )
        return new_row, prev_value
