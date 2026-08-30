# Changelog

Newest entries on top. Dates are ISO (YYYY-MM-DD).

## 2026-08-30 — Release 1B (`0.2.0`)

Zaptec integration, the monthly settlement engine, and everything they need.

- **Charger management (Epic 3)** — charger records (hand-entered or mirrored
  from Zaptec), effective-dated charger→member assignments (one open per
  charger; a member may hold several at once), non-overlapping history.
- **Zaptec integration (Epic 4)** — `ZaptecClient` (OAuth2 password grant,
  token refresh, retry/backoff); `POST /api/zaptec/sync/chargers` and
  `/sync/sessions`; archived charging sessions + 15-minute interval import,
  idempotent, member resolved from the assignment on each part's start date;
  **cross-month sessions split** (interval data first, pro-rata by duration
  otherwise); **unassigned consumption blocks settlement** until resolved;
  `sync_runs` bookkeeping and `GET /api/zaptec/status`. Config-gated
  (`zaptec.enabled`); `scripts/probe_zaptec.py` for verifying the wire format.
- **Settlement engine (Epic 6)** — one settlement per calendar month,
  draft → freeze → preview → post. Freeze snapshots participation (as of the
  last day of the month), per-member consumption, and balance-before. Invoice
  lines are `equal` (across participants) or `consumption` (across kWh share;
  excluded members still pay consumption). `money.allocate_by_weights` is
  total-preserving — the residual øre land on the largest weight. Preview
  surfaces warnings (negative balances, missing invoice kWh / attachment,
  zero consumption, late sessions, kWh mismatch). Post writes one immutable
  `settlement_charge` ledger row per member (carrying `settlement_id`) and is
  idempotent. Invoice PDF attachment required before posting.
- **Reports (Epic 9, HTML)** — a self-contained HTML report per member plus a
  summary, saved under `state/reports/<month>/` at post time and served at
  `/api/settlement/{id}/reports/*` and `/api/me/settlements`. PDF rendering is
  a later follow-up.
- **Email (Epic 10)** — queued outgoing mail with retry/backoff and a
  terminal `failed` state; `console` / `file` / `smtp` backends;
  `POST /api/notifications/process` drains the queue (wire to cron). Posting a
  settlement enqueues a report email per member with a linked account.
- **Passwordless sign-in & password reset (US-102 / US-103)** — single-use
  expiring links; request endpoints never reveal whether an account exists;
  a reset revokes all of the user's sessions.
- **System health (US-1104)** — `GET /api/system/health`: Zaptec last-sync
  state, email queue stats, failed-job count, schema + app version.
- **Web UI** — admin screens for chargers, the settlement workflow, and
  system health; member settlement history; magic-link / reset on the login
  page.

Schema: migrations `0002`–`0006`; `0005` rebuilds `ledger_transactions` to
widen `txn_type` and add `settlement_id` (append-only triggers preserved).
New runtime dirs under `state/`: `attachments/`, `reports/`, `mail/`.

Deferred to 1C: forecasting, low-balance warnings, PDF reports. To 1D:
corrections, refunds, member departure, charging-access workflows.

The per-phase entries below record how it was built.

## 2026-08-30 — PDF settlement reports (Release 1C phase P4)

- `reports/pdf.py` — `PDF_AVAILABLE` (set by a guarded `import weasyprint`) and
  `html_to_pdf(html, *, base_url=None) -> bytes`. WeasyPrint dlopen's
  Pango/cairo/GObject at import time; when those native libraries are missing the
  import is swallowed, `PDF_AVAILABLE` is `False`, and `html_to_pdf` raises
  `DomainError("pdf_unavailable", status=503)`. Nothing at import time raises.
- `GET /api/settlement/{id}/reports/{member_id}.pdf` and
  `GET /api/settlement/{id}/reports/summary.pdf` (admin) and
  `GET /api/me/settlements/{id}/report.pdf` (member, resolved from the session) —
  render the same HTML as the existing endpoints through `html_to_pdf` and return
  `application/pdf` with an inline `Content-Disposition`. `503 pdf_unavailable`
  propagates naturally.
- `reports.write_reports` also writes the sibling `.pdf` (`medlem-<id>.pdf`,
  `sammendrag.pdf`) at post time, but only when `PDF_AVAILABLE` and wrapped so any
  failure is swallowed — a settlement post never fails because of PDF.
- `weasyprint` added to `[project].dependencies`; the Dockerfile runtime stage
  installs the WeasyPrint native libraries.

## 2026-08-30 — Low-balance warnings (Release 1C phase P3)

- `NotificationRepo.scan_low_balances(*, actor)` — iterates
  `ForecastRepo.all_member_forecasts()`, skips `available: false`, and for each
  member below their recommended minimum enqueues a Norwegian warning email,
  inserts one `low_balance_notifications` row (linked to the queued
  `email_messages` id) and one `notifications.low_balance_warned` audit event in
  one locked transaction. Suppression (decision C6): re-send only when there is
  no prior row within `notify_cooldown_days`, OR the balance dropped ≥ 100 øre
  since the last row, OR the severity escalated `low → critical`. Returns
  `{scanned, below, queued, suppressed}`; idempotent within the cooldown window.
- `POST /api/notifications/low-balance-scan` (admin, `require_fetch`) and a
  `low-balance-scan` CLI subcommand — mirror `/process`; wire to cron and drain
  the queue afterwards.
- `GET /api/system/health` gains
  `low_balance: {warned_total, members_below}`.

## 2026-08-30 — Forecast settings + member forecast/consumption API (Release 1C phase P2)

- `webapp/routes/forecast.py` — admin router (`require_admin`):
  `GET /api/forecast/settings`, `PUT /api/forecast/settings` (`require_fetch`;
  the audit row is written by `ForecastRepo.update_settings`), and
  `GET /api/forecast/members` (overview list from `all_member_forecasts()`).
- `routes/me.py` — `GET /api/me/forecast` (the caller's own
  `ForecastRepo.member_forecast`) and
  `GET /api/me/consumption?month=YYYY-MM` (metered kWh + session count for the
  month, defaulting to the current Europe/Oslo month; `US-902` pre-settlement
  view). Member id is always resolved from the session.
- `ChargingRepo.member_consumption(member_id, month)` and
  `member_session_count(member_id, month)`.
- `schemas.py` — `ForecastSettingsIn` / `ForecastSettingsOut`,
  `MemberForecastOut`, `MemberConsumptionOut`.

## 2026-08-30 — Trailing-mean forecast engine (Release 1C phase P1)

- `migrations/0007_forecast.sql` — `forecast_settings` (admin-tunable singleton,
  `id` CHECK `= 1`, seeded by the migration) and `low_balance_notifications`
  (warning-email send history).
- `domain/forecast.py` `ForecastRepo` — a pure read-model over posted
  settlements + the ledger. `settings()` / `update_settings()`
  (`forecast.settings_updated` audit with before/after), `history_stats()`
  (per-settlement derived rate + equal-cost share and their trailing means),
  `member_forecast(member_id)` and `all_member_forecasts()`.
- Forecast per member: `forecast_kwh` = mean of the member's
  `consumption_kwh` over the last `lookback_settlements` (default 3) posted
  settlements they appear in; consumption rate = admin override, else the mean
  of `sum(consumption line øre) / grid_kwh` over settlements with
  `grid_kwh > 0`; equal-cost share added only when the member currently
  participates; recommended minimum balance = `forecast_monthly_cost × buffer`
  (default 2.0). Fewer postings than the lookback, or no positive historical
  `grid_kwh` and no override, → `available: false`. All arithmetic in integer
  øre; the only `Decimal` boundary is `forecast_kwh × rate` (`ROUND_HALF_EVEN`).

## 2026-08-30 — Release 1A

First release: the foundation the settlement engine (1B) will build on.

- **Identity & access** — email/password sign-in, server-side sessions (opaque
  cookie, argon2id, sliding expiry, revoke on logout/disable), DB-backed login
  rate limiting, role-based access (admin/member), `create-admin` CLI and
  optional `bootstrap_admin`.
- **Member administration** — member CRUD; effective-dated active/inactive
  status with history and as-of queries; settlement participation (equal-cost
  include/exclude, excluded members still receive consumption costs) and a
  `suggested-participants` endpoint.
- **Financial ledger** — append-only payments / one-time reversals / manual
  credit-debit adjustments; balance = `SUM(amount_ore)`, never stored; øre and
  decimal string derived from one value.
- **Audit** — one audit event per mutation in the same transaction; admin
  `GET /api/audit-events` with filters, pagination, and per-type counts.
- **Member self-service** — `/api/me`, `/api/me/balance`, `/api/me/ledger`,
  `/api/me/status`, all scoped to the caller's own member by session.
- **Web UI** — bundled React SPA: admin members / status / participation /
  ledger / audit screens and a member "My account" view.
- Docker image on `ghcr.io/taraldb/ladelaug-avregning`; sample reverse-proxy
  config under `deploy/`.

Deferred to later releases: Zaptec sync + settlement engine (1B); forecasting /
low-balance warnings (1C); corrections / refunds / departure / access (1D).

The per-phase entries below record how it was built.

## 2026-08-30 — Financial ledger (Release 1A phase E)

- `LedgerRepo` + admin API for the append-only member ledger:
  `POST /api/members/{id}/payments`, `POST /api/members/{id}/adjustments` (credit/debit,
  reason required), `POST /api/ledger-transactions/{id}/reverse`,
  `GET /api/members/{id}/balance`, `GET /api/members/{id}/ledger`.
- Balance is always `SUM(amount_ore)`, never stored. `amount_ore` (canonical, signed) and
  `amount_nok` are both derived from one `Decimal` (`money.py`, banker's rounding) so they
  cannot drift.
- A payment is reversed at most once (equal-and-opposite `payment_reversal` row); only
  `payment` rows can be reversed. Rows are immutable — no update/delete path, plus the
  existing `BEFORE UPDATE/DELETE` triggers.
- Each write pairs its row with one `audit_events` entry in the same transaction
  (`ledger.payment_recorded` / `ledger.adjusted` / `ledger.payment_reversed`,
  `entity_type="ledger_transaction"`).
- US-505 refunds remain scheduled for Release 1D.

## 2026-08-30 — Member administration (Release 1A phase C)

- `MemberRepo` and admin CRUD: `POST` / `GET` / `PATCH /api/members`, `GET /api/members/{id}`.
  `member.created` / `member.updated` audit events (the update records before/after).
- Effective-dated active status (`member_status_periods`, half-open `[from, to)`): `POST
  /api/members/{id}/status`, `GET /api/members/{id}/status-history`. Changing status closes the
  open period and opens a new one under the write lock; back-dating before the open period and
  no-op changes are rejected; `member.status_changed` audit.
- Settlement participation (`settlement_participation`): `POST /api/members/{id}/participation`,
  `GET /api/members/{id}/participation-history`, and `GET /api/settlement/suggested-participants`
  (active members, defaulting to included; an explicit row overrides). Excluded members are
  still consumption-cost recipients. `member.participation_changed` audit. **The 1B settlement
  engine must snapshot `settlement_participation` at post time — this only records the live wish.**
- Request-body validation failures now use the uniform `{"detail": {"code": "validation_error",
  "message": ...}}` shape.

## 2026-08-30 — Identity & authentication (Release 1A phase B)

- `UserRepo` and a `create-admin` CLI command; optional `bootstrap_admin` creates the first
  administrator on startup when the `users` table is empty.
- Password sign-in with server-side sessions: `POST /api/auth/login` / `POST /api/auth/logout`
  / `GET /api/auth/me`. Opaque 256-bit cookie token (`sha256` stored), argon2id hashing with
  transparent rehash, sliding expiry, instant revocation on logout or user-disable.
- DB-backed login rate limiting: a full `(email, ip)` window returns `429` + `Retry-After`
  before any argon2 work.
- CSRF: mutating requests must send `X-Requested-With: fetch` (`SameSite=Lax` cookie).
- RBAC dependencies `require_admin` / `get_current_member`; member data will be served only
  from `/api/me/*`.
- Admin-only audit read API: `GET /api/audit-events` (filter + paginate + type counts) and
  `GET /api/audit-events/{id}`.
- New `clock` module as the single source of "now" (freezable in tests).

## 2026-08-30 — Initial scaffold

Project layout, configuration module, SQLite versioned-migration runner with the Release 1A
schema (users, sessions, members with effective-dated status/participation, append-only
ledger and audit tables), money/audit/security primitives, and a FastAPI app factory
serving `/api/health`. No feature endpoints yet.
