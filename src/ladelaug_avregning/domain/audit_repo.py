"""Read/write access to the append-only ``audit_events`` table."""

from __future__ import annotations

import json
from typing import Any

from ladelaug_avregning.db import Database

_SORTABLE = {"occurred_at", "id", "event_type"}


class AuditRepo:
    """Read surface for the append-only ``audit_events`` table. The single
    writer of record is ``audit.write_audit_row`` / ``audit.record_audit`` — do
    not add an insert path here."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        d = dict(row)
        raw = d.pop("detail_json", None)
        d["detail"] = json.loads(raw) if raw else None
        return d

    def _filter_clause(
        self,
        *,
        event_type: str | None,
        entity_type: str | None,
        entity_id: str | None,
        actor: str | None,
        occurred_from: str | None,
        occurred_to: str | None,
    ) -> tuple[str, list[Any]]:
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
        if actor:
            where.append("actor_label LIKE ?")
            params.append(f"%{actor}%")
        if occurred_from:
            where.append("occurred_at >= ?")
            params.append(occurred_from)
        if occurred_to:
            where.append("occurred_at <= ?")
            params.append(occurred_to)
        return (f" WHERE {' AND '.join(where)}" if where else ""), params

    def list_audit_events(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
        occurred_from: str | None = None,
        occurred_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "occurred_at",
        sort_dir: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        if sort_by not in _SORTABLE:
            raise ValueError(f"cannot sort audit events by {sort_by!r}")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

        clause, params = self._filter_clause(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )

        conn = self._db.connection
        total = conn.execute(f"SELECT COUNT(*) FROM audit_events{clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM audit_events{clause} "
            f"ORDER BY {sort_by} {direction}, id {direction} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [self._row_to_dict(r) for r in rows], int(total)

    def rows_for_export(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
        occurred_from: str | None = None,
        occurred_to: str | None = None,
        cap: int = 10000,
    ) -> list[dict[str, Any]]:
        """Newest-first rows matching the same filters as ``list_audit_events``,
        for the admin CSV export. Capped so a huge log cannot exhaust memory."""
        clause, params = self._filter_clause(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
        rows = self._db.connection.execute(
            f"SELECT * FROM audit_events{clause} ORDER BY occurred_at DESC, id DESC LIMIT ?",
            [*params, cap],
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

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
