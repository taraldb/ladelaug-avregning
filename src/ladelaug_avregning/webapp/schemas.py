"""Shared request/response models for the HTTP layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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
