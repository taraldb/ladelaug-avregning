"""Shared request/response models for the HTTP layer."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from ladelaug_avregning.money import ore_to_nok, parse_nok

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _required(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be empty")
    return value


def _optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        raise ValueError("not a valid email address")
    return value


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("must be a YYYY-MM-DD date") from exc


def _positive_nok(value: Any) -> Decimal:
    try:
        amount = parse_nok(value)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("not a valid amount") from exc
    if amount <= 0:
        raise ValueError("amount must be positive")
    return amount


# --- auth ------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class EmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _required(v, "email").lower()


class TokenConsumeRequest(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _v_token(cls, v: str) -> str:
        return _required(v, "token")


class PasswordResetRequest(BaseModel):
    token: str
    password: str

    @field_validator("token")
    @classmethod
    def _v_token(cls, v: str) -> str:
        return _required(v, "token")

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("password must be at least 10 characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    member_id: int | None
    disabled: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> UserOut:
        return cls(
            id=row["id"],
            email=row["email"],
            role=row["role"],
            member_id=row["member_id"],
            disabled=bool(row["disabled"]),
        )


class UserCreateIn(BaseModel):
    """Admin-provisioned login. ``password`` may be omitted — the account is then
    activation-only (magic link / password reset)."""

    email: str
    password: str | None = None
    role: Literal["admin", "member"]
    member_id: int | None = None

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        v = _required(v, "email")
        if not _EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if len(v) < 10:
            raise ValueError("password must be at least 10 characters")
        return v

    @model_validator(mode="after")
    def _v_member_link(self) -> UserCreateIn:
        if self.role == "member" and self.member_id is None:
            raise ValueError("a member login requires member_id")
        if self.role == "admin" and self.member_id is not None:
            raise ValueError("an admin login must not set member_id")
        return self


class UserSetPasswordIn(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("password must be at least 10 characters")
        return v


# --- members (US-201) ----------------------------------------------------


class MemberIn(BaseModel):
    member_reference: str
    full_name: str
    email: str | None = None
    join_date: str

    @field_validator("member_reference")
    @classmethod
    def _v_ref(cls, v: str) -> str:
        return _required(v, "member_reference")

    @field_validator("full_name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return _required(v, "full_name")

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str | None) -> str | None:
        return _optional_email(v)

    @field_validator("join_date")
    @classmethod
    def _v_join_date(cls, v: str) -> str:
        return _iso_date(v)


class MemberPatch(BaseModel):
    member_reference: str | None = None
    full_name: str | None = None
    email: str | None = None
    join_date: str | None = None

    @field_validator("member_reference")
    @classmethod
    def _v_ref(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "member_reference")

    @field_validator("full_name")
    @classmethod
    def _v_name(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "full_name")

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str | None) -> str | None:
        return _optional_email(v)

    @field_validator("join_date")
    @classmethod
    def _v_join_date(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)

    @model_validator(mode="after")
    def _at_least_one(self) -> MemberPatch:
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self


class MemberOut(BaseModel):
    id: int
    member_reference: str
    full_name: str
    email: str | None
    join_date: str
    created_at: str
    updated_at: str
    status: str | None = None
    participates: bool | None = None
    balance_ore: int | None = None
    balance_nok: str | None = None

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        status: str | None = None,
        participates: bool | None = None,
        balance_ore: int | None = None,
    ) -> MemberOut:
        return cls(
            id=row["id"],
            member_reference=row["member_reference"],
            full_name=row["full_name"],
            email=row["email"],
            join_date=row["join_date"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=status,
            participates=participates,
            balance_ore=balance_ore,
            balance_nok=None if balance_ore is None else str(ore_to_nok(balance_ore)),
        )


# --- status (US-202) ---------------------------------------------------


class StatusChangeIn(BaseModel):
    status: Literal["active", "inactive"]
    effective_from: str | None = None
    note: str | None = None

    @field_validator("effective_from")
    @classmethod
    def _v_effective_from(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)


class DepartureIn(BaseModel):
    """Process a member departure (US-204). ``refund`` pays the whole remaining
    positive balance back, refused while any month is still unsettled."""

    effective_date: str
    refund: bool = False
    refund_reference: str | None = None

    @field_validator("effective_date")
    @classmethod
    def _v_effective_date(cls, v: str) -> str:
        return _iso_date(v)


class StatusPeriodOut(BaseModel):
    id: int
    status: str
    effective_from: str
    effective_to: str | None
    note: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StatusPeriodOut:
        return cls(
            id=row["id"],
            status=row["status"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            note=row["note"],
            created_at=row["created_at"],
        )


# --- settlement participation (US-203) --------------------------------


class ParticipationChangeIn(BaseModel):
    participates: bool
    effective_from: str | None = None
    reason: str | None = None

    @field_validator("effective_from")
    @classmethod
    def _v_effective_from(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)


class ParticipationPeriodOut(BaseModel):
    id: int
    participates: bool
    effective_from: str
    effective_to: str | None
    reason: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ParticipationPeriodOut:
        return cls(
            id=row["id"],
            participates=bool(row["participates"]),
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            reason=row["reason"],
            created_at=row["created_at"],
        )


class SuggestedParticipantOut(BaseModel):
    member_id: int
    member_reference: str
    full_name: str
    participates: bool
    source: str


# --- charging access (US-305) ----------------------------------------


class AccessActionIn(BaseModel):
    action: Literal["warned", "disabled", "restored"]
    reason: str | None = None
    note: str | None = None


class AccessEventOut(BaseModel):
    id: int
    member_id: int
    action: str
    reason: str | None
    note: str | None
    created_at: str
    created_by_user_id: int | None
    email_message_id: int | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AccessEventOut:
        return cls(
            id=row["id"],
            member_id=row["member_id"],
            action=row["action"],
            reason=row["reason"],
            note=row["note"],
            created_at=row["created_at"],
            created_by_user_id=row["created_by_user_id"],
            email_message_id=row["email_message_id"],
        )


# --- ledger (US-501..504) --------------------------------------------


class PaymentIn(BaseModel):
    amount: Decimal
    value_date: str | None = None
    reference: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal:
        return _positive_nok(v)

    @field_validator("value_date")
    @classmethod
    def _v_value_date(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)


class AdjustmentIn(BaseModel):
    direction: Literal["credit", "debit"]
    amount: Decimal
    reason: str
    reference: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal:
        return _positive_nok(v)

    @field_validator("reason")
    @classmethod
    def _v_reason(cls, v: str) -> str:
        return _required(v, "reason")


class RefundIn(BaseModel):
    """Pay a member back (US-505). ``reference`` is an optional accounting
    reference; ``allow_negative`` overrides the balance guard."""

    amount: Decimal
    value_date: str | None = None
    reference: str | None = None
    allow_negative: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal:
        return _positive_nok(v)

    @field_validator("value_date")
    @classmethod
    def _v_value_date(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)


class LedgerTxnOut(BaseModel):
    id: int
    member_id: int
    txn_type: str
    amount_ore: int
    amount_nok: str
    currency: str
    value_date: str
    reason: str | None
    reference: str | None
    reverses_transaction_id: int | None
    created_by_user_id: int | None
    recorded_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> LedgerTxnOut:
        return cls(
            **{
                k: row[k]
                for k in (
                    "id",
                    "member_id",
                    "txn_type",
                    "amount_ore",
                    "amount_nok",
                    "currency",
                    "value_date",
                    "reason",
                    "reference",
                    "reverses_transaction_id",
                    "created_by_user_id",
                    "recorded_at",
                )
            }
        )


class LedgerTxnRowOut(LedgerTxnOut):
    """A ledger row for the cross-member movements list — adds the owning
    member's name and reference from the join."""

    member_name: str
    member_reference: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> LedgerTxnRowOut:
        base = LedgerTxnOut.from_row(row)
        return cls(
            **base.model_dump(),
            member_name=row["member_name"],
            member_reference=row["member_reference"],
        )


class BalanceOut(BaseModel):
    member_id: int
    balance_nok: str
    balance_ore: int


# --- chargers (Epic 3) ----------------------------------------------


class ChargerIn(BaseModel):
    name: str
    serial_no: str | None = None
    zaptec_id: str | None = None
    device_type: str | None = None

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return _required(v, "name")


class ChargerPatch(BaseModel):
    name: str | None = None
    serial_no: str | None = None
    device_type: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "name")


class ChargerOut(BaseModel):
    id: int
    zaptec_id: str | None
    name: str
    serial_no: str | None
    device_type: str | None
    is_active: bool
    last_synced_at: str | None
    created_at: str
    updated_at: str
    assigned_member_id: int | None = None
    deletable: bool = False

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        assigned_member_id: int | None = None,
        deletable: bool = False,
    ) -> ChargerOut:
        return cls(
            id=row["id"],
            zaptec_id=row["zaptec_id"],
            name=row["name"],
            serial_no=row["serial_no"],
            device_type=row["device_type"],
            is_active=bool(row["is_active"]),
            last_synced_at=row["last_synced_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            assigned_member_id=assigned_member_id,
            deletable=deletable,
        )


class ChargerAssignIn(BaseModel):
    member_id: int
    effective_from: str | None = None
    note: str | None = None

    @field_validator("effective_from")
    @classmethod
    def _v_effective_from(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)


class ChargerUnassignIn(BaseModel):
    effective_to: str | None = None

    @field_validator("effective_to")
    @classmethod
    def _v_effective_to(cls, v: str | None) -> str | None:
        return None if v is None else _iso_date(v)


class SettlementDraftIn(BaseModel):
    period_month: str

    @field_validator("period_month")
    @classmethod
    def _v_month(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError("period_month must be YYYY-MM")
        return v


class SettlementInvoiceIn(BaseModel):
    invoice_kwh: str | None = None
    note: str | None = None

    @field_validator("invoice_kwh")
    @classmethod
    def _v_kwh(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            d = Decimal(str(v))
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("invoice_kwh must be a number") from exc
        if not d.is_finite() or d < 0:
            raise ValueError("invoice_kwh must be a non-negative number")
        return str(d)


class InvoiceLineIn(BaseModel):
    description: str
    allocation_method: Literal["equal", "consumption"]
    amount: Decimal
    category: str | None = None

    @field_validator("description")
    @classmethod
    def _v_desc(cls, v: str) -> str:
        return _required(v, "description")

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal:
        return _positive_nok(v)


class InvoiceLinePatch(BaseModel):
    """Partial edit of a draft settlement's invoice line — only the fields
    present in the body are applied."""

    description: str | None = None
    allocation_method: Literal["equal", "consumption"] | None = None
    amount: Decimal | None = None
    category: str | None = None

    @field_validator("description")
    @classmethod
    def _v_desc(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "description")

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal | None:
        return None if v is None else _positive_nok(v)

    @model_validator(mode="after")
    def _at_least_one(self) -> InvoiceLinePatch:
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self


class ChargerAssignmentOut(BaseModel):
    id: int
    charger_id: int
    member_id: int
    effective_from: str
    effective_to: str | None
    note: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ChargerAssignmentOut:
        return cls(
            id=row["id"],
            charger_id=row["charger_id"],
            member_id=row["member_id"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            note=row["note"],
            created_at=row["created_at"],
        )


# --- forecasting (Epic 8) ------------------------------------------


class ForecastSettingsIn(BaseModel):
    """Partial update of the ``forecast_settings`` singleton. Only the fields
    present in the request body are applied; an explicit
    ``rate_override_ore_per_kwh: null`` clears the override."""

    rate_override_ore_per_kwh: int | None = None
    buffer_months: float | None = None
    notify_cooldown_days: int | None = None
    lookback_settlements: int | None = None

    @field_validator("rate_override_ore_per_kwh")
    @classmethod
    def _v_rate(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("rate_override_ore_per_kwh must be a positive integer")
        return v

    @field_validator("buffer_months")
    @classmethod
    def _v_buffer(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("buffer_months must be greater than 0")
        return v

    @field_validator("notify_cooldown_days")
    @classmethod
    def _v_cooldown(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("notify_cooldown_days must be a non-negative integer")
        return v

    @field_validator("lookback_settlements")
    @classmethod
    def _v_lookback(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("lookback_settlements must be a positive integer")
        return v

    @model_validator(mode="after")
    def _at_least_one(self) -> ForecastSettingsIn:
        if not self.model_fields_set:
            raise ValueError("provide at least one forecast setting to update")
        return self

    def to_update_kwargs(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class ForecastSettingsOut(BaseModel):
    rate_override_ore_per_kwh: int | None
    buffer_months: float
    notify_cooldown_days: int
    lookback_settlements: int
    updated_at: str | None
    updated_by_user_id: int | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ForecastSettingsOut:
        return cls(
            rate_override_ore_per_kwh=row["rate_override_ore_per_kwh"],
            buffer_months=row["buffer_months"],
            notify_cooldown_days=row["notify_cooldown_days"],
            lookback_settlements=row["lookback_settlements"],
            updated_at=row["updated_at"],
            updated_by_user_id=row["updated_by_user_id"],
        )


class MemberForecastOut(BaseModel):
    member_id: int
    available: bool
    forecast_kwh: str
    rate_ore_per_kwh: str
    rate_source: str | None
    equal_share_ore: int
    forecast_monthly_cost_ore: int
    recommended_minimum_ore: int
    balance_ore: int
    recommended_topup_ore: int
    low_balance: bool
    severity: str | None
    reason: str | None = None

    @classmethod
    def from_forecast(cls, forecast: dict[str, Any]) -> MemberForecastOut:
        return cls(**forecast)


class MemberConsumptionOut(BaseModel):
    member_id: int
    month: str
    consumption_kwh: str
    session_count: int
