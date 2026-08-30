"""Trailing-mean forecast engine (Epic 8, US-801..804).

The forecast is a **pure read-model** (decision C8): :class:`ForecastRepo`
computes everything on demand from posted settlements + the ledger. The only
persisted state is the ``forecast_settings`` singleton row (admin-tunable, C7).

Per member (decisions C1..C5):

* ``forecast_kwh`` — mean of the member's ``settlement_members.consumption_kwh``
  across the ``lookback_settlements`` most recent posted settlements the member
  appears in. Fewer postings than the lookback → ``available: false``.
* ``rate_ore_per_kwh`` — ``forecast_settings.rate_override_ore_per_kwh`` when the
  admin has set one, else the mean of ``sum(consumption line øre) / grid_kwh``
  over the last ``lookback_settlements`` posted settlements with
  ``grid_kwh > 0``. No positive ``grid_kwh`` anywhere and no override →
  ``available: false``.
* ``equal_share_ore`` — mean of ``sum(equal line øre) / equal-participant count``
  over the same window (settlements with no equal participants are skipped).
  Only added to a member's cost when their *current* effective participation is
  true.
* ``forecast_monthly_cost_ore`` = ``round(forecast_kwh × rate)`` (the single
  ``Decimal`` boundary, ``ROUND_HALF_EVEN``) ``+ equal_share_ore``.
* ``recommended_minimum_ore`` = ``forecast_monthly_cost_ore × buffer_months``.
* ``low_balance`` when ``balance_ore < recommended_minimum_ore``; severity
  ``critical`` when ``balance_ore < forecast_monthly_cost_ore``, else ``low``.

All arithmetic is in integer øre.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError

_SETTING_FIELDS = (
    "rate_override_ore_per_kwh",
    "buffer_months",
    "notify_cooldown_days",
    "lookback_settlements",
)


def _round_ore(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


class ForecastRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- settings (C7) -------------------------------------------------

    def settings(self) -> dict[str, Any]:
        row = self._db.connection.execute("SELECT * FROM forecast_settings WHERE id = 1").fetchone()
        if row is None:  # pragma: no cover - seeded by migration 0007
            raise RuntimeError("forecast_settings singleton row is missing")
        return dict(row)

    async def update_settings(self, *, actor: AuditContext, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - set(_SETTING_FIELDS)
        if unknown:
            raise DomainError("unknown_field", f"unknown forecast setting(s): {sorted(unknown)}")
        if not fields:
            raise DomainError("no_changes", "No forecast settings to update.")
        clean = {k: _validate_setting(k, v) for k, v in fields.items()}

        before_row = self.settings()
        changed = {k: v for k, v in clean.items() if v != before_row[k]}
        if not changed:
            return before_row

        now = clock.now_utc().isoformat()
        assignments = ", ".join(f"{k} = ?" for k in changed)
        async with self._db._write() as cur:
            cur.execute(
                f"UPDATE forecast_settings SET {assignments}, updated_at = ?, "
                "updated_by_user_id = ? WHERE id = 1",
                (*changed.values(), now, actor.actor_user_id),
            )
            write_audit_row(
                cur,
                actor,
                event_type="forecast.settings_updated",
                entity_type="forecast_settings",
                entity_id=1,
                summary=f"Forecast settings updated: {', '.join(sorted(changed))}",
                detail={
                    "before": {k: before_row[k] for k in changed},
                    "after": dict(changed),
                },
            )
        return self.settings()

    # --- historical statistics (C2, C3) -----------------------------

    def history_stats(self) -> dict[str, Any]:
        lookback = int(self.settings()["lookback_settlements"])
        rows = self._db.connection.execute(
            "SELECT id, period_month, grid_kwh FROM settlements "
            "WHERE status = 'posted' ORDER BY period_month DESC LIMIT ?",
            (lookback,),
        ).fetchall()

        per_settlement: list[dict[str, Any]] = []
        rate_samples: list[Decimal] = []
        equal_share_samples: list[int] = []
        for s in rows:
            sid = int(s["id"])
            grid_kwh = Decimal(s["grid_kwh"]) if s["grid_kwh"] not in (None, "") else Decimal(0)
            consumption_ore = self._line_total(sid, "consumption")
            equal_ore = self._line_total(sid, "equal")
            equal_participants = int(
                self._db.connection.execute(
                    "SELECT COUNT(*) FROM settlement_members "
                    "WHERE settlement_id = ? AND participates_equal = 1",
                    (sid,),
                ).fetchone()[0]
            )

            rate: Decimal | None = None
            if grid_kwh > 0:
                rate = Decimal(consumption_ore) / grid_kwh
                rate_samples.append(rate)

            equal_share: int | None = None
            if equal_participants > 0:
                equal_share = _round_ore(Decimal(equal_ore) / equal_participants)
                equal_share_samples.append(equal_share)

            per_settlement.append(
                {
                    "settlement_id": sid,
                    "period_month": s["period_month"],
                    "grid_kwh": str(grid_kwh),
                    "consumption_lines_ore": consumption_ore,
                    "equal_lines_ore": equal_ore,
                    "equal_participants": equal_participants,
                    "rate_ore_per_kwh": None if rate is None else str(rate),
                    "equal_share_ore": equal_share,
                }
            )

        mean_rate = sum(rate_samples, Decimal(0)) / len(rate_samples) if rate_samples else None
        mean_equal_share = (
            _round_ore(Decimal(sum(equal_share_samples)) / len(equal_share_samples))
            if equal_share_samples
            else 0
        )
        return {
            "lookback_settlements": lookback,
            "posted_settlements_considered": len(rows),
            "per_settlement": per_settlement,
            "rate_ore_per_kwh": mean_rate,
            "rate_settlements": len(rate_samples),
            "equal_share_ore": mean_equal_share,
            "equal_settlements": len(equal_share_samples),
        }

    # --- per-member forecast (C1..C5) -----------------------------

    def member_forecast(self, member_id: int) -> dict[str, Any]:
        return self._compute(member_id, self.settings(), self.history_stats())

    def all_member_forecasts(self) -> list[dict[str, Any]]:
        settings = self.settings()
        stats = self.history_stats()
        return [self._compute(int(m["id"]), settings, stats) for m in MemberRepo(self._db).list()]

    # --- internals ----------------------------------------------------

    def _compute(
        self, member_id: int, settings: dict[str, Any], stats: dict[str, Any]
    ) -> dict[str, Any]:
        balance_ore = LedgerRepo(self._db).balance_ore(member_id)
        lookback = int(settings["lookback_settlements"])
        override = settings["rate_override_ore_per_kwh"]

        postings = self._db.connection.execute(
            "SELECT sm.consumption_kwh FROM settlement_members sm "
            "JOIN settlements s ON s.id = sm.settlement_id "
            "WHERE sm.member_id = ? AND s.status = 'posted' "
            "ORDER BY s.period_month DESC LIMIT ?",
            (member_id, lookback),
        ).fetchall()

        if len(postings) < lookback:
            return _unavailable(member_id, balance_ore, "insufficient_history")
        if override is None and stats["rate_settlements"] == 0:
            return _unavailable(member_id, balance_ore, "no_grid_kwh")

        forecast_kwh = sum((Decimal(r["consumption_kwh"]) for r in postings), Decimal(0)) / len(
            postings
        )

        if override is not None:
            rate = Decimal(int(override))
            rate_source = "override"
        else:
            rate = stats["rate_ore_per_kwh"]
            rate_source = "derived"

        participates = MemberRepo(self._db).effective_participation(member_id) is True
        equal_share_ore = stats["equal_share_ore"] if participates else 0

        consumption_cost_ore = _round_ore(forecast_kwh * rate)
        forecast_monthly_cost_ore = consumption_cost_ore + equal_share_ore
        recommended_minimum_ore = _round_ore(
            Decimal(forecast_monthly_cost_ore) * Decimal(str(settings["buffer_months"]))
        )
        recommended_topup_ore = max(0, recommended_minimum_ore - balance_ore)
        low_balance = balance_ore < recommended_minimum_ore
        if not low_balance:
            severity = None
        elif balance_ore < forecast_monthly_cost_ore:
            severity = "critical"
        else:
            severity = "low"

        return {
            "member_id": member_id,
            "available": True,
            "forecast_kwh": str(forecast_kwh),
            "rate_ore_per_kwh": str(rate),
            "rate_source": rate_source,
            "equal_share_ore": int(equal_share_ore),
            "forecast_monthly_cost_ore": int(forecast_monthly_cost_ore),
            "recommended_minimum_ore": int(recommended_minimum_ore),
            "balance_ore": int(balance_ore),
            "recommended_topup_ore": int(recommended_topup_ore),
            "low_balance": low_balance,
            "severity": severity,
            "reason": None,
        }

    def _line_total(self, settlement_id: int, method: str) -> int:
        return int(
            self._db.connection.execute(
                "SELECT COALESCE(SUM(amount_ore), 0) FROM settlement_invoice_lines "
                "WHERE settlement_id = ? AND allocation_method = ?",
                (settlement_id, method),
            ).fetchone()[0]
        )


def _unavailable(member_id: int, balance_ore: int, reason: str) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "available": False,
        "forecast_kwh": "0",
        "rate_ore_per_kwh": "0",
        "rate_source": None,
        "equal_share_ore": 0,
        "forecast_monthly_cost_ore": 0,
        "recommended_minimum_ore": 0,
        "balance_ore": int(balance_ore),
        "recommended_topup_ore": 0,
        "low_balance": False,
        "severity": None,
        "reason": reason,
    }


def _validate_setting(key: str, value: Any) -> Any:
    if key == "rate_override_ore_per_kwh":
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise DomainError("bad_rate", "rate_override_ore_per_kwh must be a positive integer.")
        return value
    if key == "buffer_months":
        number = float(value)
        if number <= 0:
            raise DomainError("bad_buffer", "buffer_months must be greater than 0.")
        return number
    if key == "notify_cooldown_days":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise DomainError(
                "bad_cooldown", "notify_cooldown_days must be a non-negative integer."
            )
        return value
    if key == "lookback_settlements":
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise DomainError("bad_lookback", "lookback_settlements must be a positive integer.")
        return value
    raise DomainError("unknown_field", f"unknown forecast setting: {key}")  # pragma: no cover
