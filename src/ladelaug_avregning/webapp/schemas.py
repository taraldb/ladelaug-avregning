"""Shared request/response models for the HTTP layer."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

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


# --- auth ------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


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

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        status: str | None = None,
        participates: bool | None = None,
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
