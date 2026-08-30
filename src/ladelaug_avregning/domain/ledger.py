"""Append-only financial ledger (Epic 5).

A member's prepaid balance is ``SUM(amount_ore)`` over their
``ledger_transactions`` rows — never stored. Money moves only by inserting a new
row: a payment, an equal-and-opposite reversal of a mistaken payment, or a manual
credit/debit adjustment. Rows are immutable (no repo update/delete + ``BEFORE
UPDATE/DELETE`` triggers). Each insert writes exactly one paired ``audit_events``
row in the same transaction (US-1102).
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

    def balance(self, member_id: int) -> Decimal:
        total = self._db.connection.execute(
            "SELECT COALESCE(SUM(amount_ore), 0) FROM ledger_transactions WHERE member_id = ?",
            (member_id,),
        ).fetchone()[0]
        return ore_to_nok(int(total))

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
