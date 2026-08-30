"""Async adapter for the Zaptec Public API (https://api.zaptec.com).

Endpoints used (confirmed with ``scripts/probe_zaptec.py`` — see
``spec/release-1b-plan.md`` § Probe findings):

* ``POST /oauth/token``      — OAuth2 password grant, form-encoded. Returns
  ``{"access_token", "token_type": "Bearer", "expires_in"}``.
* ``GET  /api/installation`` — paginated ``{"Pages", "Data": [{"Id", "Name", ...}]}``.
* ``GET  /api/chargers``     — paginated; each item has ``Id`` (device GUID),
  ``Name``, ``DeviceId``, ``SerialNo``, ``InstallationId``, ``CircuitId``,
  ``DeviceType``, ``IsOnline``, ``Active``/``Deleted``.
* ``GET  /api/chargehistory`` — archived charging sessions, paginated. With
  ``DetailLevel=1`` each item carries ``EnergyDetails`` — the 15-minute
  ``[{"Timestamp", "Energy"}]`` breakdown (US-404).

The adapter keeps the bearer token in memory, refreshes it just before expiry,
and re-authenticates once on a 401. Transport errors, 429 and 5xx are retried
with exponential backoff (``tenacity``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Self

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ladelaug_avregning.config import ZaptecConfig


class ZaptecError(RuntimeError):
    """Any failure talking to Zaptec."""


class ZaptecAuthError(ZaptecError):
    """Authentication failed (bad credentials or revoked token)."""


class _Retryable(ZaptecError):
    """Internal: a transient failure worth retrying."""


@dataclass(slots=True)
class ZaptecCharger:
    zaptec_id: str
    name: str
    serial_no: str | None
    device_id: str | None
    installation_id: str | None
    circuit_id: str | None
    device_type: str | None
    is_active: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def parse(cls, item: dict[str, Any]) -> ZaptecCharger:
        deleted = bool(item.get("Deleted") or item.get("IsDeleted"))
        active = item.get("Active")
        is_active = (bool(active) if active is not None else True) and not deleted
        return cls(
            zaptec_id=str(item["Id"]),
            name=str(item.get("Name") or item.get("SerialNo") or item["Id"]),
            serial_no=_str_or_none(item.get("SerialNo")),
            device_id=_str_or_none(item.get("DeviceId")),
            installation_id=_str_or_none(item.get("InstallationId")),
            circuit_id=_str_or_none(item.get("CircuitId")),
            device_type=_str_or_none(item.get("DeviceType") or item.get("DeviceTypeName")),
            is_active=is_active,
            raw=item,
        )


@dataclass(slots=True)
class ZaptecIntervalPoint:
    timestamp: str  # ISO-8601 UTC
    energy_kwh: Decimal


@dataclass(slots=True)
class ZaptecSession:
    session_id: str
    charger_zaptec_id: str
    device_id: str | None
    started_at: str  # ISO-8601 UTC
    ended_at: str | None
    energy_kwh: Decimal
    user_id: str | None
    user_full_name: str | None
    energy_details: list[ZaptecIntervalPoint]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def parse(cls, item: dict[str, Any]) -> ZaptecSession:
        details = [
            ZaptecIntervalPoint(
                timestamp=_iso_utc(str(p["Timestamp"])),
                energy_kwh=_dec(p.get("Energy")),
            )
            for p in (item.get("EnergyDetails") or [])
            if p.get("Timestamp") is not None
        ]
        return cls(
            session_id=str(item["Id"]),
            charger_zaptec_id=str(item.get("ChargerId") or item.get("DeviceId") or ""),
            device_id=_str_or_none(item.get("DeviceId")),
            started_at=_iso_utc(str(item["StartDateTime"])),
            ended_at=_iso_utc(str(item["EndDateTime"])) if item.get("EndDateTime") else None,
            energy_kwh=_dec(item.get("Energy")),
            user_id=_str_or_none(item.get("UserId")),
            user_full_name=_str_or_none(item.get("UserFullName")),
            energy_details=details,
            raw=item,
        )


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal(0)
    return Decimal(str(v))


def _iso_utc(raw: str) -> str:
    """Normalise a Zaptec timestamp to ``...+00:00``. Zaptec returns naive
    UTC (``2026-07-01T12:34:56`` or with a ``Z``); anything already carrying an
    offset is respected and converted to UTC."""
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ZaptecError(f"unparseable Zaptec timestamp: {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


class ZaptecClient:
    def __init__(self, config: ZaptecConfig, *, http: httpx.AsyncClient | None = None) -> None:
        self._cfg = config
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=config.request_timeout_seconds)
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # --- auth ------------------------------------------------------------

    async def authenticate(self) -> None:
        if not (self._cfg.username and self._cfg.password):
            raise ZaptecAuthError("Zaptec username / password not configured")
        try:
            resp = await self._http.post(
                self._cfg.token_url,
                data={
                    "grant_type": "password",
                    "username": self._cfg.username,
                    "password": self._cfg.password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise ZaptecError(f"Zaptec token request failed: {exc}") from exc
        if resp.status_code in (400, 401, 403):
            raise ZaptecAuthError(f"Zaptec authentication rejected ({resp.status_code})")
        if resp.status_code >= 500:
            raise ZaptecError(f"Zaptec token endpoint error {resp.status_code}")
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise ZaptecAuthError("Zaptec token response had no access_token")
        self._token = str(token)
        ttl = int(body.get("expires_in", 3600))
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=max(ttl - 60, 60))

    async def _ensure_token(self) -> str:
        if self._token is None or (
            self._token_expires_at is not None and datetime.now(UTC) >= self._token_expires_at
        ):
            await self.authenticate()
        assert self._token is not None
        return self._token

    # --- HTTP ----------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{self._cfg.base_url}{path}"

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._cfg.max_retries),
            wait=wait_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception_type((_Retryable, httpx.TransportError)),
        )
        async def _attempt() -> Any:
            token = await self._ensure_token()
            try:
                resp = await self._http.get(
                    url, params=params, headers={"Authorization": f"Bearer {token}"}
                )
            except httpx.TransportError:
                raise
            except httpx.HTTPError as exc:  # pragma: no cover - defensive
                raise ZaptecError(f"Zaptec request failed: {exc}") from exc
            if resp.status_code == 401:
                self._token = None  # force re-auth on the retry
                raise _Retryable("Zaptec returned 401")
            if resp.status_code == 429 or resp.status_code >= 500:
                raise _Retryable(f"Zaptec transient {resp.status_code}")
            if resp.status_code >= 400:
                raise ZaptecError(f"Zaptec {resp.status_code} for {path}: {resp.text[:200]}")
            return resp.json()

        return await _attempt()

    async def _iter_pages(self, path: str, params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        page = 0
        while True:
            body = await self._get(
                path, {**params, "PageIndex": page, "PageSize": self._cfg.page_size}
            )
            if isinstance(body, list):
                for item in body:
                    yield item
                return
            data = body.get("Data") or body.get("data") or []
            for item in data:
                yield item
            pages = int(body.get("Pages") or body.get("pages") or 1)
            page += 1
            if page >= pages or not data:
                return

    # --- resources ---------------------------------------------------

    async def list_installations(self) -> list[dict[str, Any]]:
        return [item async for item in self._iter_pages("/api/installation", {})]

    async def list_chargers(self, installation_id: str | None = None) -> list[ZaptecCharger]:
        params: dict[str, Any] = {}
        if installation_id:
            params["InstallationId"] = installation_id
        return [
            ZaptecCharger.parse(item) async for item in self._iter_pages("/api/chargers", params)
        ]

    async def iter_sessions(
        self,
        *,
        date_from: str,
        date_to: str,
        installation_id: str | None = None,
        detail_level: int = 1,
    ) -> AsyncIterator[ZaptecSession]:
        params: dict[str, Any] = {
            "From": date_from,
            "To": date_to,
            "DetailLevel": detail_level,
        }
        if installation_id:
            params["InstallationId"] = installation_id
        async for item in self._iter_pages("/api/chargehistory", params):
            yield ZaptecSession.parse(item)
