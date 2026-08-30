# Charger serial, edit/delete, and pre-import usage attribution

Bug-fix batch on top of Release 1C (`0.3.1`). Three related defects found while
operating the portal against the live Zaptec installation.

## What changed

### 1. Zaptec charger serial (`serial_no` from `DeviceId`)

`ZaptecCharger.parse` mapped `serial_no` from Zaptec's `SerialNo` field. In this
installation `SerialNo` duplicates the display `Name`, so a synced charger showed
the same string in "Navn" and "Serienr." The real hardware id is `DeviceId`
(`ZPR…`) — the value admins hand-entered for manual chargers.

- `serial_no` now comes from `DeviceId` (fallback `SerialNo`).
- `device_id` is threaded through `sync_chargers` → `upsert_from_zaptec` and
  recorded in the `charger.synced` / `charger.adopted` audit detail. No new
  column — `raw_json` already keeps the full payload.
- Migration `0008_charger_serial_backfill.sql` rewrites `serial_no` for
  already-synced rows from `raw_json.DeviceId`, leaving hand-corrected serials
  and manual chargers untouched.

### 2. Charger edit + delete + adopt-on-sync

- `EditChargerModal` wires the pre-existing `PATCH /api/chargers/{id}` into the
  Chargers page (name / serial / device type / active).
- `DELETE /api/chargers/{id}` — hard delete, **manual chargers only**
  (`zaptec_id IS NULL`), refused when the charger has imported
  sessions/intervals (`charger_has_usage`, 422) or is Zaptec-mirrored
  (`zaptec_charger`, 422 — deactivate instead). Cascade-removes the charger's
  assignment history; one `charger.deleted` audit row. `ChargerOut.deletable`
  drives the "Slett" button.
- `upsert_from_zaptec` now **adopts** a single hand-entered charger whose serial
  equals the incoming `DeviceId` (attaches `zaptec_id`, keeps the admin's name,
  writes `charger.adopted`) instead of inserting a duplicate. Ambiguous (0 or ≥2)
  matches fall through to a normal insert.

### 3. Retroactive member attribution

Attribution keyed off `zaptec_id` only, and only via an assignment effective on
the session's date — so usage imported before its charger existed, usage on
hand-entered chargers, and sessions predating a late-created assignment were all
stuck as unassigned.

- Resolution now goes through the local charger id (`ChargerRepo.local_id_index`:
  by `zaptec_id`, then by lower-cased `serial_no` / `DeviceId`), and
  `import_sessions` / `reresolve_members` write the resolved `charger_id` back
  onto the stored rows.
- `assign` / `unassign` routes and `sync_chargers` now trigger
  `reresolve_after_assignment` / `reresolve_unresolved`, which re-resolve every
  affected month **except** those owned by a posted settlement.
- The assign control has a back-date field; the Chargers page and the settlement
  detail page show an unassigned-kWh banner with a "Kjør ny fordeling" button
  (`POST /api/charging/reresolve`).
- `settlement.compute` emits a post-blocking `usage_stale` warning when the
  frozen snapshot no longer matches the imported usage (unassigned kWh appeared,
  or a session's `updated_at` is later than `usage_frozen_at`). Remedy: "Frys på
  nytt".

## Operator runbook — cleaning up the current data

The live DB has three hand-entered chargers (`146B` / `146C` / `148A`) duplicated
by their Zaptec-synced rows, all assignments starting `2026-08-30` (after the
August sessions), and one never-frozen draft settlement for `2026-08`.

After deploying this batch (which runs migration `0008`):

1. **Chargers page → for each Zaptec charger** (`146B→Christer`, `146C→Iman`,
   `148A→Einar`; `148C→Arnt Kåre` is already on the Zaptec row): set the
   back-date field to `2026-08-01` and assign the member. This supersedes the
   wrong assignments that currently sit on the manual duplicates.
2. The unassigned-kWh banner should now read 0 kWh for `2026-08`. If not, click
   **Kjør ny fordeling**.
3. **Delete the three manual duplicates** (`146B` / `146C` / `148A` with
   `Manuell` in the Zaptec column) — now permitted (manual, no usage; their
   stale assignments cascade away).
4. **Settlements → 2026-08 → Frys forbruk**. `unassigned_total_kwh` is 0, so the
   freeze succeeds and the preview shows per-member kWh.

### Rejected alternative

An automated merge migration (move each manual charger's open assignment to its
Zaptec twin matched on `serial_no` ↔ `raw_json.DeviceId`, delete the manual row)
was considered. Rejected: it cannot fix the wrong `effective_from`, it runs
unattended for every deployment, and the manual path above is auditable and
corrects the assignment dates at the same time.
