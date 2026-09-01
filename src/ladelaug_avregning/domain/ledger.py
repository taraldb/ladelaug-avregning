"""Append-only financial ledger (Epic 5).

A member's prepaid balance is ``SUM(amount_ore)`` over their
``ledger_transactions`` rows — never stored. Money moves only by inserting a new
row: a payment, an equal-and-opposite reversal of a mistaken payment, a manual
credit/debit adjustment, a refund paying the member back (US-505), or a
settlement charge / correction written by the settlement engine. Rows are
immutable (no repo update/delete + ``BEFORE UPDATE/DELETE`` triggers). Each
insert writes exactly one paired ``audit_events`` row in the same transaction
(US-1102).
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any, Literal

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import nok_to_ore, ore_to_nok

Direction = Literal["credit", "debit"]


def _ore_nok(ore: int) -> tuple[int, str]:
    """Signed øre plus its exact NOK string — both from one value, so they never
    drift (``ore_to_nok(ore) == Decimal(nok)``)."""
    return ore, str(ore_to_nok(ore))


class LedgerRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- reads -------------------------------------------------------------

    def get(self, txn_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM ledger_transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        return dict(row) if row else None

    def balance_ore(self, member_id: int) -> int:
        total = self._db.connection.execute(
            "SELECT COALESCE(SUM(amount_ore), 0) FROM ledger_transactions WHERE member_id = ?",
            (member_id,),
        ).fetchone()[0]
        return int(total)

    def balance(self, member_id: int) -> Decimal:
        return ore_to_nok(self.balance_ore(member_id))

    def list(
        self, member_id: int, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        conn = self._db.connection
        total = conn.execute(
            "SELECT COUNT(*) FROM ledger_transactions WHERE member_id = ?", (member_id,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM ledger_transactions WHERE member_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (member_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], int(total)

    def list_all(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        member_id: int | None = None,
        txn_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Newest-first ledger rows across every member, each joined to its
        member's name/reference. Optional ``member_id`` / ``txn_type`` filters."""
        conn = self._db.connection
        where: list[str] = []
        params: list[Any] = []
        if member_id is not None:
            where.append("lt.member_id = ?")
            params.append(member_id)
        if txn_type:
            where.append("lt.txn_type = ?")
            params.append(txn_type)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM ledger_transactions lt{clause}", params
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT lt.*, m.full_name AS member_name, m.member_reference AS member_reference "
            "FROM ledger_transactions lt JOIN members m ON m.id = lt.member_id"
            f"{clause} ORDER BY lt.id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], int(total)

    def balance_ore_map(self) -> dict[int, int]:
        """member_id -> balance in øre, for every member with ledger activity."""
        rows = self._db.connection.execute(
            "SELECT member_id, COALESCE(SUM(amount_ore), 0) AS bal "
            "FROM ledger_transactions GROUP BY member_id"
        ).fetchall()
        return {int(r["member_id"]): int(r["bal"]) for r in rows}

    def running_balance_by_month(self, member_id: int) -> list[tuple[str, int]]:
        """``(YYYY-MM, cumulative balance in øre at that month's end)`` for the
        member, ascending, one entry per month that has ledger activity.
        ``value_date`` is a ``YYYY-MM-DD`` string, so its first 7 chars key the
        local booking month. Callers forward-fill the gaps."""
        rows = self._db.connection.execute(
            "SELECT substr(value_date, 1, 7) AS ym, SUM(amount_ore) AS delta "
            "FROM ledger_transactions WHERE member_id = ? "
            "GROUP BY ym ORDER BY ym",
            (member_id,),
        ).fetchall()
        out: list[tuple[str, int]] = []
        running = 0
        for r in rows:
            running += int(r["delta"])
            out.append((str(r["ym"]), running))
        return out

    # --- mutations -------------------------------------------------------

    async def record_payment(
        self,
        *,
        member_id: int,
        amount: Decimal,
        value_date: str,
        reference: str | None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        if amount <= 0:
            raise DomainError("bad_amount", "payment amount must be positive")
        ore, nok = _ore_nok(nok_to_ore(amount))
        async with self._db._write() as cur:
            self._ensure_member(cur, member_id)
            txn_id = self._insert_txn(
                cur,
                member_id=member_id,
                txn_type="payment",
                amount_ore=ore,
                amount_nok=nok,
                value_date=value_date,
                reason=None,
                reference=reference,
                reverses_transaction_id=None,
                created_by=actor.actor_user_id,
            )
            write_audit_row(
                cur,
                actor,
                event_type="ledger.payment_recorded",
                entity_type="ledger_transaction",
                entity_id=txn_id,
                summary=f"Payment {nok} NOK recorded for member {member_id}",
                detail={
                    "member_id": member_id,
                    "amount_ore": ore,
                    "amount_nok": nok,
                    "value_date": value_date,
                    "reference": reference,
                },
            )
        return self._require(txn_id)

    async def reverse_payment(self, *, txn_id: int, actor: AuditContext) -> dict[str, Any]:
        async with self._db._write() as cur:
            row = cur.execute(
                "SELECT * FROM ledger_transactions WHERE id = ?", (txn_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"ledger transaction {txn_id} not found")
            original = dict(row)
            if original["txn_type"] != "payment":
                raise DomainError("not_a_payment", "only payments can be reversed")
            if (
                cur.execute(
                    "SELECT 1 FROM ledger_transactions WHERE reverses_transaction_id = ?", (txn_id,)
                ).fetchone()
                is not None
            ):
                raise DomainError("already_reversed", f"payment #{txn_id} is already reversed")

            member_id = int(original["member_id"])
            ore, nok = _ore_nok(-int(original["amount_ore"]))
            try:
                reversal_id = self._insert_txn(
                    cur,
                    member_id=member_id,
                    txn_type="payment_reversal",
                    amount_ore=ore,
                    amount_nok=nok,
                    value_date=clock.today_oslo().isoformat(),
                    reason=None,
                    reference=None,
                    reverses_transaction_id=txn_id,
                    created_by=actor.actor_user_id,
                )
            except sqlite3.IntegrityError as exc:
                if "idx_ledger_one_reversal" in str(exc):
                    raise DomainError(
                        "already_reversed", f"payment #{txn_id} is already reversed"
                    ) from exc
                raise
            write_audit_row(
                cur,
                actor,
                event_type="ledger.payment_reversed",
                entity_type="ledger_transaction",
                entity_id=reversal_id,
                summary=f"Payment #{txn_id} reversed for member {member_id}",
                detail={
                    "member_id": member_id,
                    "reverses_transaction_id": txn_id,
                    "amount_ore": ore,
                    "amount_nok": nok,
                },
            )
        return self._require(reversal_id)

    async def adjust(
        self,
        *,
        member_id: int,
        direction: Direction,
        amount: Decimal,
        reason: str,
        reference: str | None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        reason = (reason or "").strip()
        if not reason:
            raise DomainError("reason_required", "adjustments require a reason")
        if amount <= 0:
            raise DomainError("bad_amount", "adjustment amount must be positive")
        magnitude = nok_to_ore(amount)
        if direction == "credit":
            txn_type, (ore, nok) = "adjustment_credit", _ore_nok(magnitude)
        else:
            txn_type, (ore, nok) = "adjustment_debit", _ore_nok(-magnitude)
        async with self._db._write() as cur:
            self._ensure_member(cur, member_id)
            txn_id = self._insert_txn(
                cur,
                member_id=member_id,
                txn_type=txn_type,
                amount_ore=ore,
                amount_nok=nok,
                value_date=clock.today_oslo().isoformat(),
                reason=reason,
                reference=reference,
                reverses_transaction_id=None,
                created_by=actor.actor_user_id,
            )
            write_audit_row(
                cur,
                actor,
                event_type="ledger.adjusted",
                entity_type="ledger_transaction",
                entity_id=txn_id,
                summary=f"Adjustment ({direction}) {nok} NOK for member {member_id}: {reason}",
                detail={
                    "member_id": member_id,
                    "direction": direction,
                    "amount_ore": ore,
                    "amount_nok": nok,
                    "reason": reason,
                    "reference": reference,
                },
            )
        return self._require(txn_id)

    async def refund(
        self,
        *,
        member_id: int,
        amount: Decimal,
        value_date: str,
        reference: str | None,
        actor: AuditContext,
        allow_negative: bool = False,
    ) -> dict[str, Any]:
        """Pay a member back (US-505). Lowers the balance by ``amount``. Refused
        with ``refund_exceeds_balance`` when it would take the balance below zero
        unless ``allow_negative`` is set (the audited escape hatch for undoing an
        earlier over-charge). ``reference`` is an optional accounting reference."""
        if amount <= 0:
            raise DomainError("bad_amount", "refund amount must be positive")
        magnitude = nok_to_ore(amount)
        current = self.balance_ore(member_id)
        if not allow_negative and magnitude > current:
            raise DomainError(
                "refund_exceeds_balance",
                f"Refund {ore_to_nok(magnitude)} NOK exceeds the balance "
                f"{ore_to_nok(current)} NOK. Tick 'allow negative balance' to override.",
            )
        ore, nok = _ore_nok(-magnitude)
        async with self._db._write() as cur:
            self._ensure_member(cur, member_id)
            txn_id = self._insert_txn(
                cur,
                member_id=member_id,
                txn_type="refund",
                amount_ore=ore,
                amount_nok=nok,
                value_date=value_date,
                reason=None,
                reference=reference,
                reverses_transaction_id=None,
                created_by=actor.actor_user_id,
            )
            write_audit_row(
                cur,
                actor,
                event_type="ledger.refunded",
                entity_type="ledger_transaction",
                entity_id=txn_id,
                summary=f"Refund {nok} NOK for member {member_id}",
                detail={
                    "member_id": member_id,
                    "amount_ore": ore,
                    "amount_nok": nok,
                    "value_date": value_date,
                    "reference": reference,
                    "balance_before_ore": current,
                },
            )
        return self._require(txn_id)

    # --- internals ------------------------------------------------------

    def _require(self, txn_id: int) -> dict[str, Any]:
        row = self.get(txn_id)
        if row is None:
            raise NotFoundError(f"ledger transaction {txn_id} not found")
        return row

    @staticmethod
    def _ensure_member(cur: sqlite3.Cursor, member_id: int) -> None:
        if cur.execute("SELECT 1 FROM members WHERE id = ?", (member_id,)).fetchone() is None:
            raise NotFoundError(f"member {member_id} not found")

    @staticmethod
    def _insert_txn(
        cur: sqlite3.Cursor,
        *,
        member_id: int,
        txn_type: str,
        amount_ore: int,
        amount_nok: str,
        value_date: str,
        reason: str | None,
        reference: str | None,
        reverses_transaction_id: int | None,
        created_by: int | None,
    ) -> int:
        cur.execute(
            "INSERT INTO ledger_transactions "
            "(member_id, txn_type, amount_ore, amount_nok, currency, value_date, reason, "
            " reference, reverses_transaction_id, created_by_user_id, recorded_at) "
            "VALUES (?, ?, ?, ?, 'NOK', ?, ?, ?, ?, ?, ?)",
            (
                member_id,
                txn_type,
                amount_ore,
                amount_nok,
                value_date,
                reason,
                reference,
                reverses_transaction_id,
                created_by,
                clock.now_utc().isoformat(),
            ),
        )
        return int(cur.lastrowid or 0)
