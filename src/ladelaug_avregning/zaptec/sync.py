"""Drives :class:`ZaptecClient` to mirror Zaptec state into the local DB.

``sync_chargers`` (US-301) upserts the installation row and every charger.
``sync_sessions`` (P4) imports archived charging sessions and their 15-minute
interval data. Each call writes one ``sync_runs`` row (US-403 / US-1104).
"""

from __future__ import annotations

import json
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.zaptec.client import ZaptecClient


def require_enabled(config: AppConfig) -> None:
    if not config.zaptec.enabled:
        raise DomainError(
            "zaptec_disabled",
            "Zaptec integration is disabled (set zaptec.enabled in config.yaml).",
            status=503,
        )


class ZaptecSync:
    def __init__(
        self, db: Database, config: AppConfig, *, client: ZaptecClient | None = None
    ) -> None:
        self._db = db
        self._config = config
        self._client = client

    def _new_client(self) -> ZaptecClient:
        return self._client or ZaptecClient(self._config.zaptec)

    async def sync_chargers(self, *, actor: AuditContext) -> dict[str, Any]:
        require_enabled(self._config)
        started = clock.now_utc().isoformat()
        chargers_repo = ChargerRepo(self._db)
        runs = SyncRunRepo(self._db)
        client = self._new_client()
        seen = created = updated = 0
        try:
            installations = await client.list_installations()
            await self._upsert_installations(installations)
            target = self._config.zaptec.installation_id or None
            devices = await client.list_chargers(target)
            for dev in devices:
                seen += 1
                _, was_created = await chargers_repo.upsert_from_zaptec(
                    zaptec_id=dev.zaptec_id,
                    name=dev.name,
                    serial_no=dev.serial_no,
                    installation_zaptec_id=dev.installation_id,
                    circuit_zaptec_id=dev.circuit_id,
                    device_type=dev.device_type,
                    is_active=dev.is_active,
                    raw=dev.raw,
                    actor=actor,
                )
                created += int(was_created)
                updated += int(not was_created)
        except Exception as exc:
            await runs.record(
                kind="chargers",
                status="error",
                started_at=started,
                items_seen=seen,
                items_imported=created + updated,
                error=f"{type(exc).__name__}: {exc}",
                created_by_user_id=actor.actor_user_id,
            )
            raise
        finally:
            if self._client is None:
                await client.aclose()

        await runs.record(
            kind="chargers",
            status="ok",
            started_at=started,
            items_seen=seen,
            items_imported=created + updated,
            created_by_user_id=actor.actor_user_id,
        )
        return {
            "installations": len(installations),
            "chargers_seen": seen,
            "chargers_created": created,
            "chargers_updated": updated,
        }

    async def _upsert_installations(self, installations: list[dict[str, Any]]) -> None:
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            for inst in installations:
                zid = str(inst.get("Id") or "")
                if not zid:
                    continue
                payload = json.dumps(inst, sort_keys=True, default=str)
                existing = cur.execute(
                    "SELECT id FROM zaptec_installations WHERE zaptec_id = ?", (zid,)
                ).fetchone()
                if existing is None:
                    cur.execute(
                        "INSERT INTO zaptec_installations "
                        "(zaptec_id, name, raw_json, first_connected_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (zid, inst.get("Name"), payload, now, now),
                    )
                else:
                    cur.execute(
                        "UPDATE zaptec_installations SET name = ?, raw_json = ?, updated_at = ? "
                        "WHERE id = ?",
                        (inst.get("Name"), payload, now, existing["id"]),
                    )
