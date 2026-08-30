# Release 1B — build plan

Product scope (`spec.md` Release 1B): **Zaptec integration, settlement engine,
invoice handling, PDF reports, email reports** — plus **Epic 3 charger
management** (deferred from 1A) and **US-102 magic-link / US-103 password reset**
(need email, deferred from 1A).

Architecture and 1A decisions: [`implementation-plan.md`](./implementation-plan.md).
This session executes **all of 1B**. PDF rendering is the one explicit deferral:
reports ship as self-contained **HTML** now, PDF is a follow-up.

Target version: **`0.2.0`** (`VERSION` + `pyproject.toml` in lockstep).

## Status — COMPLETE (2026-08-30)

All of P1–P11 shipped. Deviations from this plan as written:

- **Migrations renumbered** one concern per file: `0002` chargers,
  `0003` zaptec_installations + sync_runs, `0004` charging_sessions +
  charging_intervals, `0005` settlements (+ ledger rebuild + late_session_flags),
  `0006` email_messages + auth_tokens.
- **P5 + P6 landed as one commit** (`feat(settlement): …`) — freeze / compute /
  post are one cohesive module; splitting the tests across two commits was not
  worth the churn.
- **Late-session detection (US-406)** table (`late_session_flags`) and the
  `_unresolved_late` warning path exist; the automatic *detector* that compares
  re-imported sessions against a posted snapshot is a thin follow-up (the
  correction workflow it feeds is 1D).
- **`scripts/probe_zaptec.py` not yet run against the real installation** —
  `.env` carries `ZAPTEC_PASSWORD` + `ZAPTEC_INSTALLATION_ID` but not
  `ZAPTEC_USERNAME`. The adapter + its respx contract tests are written to the
  documented API shapes; fill § Probe findings once the probe runs.

---

## Decisions locked for 1B

| # | Decision | Note |
|---|---|---|
| B1 | **Zaptec auth** = OAuth2 password grant against `api.zaptec.com`; token cached in memory, refreshed on 401. Username in `config.yaml`, password via `ZAPTEC_PASSWORD` env (mirrors `LADELAUG_SECRET_KEY`). | `zaptec/client.py`, `httpx.AsyncClient` + `tenacity` retry on 5xx / timeout. |
| B2 | **Probe first.** `scripts/probe_zaptec.py` runs against the real installation before the adapter is trusted — records endpoint, pagination, and 15-min interval shapes. Findings pasted into this file (§ Probe findings). | Throwaway; not imported by the app. |
| B3 | **Charger → member link is effective-dated**, one open assignment per *charger* (partial unique index), non-overlapping enforced in the repo (reuse the `_replace_open_period` pattern). A member may hold several chargers at once (US-303) — no uniqueness on `member_id`. | `charger_assignments`. |
| B4 | **Consumption is attributed to the member assigned to the charger on the session's start date.** A session on a charger with no assignment that day is *unassigned consumption* (US-304) and **blocks settlement freeze** until resolved. | `ChargingRepo.consumption_by_member` / `unassigned_consumption`. |
| B5 | **Cross-month sessions (US-405)** are split at the month boundary by priority: (1) 15-min interval data if present, (2) energy-point / partial-kWh data, (3) pro-rata by duration. The chosen method is recorded on each split part. | `ChargingRepo._split_session`. |
| B6 | **Late-session detection (US-406)** compares newly-imported / changed sessions against the frozen usage snapshot of any *posted* settlement covering that month. A mismatch writes a `late_session_flags` row — **no automatic financial change**; the admin resolves via a 1D correction. | |
| B7 | **Settlement money allocation** = `money.allocate_by_weights(total_ore, weights)`: integer largest-remainder apportionment; the **residual øre goes to the largest weight** (ties → lowest member id) so `sum(parts) == total_ore` exactly (US-610). | New, heavily unit-tested. |
| B8 | **Equal-cost lines** split across members `participates == True` in the frozen snapshot; **consumption lines** split across **all active members** by kWh ratio (excluded members still pay consumption — US-203 / US-607). Zero total consumption **blocks** a settlement with any consumption line (US-607). | |
| B9 | **`settlement_participation` is snapshotted at freeze** (not post) into `settlement_members`; freeze is re-runnable while `draft`, post is not. Posting is idempotent (second call → `already_posted`). | US-203 "frozen on posting" — we freeze at the explicit freeze step, which must precede post. |
| B10 | **Posting writes ledger rows** of a new `txn_type = 'settlement_charge'` (negative `amount_ore` = a debit to the member), each carrying `settlement_id`. Migration `0004` rebuilds `ledger_transactions` (12-step) to widen the `CHECK` and add the `settlement_id` column + FK; append-only triggers and indexes recreated. | US-609 / US-1102. |
| B11 | **Invoice attachment (US-604)** stored on disk under `state/attachments/<settlement_id>/`, filename + relative path in `settlements`. Required before `post`. Served admin-only. | |
| B12 | **Email** has three backends: `console` (dev, logs), `file` (`.eml` under `state/mail/`), `smtp` (stdlib `smtplib` in a worker thread). Queue table `email_messages` with attempts + exponential backoff; `POST /api/notifications/process` drains it (documented cron). US-1001 / US-1002. | |
| B13 | **Magic-link / reset tokens** — `auth_tokens` (`kind`, `token_hash` sha256, `expires_at`, single-use `used_at`). Request endpoints always return 200 (no account enumeration); disabled users never get a working link. US-102 / US-103. | |
| B14 | **Reports** — `reports/settlement_report.py` renders one self-contained HTML page per member + a settlement summary, saved under `state/reports/<period>/`. Forecast / recommended-top-up sections are stubbed (Epic 8 is 1C). US-905 (HTML), US-904/906 member-facing. | |
| B15 | New runtime dirs (`state/attachments`, `state/mail`, `state/reports`) live under the existing `state/` volume — no new Docker volume. `state/` backup still captures everything. | |

---

## Probe findings

_Filled in after running `scripts/probe_zaptec.py` against the real installation._

- OAuth token endpoint: _tbd_
- Installations list: _tbd_
- Chargers list: _tbd_
- Archived charging sessions endpoint + pagination: _tbd_
- 15-minute interval / energy-details shape: _tbd_

---

## Data model additions

### `migrations/0002_chargers.sql`
- **`chargers`** — `id, zaptec_id TEXT UNIQUE NULL, name, serial_no, installation_zaptec_id, circuit_zaptec_id, device_type, is_active INT DEFAULT 1, last_synced_at, raw_json, created_at, updated_at`.
- **`charger_assignments`** — `id, charger_id REFERENCES chargers(id), member_id REFERENCES members(id), effective_from DATE, effective_to DATE NULL, note, created_at, created_by_user_id`. `INDEX (charger_id, effective_from)`; partial `UNIQUE INDEX idx_ca_one_open ON (charger_id) WHERE effective_to IS NULL`.

### `migrations/0003_charging_data.sql`
- **`zaptec_installations`** — `id, zaptec_id TEXT UNIQUE, name, raw_json, first_connected_at, updated_at`.
- **`sync_runs`** — `id, kind TEXT CHECK (kind IN ('chargers','sessions','intervals')), started_at, finished_at, status TEXT CHECK (status IN ('ok','error','partial')), window_from, window_to, items_seen INT, items_imported INT, error, created_by_user_id`.
- **`charging_sessions`** — `id, zaptec_session_id TEXT, charger_id REFERENCES chargers(id) NULL, charger_zaptec_id TEXT, member_id REFERENCES members(id) NULL, period_month TEXT, started_at, ended_at, energy_kwh TEXT, split_method TEXT NULL, split_parent_zaptec_id TEXT NULL, source TEXT, raw_json, imported_at, updated_at`. `UNIQUE INDEX idx_cs_zaptec ON (zaptec_session_id, period_month)` (a cross-month split yields one row per month, same source id); `INDEX (period_month)`, `INDEX (charger_id, started_at)`.
- **`charging_intervals`** — `id, charger_id REFERENCES chargers(id) NULL, charger_zaptec_id TEXT, member_id NULL, period_month TEXT, interval_start, interval_end, energy_kwh TEXT, raw_json, imported_at`. `UNIQUE INDEX ON (charger_zaptec_id, interval_start)`; `INDEX (period_month)`.
- **`late_session_flags`** — `id, zaptec_session_id, charger_zaptec_id, period_month, settlement_id REFERENCES settlements(id) NULL, kind TEXT ('new'|'changed'), detail_json, detected_at, resolved_at, resolved_by_user_id, note`.

### `migrations/0004_settlements.sql`
- **`settlements`** — `id, period_month TEXT UNIQUE, status TEXT CHECK (status IN ('draft','posted')) DEFAULT 'draft', invoice_kwh TEXT NULL, invoice_total_nok TEXT NULL, grid_kwh TEXT NULL, attachment_filename NULL, attachment_path NULL, note, usage_frozen_at NULL, created_at, created_by_user_id, posted_at NULL, posted_by_user_id NULL`.
- **`settlement_invoice_lines`** — `id, settlement_id, description, category TEXT, allocation_method TEXT CHECK (allocation_method IN ('equal','consumption')), amount_ore INT, amount_nok TEXT, sort_order INT, created_at`. (US-605)
- **`settlement_members`** — the freeze snapshot: `id, settlement_id, member_id, member_reference, full_name, is_active INT, participates_equal INT, consumption_kwh TEXT, session_count INT, balance_before_ore INT NULL, snapshot_json`. `UNIQUE (settlement_id, member_id)`. (US-602 / US-203 freeze)
- **`settlement_allocations`** — `id, settlement_id, member_id, invoice_line_id REFERENCES settlement_invoice_lines(id) NULL, kind TEXT ('equal','consumption'), amount_ore INT, amount_nok TEXT`. (US-606/607/610)
- **`ledger_transactions`** rebuilt: `txn_type` CHECK gains `'settlement_charge'` (and `'settlement_reversal'` reserved for 1D); new `settlement_id INTEGER REFERENCES settlements(id)` column; `idx_ledger_member`, `idx_ledger_one_reversal`, `trg_ledger_no_update`, `trg_ledger_no_delete` recreated; add `INDEX idx_ledger_settlement ON (settlement_id) WHERE settlement_id IS NOT NULL`.

### `migrations/0005_email_auth_tokens.sql`
- **`email_messages`** — `id, to_address, subject, body_text, body_html NULL, template TEXT, related_entity_type NULL, related_entity_id NULL, status TEXT CHECK (status IN ('queued','sent','failed')) DEFAULT 'queued', attempts INT DEFAULT 0, max_attempts INT DEFAULT 5, last_error NULL, next_attempt_at, created_at, sent_at NULL`. `INDEX (status, next_attempt_at)`.
- **`auth_tokens`** — `id, user_id REFERENCES users(id), kind TEXT CHECK (kind IN ('magic_link','password_reset')), token_hash TEXT UNIQUE, created_at, expires_at, used_at NULL, requested_ip`. `INDEX (user_id, kind)`.

---

## Ordered work items (one reviewable commit each)

| # | Commit | Scope | User stories |
|---|---|---|---|
| **P1** | `feat(chargers): records + effective-dated assignments` | `0002`; `domain/chargers.py` `ChargerRepo` (`create`/`update`/`get`/`list`, `assign`/`unassign`/`assignments`, `assignment_on`/`member_chargers`/`unassigned_charger_ids`); `routes/chargers.py` (admin); `schemas.py`; `test_chargers.py`. | US-302, US-303 |
| **P2** | `feat(zaptec): API client + probe script` | `ZaptecConfig` in `config.py`; `zaptec/__init__.py` + `zaptec/client.py` (`ZaptecClient`: `authenticate`, `list_installations`, `list_chargers`, `iter_sessions`, `session_energy_details`); `scripts/probe_zaptec.py`; `config/config.example.yaml` + README; `test_zaptec_client.py` (respx). **Run the probe; fill § Probe findings.** | US-401 |
| **P3** | `feat(zaptec): charger sync` | `0003` (`zaptec_installations`, `sync_runs`); `zaptec/sync.py` `ZaptecSync.sync_chargers`; `ChargerRepo.upsert_from_zaptec` (idempotent on `zaptec_id`); `routes/zaptec.py` `POST /api/zaptec/sync/chargers`, `GET /api/zaptec/status`; `test_charger_sync.py`. | US-301, US-403 (status) |
| **P4** | `feat(charging): session + interval import` | `0003` (`charging_sessions`, `charging_intervals`, `late_session_flags`); `domain/charging.py` `ChargingRepo` (`import_sessions` idempotent + member resolution + cross-month split; `import_intervals`; `detect_late_sessions`; `consumption_by_member(month)`; `unassigned_consumption(month)`); `zaptec/sync.py` `sync_sessions`; `routes/zaptec.py` (`POST /sync/sessions`, `GET /api/charging/consumption`, `/unassigned`); `test_charging_import.py`. | US-402, US-404, US-405, US-406, US-304 |
| **P5** | `feat(settlement): draft, invoice lines, freeze + allocation math` | `money.allocate_by_weights` + `test_allocate.py`; `0004`; `domain/settlement.py` `SettlementRepo` (`create_draft`, `set_invoice`, `add_line`/`update_line`/`delete_line`, `attach_invoice`, `freeze` → snapshot + guards); `test_settlement_freeze.py`. | US-601, US-602, US-603, US-604, US-605 |
| **P6** | `feat(settlement): compute, preview, post` | `SettlementRepo.compute`/`preview`/`post` (idempotent; ledger `settlement_charge` rows); `routes/settlement.py` grows (`drafts`, `{id}`, `invoice`, `lines`, `attachment`, `freeze`, `preview`, `post`); `schemas.py`; `test_settlement_engine.py` (rounding determinism, `sum == invoice`, negative-balance warnings, blocks). | US-606, US-607, US-608, US-609, US-610, US-1103 |
| **P7** | `feat(reports): HTML settlement reports` | `reports/settlement_report.py`; `routes/settlement.py` (`GET {id}/reports`, `{id}/reports/{member_id}`); `routes/me.py` (`/api/me/settlements`, `/api/me/settlements/{id}/report`); `test_settlement_reports.py`. | US-905 (HTML), US-904 |
| **P8** | `feat(notifications): email queue + settlement emails + health` | `0005` (`email_messages`); `email/sender.py` (`console`/`file`/`smtp`); `domain/notifications.py` `NotificationRepo` (`enqueue`, `process_queue` with backoff); post-settlement hook enqueues per-member report emails; `routes/notifications.py` (`POST /process`), `routes/system.py` (`GET /api/system/health` — Zaptec last sync, queue stats, failed jobs); `EmailConfig` in `config.py`; `test_notifications.py`. | US-1001, US-1002, US-1104 |
| **P9** | `feat(auth): magic-link + password reset` | `0005` (`auth_tokens`); `domain/auth_tokens.py`; `routes/auth.py` (`POST /api/auth/magic-link[/consume]`, `/password-reset/request[/consume]`); enqueue via `NotificationRepo`; `test_auth_tokens.py`. | US-102, US-103 |
| **P10** | `feat(web): Release 1B UI` | Chargers (list/detail/assignment timeline), Zaptec sync panel, Settlements (list, draft editor, freeze, preview + warnings, post), member settlement history + report, system health, magic-link / reset forms; `api/client.ts` wrappers; MSW handlers; Vitest. | — |
| **P11** | `docs: Release 1B` | README (Zaptec config, settlement workflow, email config, sync + queue cron), consolidated CHANGELOG "Release 1B", `VERSION`/`pyproject` → `0.2.0`, `implementation-plan.md` status, `config.example.yaml` final. | — |

**Done** = `uv run ruff check` + `uv run ruff format --check` + `uv run pytest -q`
green (and `npm run check` from P10). Behaviour-changing items touch `CHANGELOG.md`.

---

## Residual risks

- **Zaptec wire format drift** — the adapter is written to the probe output; a
  contract test (`test_zaptec_client.py`) pins the parsed shapes, and
  `probe_zaptec.py` stays in the tree for re-checking.
- **Cross-month split accuracy** — interval data is authoritative; the pro-rata
  fallback is explicitly flagged (`split_method='duration'`) for admin review.
- **Ledger table rebuild (`0004`)** — done inside the migration's single
  transaction; `test_migrations.py` gains a check that the triggers and the new
  `CHECK` survive; existing 1A ledger tests are the regression guard.
- **Allocation rounding** — `allocate_by_weights` is total-preserving by
  construction (residual to the largest weight); a property-style test sweeps
  many totals / weight vectors asserting `sum(parts) == total`.
- **Settlement double-post** — `status` gate + the per-`settlement_id` ledger
  rows make a second post raise `already_posted` before any write.
- **Account enumeration on magic-link / reset** — request endpoints always 200
  with a generic body; work happens only if the user exists and is enabled.
- **SMTP blocking the event loop** — `smtplib` send runs in a thread via
  `anyio.to_thread`; the queue drain is an explicit endpoint, not an inline
  send on the request path.
