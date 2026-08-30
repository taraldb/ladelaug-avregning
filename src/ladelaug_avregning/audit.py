"""Audit-event write helpers.

Every mutating operation records exactly one audit event. ``AuditContext`` carries
the "who / from where" that the web layer resolves from the authenticated session;
the write helpers are the "what happened".

Two entry points:

* ``write_audit_row(cur, ...)`` — synchronous, runs on a cursor the caller already
  holds inside a ``Database._write()`` transaction. Use this from repositories so
  the mutation and its audit row commit together. ``asyncio.Lock`` is not
  reentrant, so a repo inside ``_write()`` must not call ``record_audit``.
* ``record_audit(db, ...)`` — async, opens its own ``_write()`` transaction. Use
  this for stand-alone events with no accompanying mutation (e.g. a failed login).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.db import Database

SYSTEM_ACTOR = "system"

_INSERT = (
    "INSERT INTO audit_events "
    "(occurred_at, actor_user_id, actor_label, event_type, entity_type, "
    " entity_id, summary, detail_json, ip) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(frozen=True)
class AuditContext:
    actor_user_id: int | None
    actor_label: str
    ip: str | None = None

    @classmethod
    def system(cls) -> AuditContext:
        return cls(actor_user_id=None, actor_label=SYSTEM_ACTOR, ip=None)


def write_audit_row(
    cur: sqlite3.Cursor,
    ctx: AuditContext,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | int | None,
    summary: str,
    detail: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> int:
    """Insert one audit row on an existing cursor. No locking, no commit."""
    cur.execute(
        _INSERT,
        (
            occurred_at or clock.now_utc().isoformat(),
            ctx.actor_user_id,
            ctx.actor_label,
            event_type,
            entity_type,
            None if entity_id is None else str(entity_id),
            summary,
            json.dumps(detail) if detail is not None else None,
            ctx.ip,
        ),
    )
    return int(cur.lastrowid or 0)


async def record_audit(
    db: Database,
    ctx: AuditContext,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | int | None,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> int:
    async with db._write() as cur:
        return write_audit_row(
            cur,
            ctx,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            detail=detail,
        )
