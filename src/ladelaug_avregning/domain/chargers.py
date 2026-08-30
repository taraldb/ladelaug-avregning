"""Chargers and their effective-dated member assignments (Epic 3).

A *charger* is a physical unit. It is normally mirrored from Zaptec
(``upsert_from_zaptec``, Release 1B phase 3) but an admin may also enter one by
hand. Each charger has an assignment timeline — half-open ``[effective_from,
effective_to)`` ranges, ``effective_to IS NULL`` = open, at most one open row per
charger (partial unique index ``idx_ca_one_open``). The monthly settlement
attributes a charging session's energy to whichever member holds the charger on
the session's start date; a session on a charger with no assignment that day is
*unassigned consumption* (US-304).

A member may hold several chargers at once (US-303) — there is no uniqueness on
``member_id``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, write_audit_row
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import DomainError, NotFoundError

_UNSET: Any = object()


def _iso_date(value: str | None) -> str:
    if value is None:
        return clock.today_oslo().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise DomainError("bad_date", f"{value!r} is not a valid YYYY-MM-DD date.") from exc


class ChargerRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- charger records -----------------------------------------------------

    async def create(
        self,
        *,
        name: str,
        serial_no: str | None = None,
        zaptec_id: str | None = None,
        device_type: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise DomainError("name_required", "A charger needs a name.")
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            try:
                cur.execute(
                    "INSERT INTO chargers "
                    "(zaptec_id, name, serial_no, device_type, is_active, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (zaptec_id, name, serial_no, device_type, now, now),
                )
            except sqlite3.IntegrityError as exc:
                if "zaptec_id" in str(exc):
                    raise DomainError(
                        "zaptec_id_taken", "A charger with that Zaptec id already exists."
                    ) from exc
                raise
            charger_id = int(cur.lastrowid or 0)
            write_audit_row(
                cur,
                actor,
                event_type="charger.created",
                entity_type="charger",
                entity_id=charger_id,
                summary=f"Charger {name!r} created",
                detail={"name": name, "serial_no": serial_no, "zaptec_id": zaptec_id},
            )
        return self._require(charger_id)

    def get(self, charger_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM chargers WHERE id = ?", (charger_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_zaptec_id(self, zaptec_id: str) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            "SELECT * FROM chargers WHERE zaptec_id = ?", (zaptec_id,)
        ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self._db.connection.execute("SELECT * FROM chargers ORDER BY name, id").fetchall()
        return [dict(r) for r in rows]

    async def update(
        self,
        charger_id: int,
        *,
        name: Any = _UNSET,
        serial_no: Any = _UNSET,
        device_type: Any = _UNSET,
        is_active: Any = _UNSET,
        actor: AuditContext,
    ) -> dict[str, Any]:
        incoming = {"name": name, "serial_no": serial_no, "device_type": device_type}
        fields = {k: v for k, v in incoming.items() if v is not _UNSET}
        if is_active is not _UNSET:
            fields["is_active"] = 1 if is_active else 0
        if "name" in fields:
            fields["name"] = (fields["name"] or "").strip()
            if not fields["name"]:
                raise DomainError("name_required", "A charger needs a name.")
        if not fields:
            raise DomainError("no_changes", "No fields to update.")
        now = clock.now_utc().isoformat()
        async with self._db._write() as cur:
            row = cur.execute("SELECT * FROM chargers WHERE id = ?", (charger_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"charger {charger_id} not found")
            before = dict(row)
            changed = {k: v for k, v in fields.items() if v != before[k]}
            if changed:
                assignments = ", ".join(f"{k} = ?" for k in changed)
                cur.execute(
                    f"UPDATE chargers SET {assignments}, updated_at = ? WHERE id = ?",
                    (*changed.values(), now, charger_id),
                )
                write_audit_row(
                    cur,
                    actor,
                    event_type="charger.updated",
                    entity_type="charger",
                    entity_id=charger_id,
                    summary=f"Charger {charger_id} updated: {', '.join(sorted(changed))}",
                    detail={"before": {k: before[k] for k in changed}, "after": dict(changed)},
                )
        return self._require(charger_id)

    def has_usage(self, charger_id: int) -> bool:
        """True if any imported charging row points at this charger."""
        return charger_id in self.charger_ids_with_usage()

    def charger_ids_with_usage(self) -> set[int]:
        """charger ids referenced by any imported session or interval row."""
        rows = self._db.connection.execute(
            "SELECT charger_id FROM charging_sessions WHERE charger_id IS NOT NULL "
            "UNION SELECT charger_id FROM charging_intervals WHERE charger_id IS NOT NULL"
        ).fetchall()
        return {int(r["charger_id"]) for r in rows}

    async def delete(self, charger_id: int, *, actor: AuditContext) -> None:
        """Hard-delete a hand-entered charger and its assignment history.

        Refused for Zaptec-mirrored chargers (deactivate instead — sync would
        re-create them) and for any charger that already has imported usage.
        """
        async with self._db._write() as cur:
            row = cur.execute("SELECT * FROM chargers WHERE id = ?", (charger_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"charger {charger_id} not found")
            if row["zaptec_id"] is not None:
                raise DomainError(
                    "zaptec_charger",
                    "Deaktiver i stedet – laderen speiles fra Zaptec og kommer "
                    "tilbake ved neste synk.",
                )
            usage = cur.execute(
                "SELECT "
                " (SELECT 1 FROM charging_sessions WHERE charger_id = ? LIMIT 1) "
                " OR (SELECT 1 FROM charging_intervals WHERE charger_id = ? LIMIT 1)",
                (charger_id, charger_id),
            ).fetchone()
            if usage[0]:
                raise DomainError(
                    "charger_has_usage",
                    "Laderen har importert forbruk og kan ikke slettes.",
                    status=422,
                )
            removed = [
                {"id": int(a["id"]), "member_id": int(a["member_id"])}
                for a in cur.execute(
                    "SELECT id, member_id FROM charger_assignments WHERE charger_id = ?",
                    (charger_id,),
                ).fetchall()
            ]
            cur.execute("DELETE FROM charger_assignments WHERE charger_id = ?", (charger_id,))
            cur.execute("DELETE FROM chargers WHERE id = ?", (charger_id,))
            write_audit_row(
                cur,
                actor,
                event_type="charger.deleted",
                entity_type="charger",
                entity_id=charger_id,
                summary=f"Charger {row['name']!r} deleted",
                detail={
                    "name": row["name"],
                    "serial_no": row["serial_no"],
                    "removed_assignments": removed,
                },
            )

    async def upsert_from_zaptec(
        self,
        *,
        zaptec_id: str,
        name: str,
        serial_no: str | None,
        device_id: str | None = None,
        installation_zaptec_id: str | None,
        circuit_zaptec_id: str | None,
        device_type: str | None,
        is_active: bool,
        raw: dict[str, Any],
        actor: AuditContext,
    ) -> tuple[dict[str, Any], bool]:
        """Idempotently mirror one Zaptec charger. Returns (row, created).

        ``device_id`` is Zaptec's immutable hardware id; it is not stored in its
        own column (``raw_json`` keeps it) but is recorded in the audit detail.
        """
        now = clock.now_utc().isoformat()
        payload = json.dumps(raw, sort_keys=True, default=str)
        async with self._db._write() as cur:
            existing = cur.execute(
                "SELECT * FROM chargers WHERE zaptec_id = ?", (zaptec_id,)
            ).fetchone()
            if existing is None:
                adopted = self._adopt_manual_charger(
                    cur,
                    zaptec_id=zaptec_id,
                    name=name,
                    serial_no=serial_no,
                    device_id=device_id,
                    installation_zaptec_id=installation_zaptec_id,
                    circuit_zaptec_id=circuit_zaptec_id,
                    device_type=device_type,
                    is_active=is_active,
                    payload=payload,
                    now=now,
                    actor=actor,
                )
                if adopted is not None:
                    return self._require(adopted), False
                cur.execute(
                    "INSERT INTO chargers "
                    "(zaptec_id, name, serial_no, installation_zaptec_id, circuit_zaptec_id, "
                    " device_type, is_active, last_synced_at, raw_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        zaptec_id,
                        name,
                        serial_no,
                        installation_zaptec_id,
                        circuit_zaptec_id,
                        device_type,
                        1 if is_active else 0,
                        now,
                        payload,
                        now,
                        now,
                    ),
                )
                charger_id = int(cur.lastrowid or 0)
                write_audit_row(
                    cur,
                    actor,
                    event_type="charger.synced",
                    entity_type="charger",
                    entity_id=charger_id,
                    summary=f"Charger {name!r} imported from Zaptec",
                    detail={"zaptec_id": zaptec_id, "device_id": device_id, "created": True},
                )
                return self._require(charger_id), True

            charger_id = int(existing["id"])
            cur.execute(
                "UPDATE chargers SET name = ?, serial_no = ?, installation_zaptec_id = ?, "
                "circuit_zaptec_id = ?, device_type = ?, is_active = ?, last_synced_at = ?, "
                "raw_json = ?, updated_at = ? WHERE id = ?",
                (
                    name,
                    serial_no,
                    installation_zaptec_id,
                    circuit_zaptec_id,
                    device_type,
                    1 if is_active else 0,
                    now,
                    payload,
                    now,
                    charger_id,
                ),
            )
            return self._require(charger_id), False

    # --- assignments (US-302 / US-303) -------------------------------------

    async def assign(
        self,
        charger_id: int,
        member_id: int,
        *,
        effective_from: str | None = None,
        note: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        eff = _iso_date(effective_from)
        async with self._db._write() as cur:
            if cur.execute("SELECT 1 FROM chargers WHERE id = ?", (charger_id,)).fetchone() is None:
                raise NotFoundError(f"charger {charger_id} not found")
            if cur.execute("SELECT 1 FROM members WHERE id = ?", (member_id,)).fetchone() is None:
                raise NotFoundError(f"member {member_id} not found")

            open_row = cur.execute(
                "SELECT * FROM charger_assignments WHERE charger_id = ? AND effective_to IS NULL",
                (charger_id,),
            ).fetchone()
            prev_member = None
            if open_row is not None:
                open_row = dict(open_row)
                prev_member = int(open_row["member_id"])
                if prev_member == member_id:
                    raise DomainError(
                        "already_assigned",
                        f"Charger {charger_id} is already assigned to that member.",
                    )
                if eff < open_row["effective_from"]:
                    raise DomainError(
                        "backdated",
                        f"effective_from {eff} is before the current assignment start "
                        f"{open_row['effective_from']}.",
                    )
                cur.execute(
                    "UPDATE charger_assignments SET effective_to = ? WHERE id = ?",
                    (eff, open_row["id"]),
                )

            now = clock.now_utc().isoformat()
            try:
                cur.execute(
                    "INSERT INTO charger_assignments "
                    "(charger_id, member_id, effective_from, effective_to, note, "
                    " created_at, created_by_user_id) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                    (charger_id, member_id, eff, note, now, actor.actor_user_id),
                )
            except sqlite3.IntegrityError as exc:
                if "idx_ca_one_open" in str(exc):
                    raise DomainError(
                        "assignment_conflict", "A concurrent change won the race; retry."
                    ) from exc
                raise
            new_id = int(cur.lastrowid or 0)
            write_audit_row(
                cur,
                actor,
                event_type="charger.assigned",
                entity_type="charger",
                entity_id=charger_id,
                summary=f"Charger {charger_id} assigned to member {member_id} (from {eff})",
                detail={
                    "charger_id": charger_id,
                    "member_id": member_id,
                    "previous_member_id": prev_member,
                    "effective_from": eff,
                    "note": note,
                },
            )
        return dict(
            self._db.connection.execute(
                "SELECT * FROM charger_assignments WHERE id = ?", (new_id,)
            ).fetchone()
        )

    async def unassign(
        self,
        charger_id: int,
        *,
        effective_to: str | None = None,
        actor: AuditContext,
    ) -> dict[str, Any]:
        eff = _iso_date(effective_to)
        async with self._db._write() as cur:
            if cur.execute("SELECT 1 FROM chargers WHERE id = ?", (charger_id,)).fetchone() is None:
                raise NotFoundError(f"charger {charger_id} not found")
            open_row = cur.execute(
                "SELECT * FROM charger_assignments WHERE charger_id = ? AND effective_to IS NULL",
                (charger_id,),
            ).fetchone()
            if open_row is None:
                raise DomainError("not_assigned", f"Charger {charger_id} has no open assignment.")
            open_row = dict(open_row)
            if eff < open_row["effective_from"]:
                raise DomainError(
                    "backdated",
                    f"effective_to {eff} is before the assignment start "
                    f"{open_row['effective_from']}.",
                )
            cur.execute(
                "UPDATE charger_assignments SET effective_to = ? WHERE id = ?",
                (eff, open_row["id"]),
            )
            write_audit_row(
                cur,
                actor,
                event_type="charger.unassigned",
                entity_type="charger",
                entity_id=charger_id,
                summary=f"Charger {charger_id} unassigned from member {open_row['member_id']} "
                f"(effective {eff})",
                detail={
                    "charger_id": charger_id,
                    "member_id": int(open_row["member_id"]),
                    "effective_to": eff,
                },
            )
        return dict(
            self._db.connection.execute(
                "SELECT * FROM charger_assignments WHERE id = ?", (open_row["id"],)
            ).fetchone()
        )

    def assignments(self, charger_id: int) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            "SELECT * FROM charger_assignments WHERE charger_id = ? ORDER BY effective_from, id",
            (charger_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def assignment_on(self, charger_id: int, on_date: str | None = None) -> int | None:
        d = on_date or clock.today_oslo().isoformat()
        row = self._db.connection.execute(
            "SELECT member_id FROM charger_assignments WHERE charger_id = ? "
            "AND effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)",
            (charger_id, d, d),
        ).fetchone()
        return int(row["member_id"]) if row else None

    def assignment_map(self, on_date: str | None = None) -> dict[int, int]:
        """charger_id -> member_id for every assignment covering on_date."""
        d = on_date or clock.today_oslo().isoformat()
        rows = self._db.connection.execute(
            "SELECT charger_id, member_id FROM charger_assignments "
            "WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)",
            (d, d),
        ).fetchall()
        return {int(r["charger_id"]): int(r["member_id"]) for r in rows}

    def zaptec_assignment_map(self, on_date: str | None = None) -> dict[str, int]:
        """charger zaptec_id -> member_id for assignments covering on_date. Used
        when resolving imported charging sessions to a member."""
        d = on_date or clock.today_oslo().isoformat()
        rows = self._db.connection.execute(
            "SELECT c.zaptec_id AS zid, a.member_id AS mid FROM charger_assignments a "
            "JOIN chargers c ON c.id = a.charger_id "
            "WHERE c.zaptec_id IS NOT NULL AND a.effective_from <= ? "
            "AND (a.effective_to IS NULL OR a.effective_to > ?)",
            (d, d),
        ).fetchall()
        return {str(r["zid"]): int(r["mid"]) for r in rows}

    def member_chargers(self, member_id: int, on_date: str | None = None) -> list[dict[str, Any]]:
        d = on_date or clock.today_oslo().isoformat()
        rows = self._db.connection.execute(
            "SELECT c.* FROM chargers c JOIN charger_assignments a ON a.charger_id = c.id "
            "WHERE a.member_id = ? AND a.effective_from <= ? "
            "AND (a.effective_to IS NULL OR a.effective_to > ?) ORDER BY c.name",
            (member_id, d, d),
        ).fetchall()
        return [dict(r) for r in rows]

    def unassigned_charger_ids(self, on_date: str | None = None) -> set[int]:
        """Active chargers with no assignment covering on_date."""
        assigned = set(self.assignment_map(on_date))
        return {c["id"] for c in self.list() if c["is_active"] and c["id"] not in assigned}

    # --- internals ---------------------------------------------------------

    def _adopt_manual_charger(
        self,
        cur: sqlite3.Cursor,
        *,
        zaptec_id: str,
        name: str,
        serial_no: str | None,
        device_id: str | None,
        installation_zaptec_id: str | None,
        circuit_zaptec_id: str | None,
        device_type: str | None,
        is_active: bool,
        payload: str,
        now: str,
        actor: AuditContext,
    ) -> int | None:
        """If exactly one hand-entered charger's serial matches this Zaptec unit,
        attach the Zaptec id to it instead of inserting a duplicate. Returns the
        adopted charger id, or ``None`` to fall through to a plain INSERT."""
        key = (device_id or serial_no or "").strip().lower()
        if not key:
            return None
        candidates = cur.execute(
            "SELECT * FROM chargers WHERE zaptec_id IS NULL AND lower(trim(serial_no)) = ?",
            (key,),
        ).fetchall()
        if len(candidates) != 1:
            return None
        adopt = dict(candidates[0])
        charger_id = int(adopt["id"])
        cur.execute(
            "UPDATE chargers SET zaptec_id = ?, name = ?, serial_no = ?, "
            "installation_zaptec_id = ?, circuit_zaptec_id = ?, device_type = ?, "
            "is_active = ?, last_synced_at = ?, raw_json = ?, updated_at = ? WHERE id = ?",
            (
                zaptec_id,
                name or adopt["name"],
                serial_no,
                installation_zaptec_id,
                circuit_zaptec_id,
                device_type,
                1 if is_active else 0,
                now,
                payload,
                now,
                charger_id,
            ),
        )
        write_audit_row(
            cur,
            actor,
            event_type="charger.adopted",
            entity_type="charger",
            entity_id=charger_id,
            summary=f"Manual charger {adopt['name']!r} adopted by Zaptec {zaptec_id}",
            detail={
                "zaptec_id": zaptec_id,
                "device_id": device_id,
                "previous_name": adopt["name"],
                "matched_on": key,
            },
        )
        return charger_id

    def _require(self, charger_id: int) -> dict[str, Any]:
        row = self.get(charger_id)
        if row is None:
            raise NotFoundError(f"charger {charger_id} not found")
        return row
