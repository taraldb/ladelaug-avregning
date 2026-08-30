"""Read/write access to the append-only ``audit_events`` table."""

from __future__ import annotations

import json
from typing import Any

from ladelaug_avregning.db import Database

_SORTABLE = {"occurred_at", "id", "event_type"}


class AuditRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_audit_event(
        self,
        *,
        occurred_at: str,
        actor_user_id: int | None,
        actor_label: str,
        event_type: str,
        entity_type: str,
        entity_id: str | None,
        summary: str,
        detail_json: str | None = None,
        ip: str | None = None,
    ) -> int:
        async with self._db._write() as cur:
            cur.execute(
                "INSERT INTO audit_events "
                "(occurred_at, actor_user_id, actor_label, event_type, entity_type, "
                " entity_id, summary, detail_json, ip) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    occurred_at,
                    actor_user_id,
                    actor_label,
                    event_type,
                    entity_type,
                    entity_id,
                    summary,
                    detail_json,
                    ip,
                ),
            )
            return int(cur.lastrowid or 0)

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        d = dict(row)
        raw = d.pop("detail_json", None)
        d["detail"] = json.loads(raw) if raw else None
        return d

    def list_audit_events(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "occurred_at",
        sort_dir: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        if sort_by not in _SORTABLE:
            raise ValueError(f"cannot sort audit events by {sort_by!r}")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

        where: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            where.append("event_type = ?")
            params.append(event_type)
        if entity_type is not None:
            where.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            where.append("entity_id = ?")
            params.append(entity_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        conn = self._db.connection
        total = conn.execute(f"SELECT COUNT(*) FROM audit_events{clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM audit_events{clause} "
            f"ORDER BY {sort_by} {direction}, id {direction} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [self._row_to_dict(r) for r in rows], int(total)

    def get_audit_event(self, event_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM audit_events WHERE id = ?", (event_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def count_by_type(self) -> dict[str, int]:
        rows = self._db.connection.execute(
            "SELECT event_type, COUNT(*) AS n FROM audit_events GROUP BY event_type"
        ).fetchall()
        return {r["event_type"]: int(r["n"]) for r in rows}
