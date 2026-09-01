# Changelog

Newest entries on top. Dates are ISO (YYYY-MM-DD).

## Unreleased

- **Admins can view the member portal "as" a member (read-only)** — a
  **Se som medlem** action on each row of the `/medlemmer` list drops the admin
  into that member's "Min konto" exactly as they see it (balance, prognosis,
  history, settlements, status, charging-access banner). An amber
  *"Du ser portalen som …"* banner stays pinned under the header with an
  **Avslutt** button, and the admin nav is hidden until then. It is strictly
  read-only: every `/api/me/*` write returns 403 `view_as_read_only`, and the
  admin is never handed the member's session (no email links, no password
  reset). New: migration `0015` (`sessions.view_as_member_id`),
  `POST` / `DELETE /api/admin/view-as[/{member_id}]` (admin; 404 `not_found`,
  audited `admin.view_as_started` / `admin.view_as_stopped`),
  `SessionRepo.set_view_as`, `deps.active_view_as` / `forbid_view_as`.
  `GET /api/auth/me` now also returns `view_as: {member_id,member_name} | null`.

- **Members can preview a settlement as a DRAFT before it is posted** — after an
  admin freezes a settlement they can click **Del utkast med medlemmer** on the
  settlement page (only shown once the usage snapshot is frozen). Each snapshot
  member then sees their own line of that settlement in a clearly-marked
  "Utkast til avregning" section on "Min konto": an amber panel stating the
  numbers are not final, an `UTKAST` badge per row, and links to the report /
  PDF — which carry a diagonal `UTKAST` watermark across the page. A draft is
  visible to a member **only**
  when it is frozen **and** explicitly shared **and** the member is in its
  snapshot; **Trekk tilbake** clears the share and hides it again. Re-freezing a
  shared draft keeps it shared, so members always see the latest frozen numbers.
  New: migration `0014` (`settlements.draft_shared_at` /
  `draft_shared_by_user_id`), `POST` / `DELETE /api/settlement/{id}/share-draft`
  (admin; 422 `not_frozen` / `not_draft` / `not_shared`, audited
  `settlement.draft_shared` / `settlement.draft_unshared`),
  `SettlementRepo.share_draft` / `unshare_draft` / `shared_draft_for_member`.
  `/api/me/settlements` now also returns shared drafts, each with
  `"is_draft": true`; `/api/me/settlements/{id}/report[.pdf]` and
  `.../invoices/{aid}` accept a shared draft and watermark the report.
- **Currency shown with the `kr` prefix, column-aligned** — every formatted
  amount now reads `kr 1 234,56` instead of `1 234,56 kr`, matching Norwegian
  convention where the currency symbol comes first. Centralised in
  `formatNok`/`formatOre` (frontend) and `settlement_report._nok` (HTML/PDF
  reports); notification email bodies (settlement report, correction,
  low-balance) updated to match. In tables and reports the amount is rendered so
  the `kr` sits a small constant gap left of the digits, which occupy a
  fixed-width right-aligned box — so both the prefix *and* the øre line up down
  the whole column (amounts past ~5 digits just nudge the `kr` left on that
  row). New `<Money>` component (frontend) / `.money` span (reports) carries
  this; every amount column was switched over (movements, member balances,
  ledgers, settlement preview & invoice lines, forecast overview, usage history,
  settlement list). The portal renders every settlement report live
  (`render_member_report`/`render_summary_report` on each request), so it picks
  up the new formatting immediately. The archived copies under
  `state/reports/<period>/` are only rewritten at post time — new
  `python -m ladelaug_avregning regenerate-reports [--settlement ID]`
  (`SettlementRepo.regenerate_reports`) re-renders them for already-posted
  settlements so the archive matches. PDF siblings are rewritten too where
  WeasyPrint is installed.
- **Members can edit their own profile and password** — new "Min profil" page
  (`/min-profil`, in the member nav). `PATCH /api/me` lets a member change their
  own name and contact email (andelsnummer / innmeldingsdato stay admin-only);
  `POST /api/me/password` sets a new password with no current-password prompt —
  the live session is the proof — enforcing a 10-char minimum plus a small
  known-weak blocklist (`security.password_policy_error`, now shared with the
  CLI bootstrap). A successful change revokes every *other* session for the
  login (current device stays signed in), queues a `password_changed` email, and
  writes an `auth.password_changed` audit row.
- **Member dashboard — 6-month usage / cost / balance history** — "Min konto" no
  longer shows only the current month's consumption. New
  `GET /api/me/history?months=6` returns a rolling window ending with the current
  Oslo month: per-month metered kWh + session count (available before any
  settlement), the kr charge for months whose settlement is **posted** (blank
  otherwise — no estimates), and the running ledger balance
  (`LedgerRepo.running_balance_by_month`, `SUM(amount_ore)` grouped on
  `substr(value_date,1,7)`, forward-filled) at each month's end. The dashboard's
  new `UsageHistoryChart` draws one combined chart — grouped kWh/kr bars with the
  balance line on top, a per-month hover tooltip — plus a data table (newest
  month first). Fixes not being able to see last month's usage right after a
  month rollover.
- **Fakturalinjer — focus returns to Beskrivelse after "Legg til"** — on the admin
  settlement page, adding an invoice line (Enter or the button) now puts the
  cursor back in the Beskrivelse field so lines can be entered in a row.
- **Zaptec session sync — last day of the window was dropped** — Zaptec's
  `GET /api/chargehistory` treats `To` as an *exclusive* midnight bound, so the
  monthly sync (which passed `To=<last day of month>`) never imported any
  session on that final day. Confirmed against a production capture on
  2026-09-01: three 2026-08-31 sessions were missing. `ZaptecSync.sync_sessions`
  now advances the caller's inclusive `date_to` by one day
  (`_chargehistory_to`) before calling the client; the recorded
  `sync_runs.window_to` still shows the requested last day. After deploying,
  re-run a sessions sync for any affected month to backfill (and correct the
  settlement if it was already posted).
- **Security review pass** — pinned `forwarded_allow_ips` to
  `server.trusted_proxies` (default `127.0.0.1`; `*` is now rejected) so
  `X-Forwarded-For` can no longer be spoofed to defeat the login rate limiter;
  added `SecurityHeadersMiddleware` (CSP with `frame-ancestors 'none'`,
  `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, and HSTS
  when `cookie_secure`); rate-limited magic-link / password-reset **issuance**
  (`auth.request_max_per_email` / `_per_ip` / `_window_seconds`, migration 0012,
  audited `auth.request_throttled`, still returns `{"ok": true}`); moved the
  magic-link / reset token from the URL query into the URL **fragment** (`#token=`,
  never sent to the server or in `Referer`; `?token=` still accepted as a
  fallback); `_bootstrap_admin` now refuses a short or known-weak password;
  `GET /api/health` no longer returns the version; the `console` mail backend
  redacts tokens in its log line. See `SECURITY-REVIEW.md`.
- **Audit-logging gaps closed** — new events `user.sign_in_blocked`,
  `auth.magic_link_failed`, `auth.password_reset_failed`,
  `user.session_revoked_disabled`, `system.job_triggered`,
  `notifications.queue_processed` / `notifications.email_failed`,
  `zaptec.installation_synced`, and `settlement.report_downloaded` /
  `invoice_downloaded` / `attachment_downloaded`. `audit_events` now also stores
  `user_agent` and `actor_role` (migration 0013). The admin **Revisjonslogg** page
  gained an expandable per-row detail view (before/after `detail`, `ip`,
  `user_agent`, `actor_role`), actor + date-range filters, and a CSV export
  (`GET /api/audit-events/export.csv`). Removed the unused
  `AuditRepo.insert_audit_event` writer. Retention is deliberately indefinite (no
  purge job).
- **Norwegian URL paths** — client routes are now Norwegian and centralised in
  `frontend/src/routes.ts`: `/medlemmer`, `/brukere`, `/ladere`, `/avregninger`,
  `/bevegelser`, `/revisjonslogg`, `/prognose` (`/system` unchanged). The member
  "min side" is the site **root** `/` with no suffix; an admin landing on `/` is
  redirected to `/medlemmer`. `/login` and `/auth/*` stay English. Settlement
  report-notification emails now link to `/` instead of `/my-account`. No legacy
  redirects — old bookmarks resolve to the root.
- **Sign-in links send immediately** — the magic-link and password-reset request
  endpoints now deliver their email on the request itself via
  `NotificationRepo.send_now`, instead of leaving the user to wait up to a
  `drain_mail` interval. Delivery failures are non-fatal: the row stays queued
  and the scheduler retries it as before. New `AppConfig.state_dir` property
  replaces the mail-spool path recomputed in four places.
- **Re-send settlement report emails** — `POST /api/settlement/{id}/resend-reports`
  (admin, `X-Requested-With`, posted settlements only — `422 not_posted`
  otherwise) recomputes the settlement from its frozen snapshot and queues a
  fresh batch of per-member report emails (audited `settlement.reports_resent`).
  Alongside it, `POST /api/notifications/{id}/requeue` puts a single `failed` /
  `sent` message back on the queue — resets its attempt counter, makes it due now
  (audited `notifications.email_requeued`, `422 not_requeueable` for a message
  that is already queued). Both enqueue only; the `drain_mail` job /
  `POST /api/notifications/process` still does the sending. In the UI: a **Send
  rapport-e-post på nytt** button on a posted settlement and a **Legg i kø igjen**
  button per failed row on **System → Systemhelse**.
- **In-process job scheduler** — with `scheduler.enabled: true` the server runs
  the recurring jobs itself: `drain_mail` (`*/10 * * * *`), `low_balance_scan`
  (`0 * * * *`), `zaptec_sync_sessions` (`30 3 * * *`) — no external crontab. One
  job runs at a time on the serving process; missed slots are not replayed (the
  next run recomputes from current state). Per-job on/off and cron live in the
  new `job_schedules` DB table (migration 0011), edited at runtime under
  **System → Bakgrunnsjobber** — `GET /api/system/jobs`, `PUT /api/system/jobs/{name}`
  (audited `system.job_schedule_updated`, `bad_cron` on a bad expression),
  `POST /api/system/jobs/{name}/run` to fire one now. `GET /api/system/health`
  gains `scheduler:{enabled,jobs}` and a failed job flips `ok`. All three jobs
  ship disabled. New `python -m ladelaug_avregning run-job <name>` CLI; the
  existing `drain-mail` / `low-balance-scan` commands stay for current crontabs.
- **Edit user logins** — `PATCH /api/users/{id}` (admin, `X-Requested-With`)
  patches a login's `email`, `role`, and `member_id` (partial body, `422
  validation_error` on an empty one). Promoting a member login to `admin`
  auto-drops the member link; demoting to `member` requires a `member_id`.
  Guards: `email_taken`, `member_linked`, `cannot_demote_self`, `last_admin`.
  The admin *Brukere* page gets an **Endre** button per row opening an edit
  modal alongside the existing "Nytt passord" / activate-toggle actions.
- **Gmail email backend** — `email.backend: gmail` sends through the Gmail REST
  API with an OAuth2 refresh token (scope `gmail.send`), no SMTP or app
  password. Secrets via `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` /
  `GMAIL_REFRESH_TOKEN` (mirrors `ZAPTEC_PASSWORD`); access tokens refresh
  automatically and a 401 forces one re-auth + retry. `gmail_sender` (defaults
  to `from_address`) is the authenticated address / verified alias.
  `scripts/gmail_oauth_bootstrap.py` mints the refresh token once.
- **`drain-mail` CLI** — `python -m ladelaug_avregning drain-mail` sends the
  queued emails (same as `POST /api/notifications/process`), so the cron line no
  longer needs a `curl` with an admin cookie.
- **PDF availability is observable** — the guarded `import weasyprint` now logs
  the failure and keeps the exception string in `reports.pdf.PDF_IMPORT_ERROR`;
  `GET /api/system/health` gains `pdf: {available, error}`. Post-time PDF render
  failures are logged instead of silently swallowed. `scripts/serve-dev.sh` runs
  the dev server with the Homebrew lib path so the `.pdf` endpoints work outside
  Docker on macOS.
- **Member report tidy-up** — the per-member settlement report drops the
  "Fakturert energi" and "Sum belastet alle medlemmer" rows (still in the admin
  summary), shows the member's full name once (the page title now uses the
  member reference, not the name), and the "Avregningsgrunnlag" values sit in a
  right-aligned tabular-figures column so kr/kWh amounts line up regardless of
  digit count. Metered/invoiced kWh use the nb-NO decimal comma like every other
  figure.

## 2026-08-31 — Release 1D: corrections, refunds, departure, access (`0.5.0`)

The correction and exit workflows. Migration `0010` widens
`ledger_transactions.txn_type` with `refund` and `settlement_correction` (table
rebuilt, same pattern as `0005`) and adds `settlement_corrections`,
`settlement_correction_members`, and `charging_access_events`.

- **Refunds (US-505)** — `POST /api/members/{id}/refunds`
  `{amount,value_date?,reference?,allow_negative?}` writes an append-only
  `refund` ledger row (negative `amount_ore`) plus a `ledger.refunded` audit
  event. Refused with `refund_exceeds_balance` (422) when it would take the
  balance below zero unless `allow_negative` is set. New `Refusjon` action on the
  member page; `txnTypeLabel` gains `Refusjon` / `Korrigering`.
- **Settlement corrections (Epic 7 — US-701/702/703)** —
  `SettlementRepo.assess_correction` recomputes a *posted* settlement from the
  month's current imported consumption against its **frozen** invoice lines and
  **frozen** equal-cost participation; `post_correction` books the per-member
  delta as one `settlement_correction` ledger row each (positive = a credit back
  to the member), records a `settlement_corrections` /
  `settlement_correction_members` trail, resolves the month's outstanding
  `late_session_flags`, and audits `settlement.corrected`. The delta is measured
  against what the ledger has already charged for the settlement, so repeated
  corrections never double-count; the original settlement row and its
  allocations are untouched. Endpoints `GET`/`POST
  /api/settlement/{id}/correction` (the `POST` also emails each adjusted member —
  `NotificationRepo.enqueue_correction_reports`, `template=settlement_correction`).
  `GET /api/settlement/{id}` now carries `corrections[]` and, for a posted
  settlement, `correction_pending`. New "Korrigering" panel on the settlement
  page (assess table → confirm → book).
- **Member departure (US-204)** — `MemberRepo.departure_check` previews the open
  charger assignments that would close, any month with the member's consumption
  not yet in a posted settlement, and the balance a refund would pay back.
  `process_departure` sets the status inactive from the leaving date, closes
  every open assignment (re-resolving the affected non-posted months), and —
  when asked and nothing is unsettled (`unsettled_consumption`, 422, otherwise) —
  refunds the whole positive balance. Each step keeps its own audit row; one
  `member.departed` row summarises it. Nothing is deleted. `GET
  /api/members/{id}/departure-check`, `POST /api/members/{id}/departure`; a new
  "Utmelding" card on the member page.
- **Charging-access status (US-305, US-1003/1004)** — `AccessRepo` over
  `charging_access_events` records a `warned` / `disabled` / `restored` intent
  per member, each audited (`access.{action}`); `warned` and `restored` also
  enqueue a Norwegian email carrying the reason and the Zaptec portal link.
  Admin: `GET`/`POST /api/members/{id}/access`. Portal: `GET /api/me/access` →
  `{status, portal_url}` drives a banner + link on "Min konto". New
  `ZaptecConfig.portal_url` (`config.example.yaml`).
  **This is a status of record and a notification only — 1D does not call Zaptec
  to pause or authorise a charger. Live enforcement is Release 2 ("Direct Zaptec
  access control"); an admin acts in the Zaptec portal.**
- **System health** — `GET /api/system/health` gains
  `corrections: {settlements_with_pending}` (posted settlements whose current
  usage no longer matches) and `access: {disabled}` (members whose latest access
  event is `disabled`). Informational — they do not flip `ok`. Two matching
  tiles on the Systemhelse page.

Build plan: `spec/release-1d-plan.md`. 347 pytest + 53 Vitest tests green;
`ruff check` / `ruff format --check` clean; `npm run build` green.

## 2026-08-30 — User provisioning + movements (`0.4.0`)

Admin can now create and manage login accounts from the UI, see balances at a
glance, and record incoming payments from anywhere.

- **User administration** — new `Brukere` page (`/users`, reached from **System**
  alongside `Ladere` — both are configuration, not day-to-day nav) listing every
  login (email, role, linked member, enabled/disabled). `POST /api/users` creates an
  administrator or a member login; `password` is optional — omit it and the
  account activates via magic link / password reset (`users.password_hash` stays
  NULL). `POST /api/users/{id}/disable|enable` (disable revokes the user's
  sessions; guards against disabling yourself or the last active admin) and
  `POST /api/users/{id}/password`. `GET /api/users` lists them. The member
  detail page gains a **Pålogging** card to create/disable/reset that member's
  login inline. `UserRepo.create` now accepts `password=None`.
- **Balance movements list** — new `Bevegelser` page (`/movements`) shows the
  ledger across all members, newest first, filterable by member and transaction
  type. Backed by `GET /api/ledger-transactions?limit=&offset=&member_id=&txn_type=`
  (`LedgerRepo.list_all`, joined to member name/reference).
- **Balances on the member overview** — `GET /api/members` and
  `GET /api/members/{id}` now carry `balance_ore` / `balance_nok`
  (`LedgerRepo.balance_ore_map`); the member table shows a `Saldo` column.
- **Quick "Registrer innbetaling"** — a shared `RecordPaymentModal` (member
  picker, value date prefilled to today) is reachable from a `＋` button on the
  member overview and the movements page, as well as the existing per-member
  ledger card.
- **Settlement report shows the calculation** — the member report
  (`render_member_report`) gains an "Avregningsgrunnlag" section: fixed costs
  (equal-split, with the participant count), consumption costs (kWh-weighted),
  invoiced vs. metered kWh, and totals — plus "Din andel av totalforbruk"
  (the member's kWh as a percentage of the settlement total) and a per-line
  table with both the settlement-wide amount and the member's share. The admin
  summary report gets the same fixed/consumption split.
- **Invoices available to members** — settlements now hold **several** invoice
  files (new `settlement_attachments` table, migration `0009`; the legacy
  `settlements.attachment_*` columns are backfilled and then unused). Admins add
  and delete invoices from the settlement page **in any status** (a confirm
  dialog gates deletion) via `POST /api/settlement/{id}/attachments`,
  `GET|DELETE /api/settlement/{id}/attachments/{aid}`; `GET /api/settlement/{id}`
  now returns an `attachments` list. Members reach each invoice for their posted
  settlements **through the settlement report** (which links every file) via
  `GET /api/me/settlements/{id}/invoices/{aid}` — the invoices are not listed on
  the "Min konto" page itself. New reusable `ConfirmModal` component.

## 2026-08-30 — Charger fixes (`0.3.1`)

Bug-fix batch for chargers and pre-import usage attribution. See
`spec/charger-attribution-fix.md` for the full write-up and the operator
runbook for cleaning up existing data.

- **Zaptec charger serial** — `ZaptecCharger.parse` now maps `serial_no` from
  the hardware `DeviceId` (fallback `SerialNo`), so a synced charger no longer
  shows the same string in "Navn" and "Serienr." `device_id` is threaded into
  `upsert_from_zaptec` and the sync audit detail (no new column). Migration
  `0008_charger_serial_backfill.sql` fixes already-synced rows from
  `raw_json.DeviceId`, leaving hand-corrected serials and manual chargers alone.
- **Charger edit / delete** — `EditChargerModal` wires the existing
  `PATCH /api/chargers/{id}` into the UI. New `DELETE /api/chargers/{id}`:
  hard delete, hand-entered chargers only, refused when the charger has
  imported usage (`charger_has_usage`, 422) or is Zaptec-mirrored
  (`zaptec_charger`, 422); cascades the assignment history; one
  `charger.deleted` audit row. `ChargerOut.deletable` gates the button.
- **Adopt on sync** — `upsert_from_zaptec` adopts a single hand-entered charger
  whose serial matches the incoming `DeviceId` (attaches `zaptec_id`, keeps the
  admin's name, `charger.adopted` audit) instead of creating a duplicate;
  ambiguous matches fall through to a normal insert.
- **Retroactive attribution** — imported charging rows resolve to a local
  `charger_id` (by `zaptec_id`, then by serial / `DeviceId`) rather than
  `zaptec_id` alone, and `import_sessions` / `reresolve_members` backfill
  `charger_id` onto the stored rows. `assign` / `unassign` and `sync_chargers`
  now auto-run `reresolve_after_assignment` / `reresolve_unresolved`, skipping
  months owned by a posted settlement. The assign control gains a back-date
  field; the Chargers page and settlement detail show an unassigned-kWh banner
  with `POST /api/charging/reresolve` ("Kjør ny fordeling").
- **Stale-snapshot guard** — `settlement.compute` / `preview` emit a
  post-blocking `usage_stale` warning when the frozen snapshot no longer
  matches the imported usage (unassigned kWh appeared, or a session changed
  after `usage_frozen_at`); the "Frys på nytt" button is the remedy.
- **Report preview before posting** — the admin settlement page now shows the
  HTML/PDF report links (labelled "forhåndsvisning") as soon as a settlement is
  frozen, not only after it is posted. The `/reports*` endpoints already
  rendered from the frozen snapshot; only the UI gate changed.
- **Live month-consumption panel** — draft settlements show a "Forbruk i
  {måned} (foreløpig)" panel with the running metered total and per-member
  breakdown from `GET /api/charging/consumption`, so an admin sees what will be
  captured before clicking "Frys forbruk".

## 2026-08-30 — Release 1C (`0.3.0`)

Forecasting, the member portal, low-balance warnings, and PDF settlement
reports (deferred from 1B).

- **Forecasting (Epic 8)** — `domain/forecast.py` `ForecastRepo`, a pure
  read-model over posted settlements + the ledger. Per member: `forecast_kwh` =
  trailing mean of the member's `consumption_kwh` over the last
  `lookback_settlements` (default 3) posted settlements they appear in (no
  seasonality — US-801); consumption rate = the admin `rate_override_ore_per_kwh`
  else the mean of `sum(consumption line øre) ÷ grid_kwh` over settlements with
  `grid_kwh > 0` (US-802); equal-cost share = mean equal-line total ÷ participant
  count, counted only when the member currently participates (US-803);
  recommended minimum balance = `forecast_monthly_cost × buffer_months`
  (default 2.0 — US-804). Thin history (fewer postings than the lookback, or no
  positive historical `grid_kwh` and no override) → `available: false` and the
  portal shows a neutral "ikke nok historikk" state. All arithmetic in integer
  øre; the only `Decimal` boundary is `forecast_kwh × rate` (`ROUND_HALF_EVEN`).
- **Forecast settings** — `forecast_settings`, an admin-tunable singleton row
  (seeded by the migration) for the rate override, buffer months, notify
  cooldown, and lookback. `GET` / `PUT /api/forecast/settings` (admin; each
  write is one `forecast.settings_updated` audit row with before/after) and
  `GET /api/forecast/members` (overview). No new `config.yaml` block — the
  tunables live in the DB so an admin changes them from the UI without a redeploy.
- **Member portal (Epic 9)** — `GET /api/me/forecast` (US-903) and
  `GET /api/me/consumption?month=` (current-month metered kWh + session count
  before any settlement exists — US-902). `MyAccount` gains a forecast card, a
  current-month consumption line, and a severity-coloured low-balance banner;
  each settlement-history row gets a PDF link (US-904). New admin
  `/forecast` page (rate override + a "run low-balance scan now" button + a
  per-member overview).
- **Low-balance warnings (US-805)** — `NotificationRepo.scan_low_balances`
  enqueues a Norwegian warning email for every member below their recommended
  minimum, writing one `low_balance_notifications` history row (linked to the
  queued message) and one `notifications.low_balance_warned` audit event.
  Duplicate suppression: re-send only when there is no prior row within
  `notify_cooldown_days`, OR the balance dropped ≥ 1 kr since the last row, OR
  the severity escalated `low → critical`. `POST /api/notifications/low-balance-scan`
  (admin) and a `low-balance-scan` CLI subcommand — wire to cron, then drain
  the queue with `POST /api/notifications/process`. `GET /api/system/health`
  gains `low_balance: {warned_total, members_below}`.
- **PDF reports (US-906)** — WeasyPrint renders the existing self-contained HTML
  report. `GET /api/settlement/{id}/reports/{member_id}.pdf` /
  `.../reports/summary.pdf` (admin) and `GET /api/me/settlements/{id}/report.pdf`
  (member). `write_reports` also drops `.pdf` siblings under
  `state/reports/<month>/` at post time. WeasyPrint dlopen's Pango/cairo/GObject
  at import; when those native libraries are missing the app still runs and the
  `.pdf` endpoints return `503 pdf_unavailable`. The runtime Docker image
  installs the libraries.
- **Member HTML report** — the 1B "Prognose og anbefalt innbetaling kommer i en
  senere versjon" placeholder is replaced by a real "Prognose neste måned" +
  "Anbefalt saldo / innbetaling" section (US-905), computed after the ledger
  rows land so the balances match.

Schema: migration `0007` — `forecast_settings` + `low_balance_notifications`.
New dependency: `weasyprint`. Backend 233 → 272 pytest tests (+1 skipped where
WeasyPrint's native libs are absent); frontend 24 → 30 Vitest tests.

Deferred to 1D: corrections, refunds, member departure, charging-access
workflows.

The per-phase entries below record how it was built.

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

## 2026-08-30 — Web UI: member portal + forecast admin (Release 1C phase P6)

- `frontend/` — `MyAccount.tsx` gains a severity-coloured low-balance banner
  (rose = `critical`, amber = `low`, shown only when `forecast.available &&
  forecast.low_balance`), a "Prognose neste måned" card (forecast kWh, estimated
  monthly cost, recommended minimum balance, recommended top-up — or a neutral
  "Ikke nok historikk …" when `available` is false), and a current-month
  consumption line from `GET /api/me/consumption`. Each settlement-history row
  gets a "PDF" link (`${report_url}.pdf`) beside "Rapport".
- New `pages/ForecastSettings.tsx` at `/forecast` (admin-only, nav link
  "Prognose" beside "System"): edit `rate_override_ore_per_kwh` (empty clears
  it), `buffer_months`, `notify_cooldown_days`, `lookback_settlements` via
  `PUT /api/forecast/settings`; a "Kjør lavsaldo-varsling nå" button hitting
  `POST /api/notifications/low-balance-scan` and rendering the
  scanned/below/queued/suppressed counts; a member overview table from
  `GET /api/forecast/members` (names joined from `GET /api/members`) with a
  severity badge.
- `api/client.ts` — `getMyForecast`, `getMyConsumption`, `getForecastSettings`,
  `updateForecastSettings`, `getForecastMembers`, `runLowBalanceScan` plus the
  `MemberForecast` / `MemberConsumption` / `ForecastSettings` /
  `ForecastSettingsUpdate` / `LowBalanceScanResult` types. `lib/format.ts` gains
  `formatOre` (integer øre → `"1 500,00 kr"`).
- MSW handlers + Vitest for all of the above; `frontend/CLAUDE.md` contract
  section extended.

## 2026-08-30 — Forecast section in member report (Release 1C phase P5)

- `render_member_report(result, member, forecast=None)` — the 1B placeholder
  footer ("Prognose og anbefalt innbetaling kommer i en senere versjon") is
  replaced by a real "Prognose neste måned" (forecast kWh, estimated monthly
  cost) + "Anbefalt saldo / innbetaling" (recommended balance, and
  `max(0, recommended_minimum_ore − balance_ore)` as "Anbefalt innbetaling for å
  nå anbefalt saldo") section when a forecast dict is supplied and
  `available`. Without one, a short neutral footer stands in — no placeholder
  promise (decision C10).
- `write_reports(result, members, out_dir, forecasts=None)` threads a
  `{member_id: forecast_dict}` map to each member's report.
- `SettlementRepo.post` builds those forecasts via `ForecastRepo.member_forecast`
  *after* the ledger rows are written (so `balance_ore` reflects the just-posted
  charge) and passes them to `write_reports`, wrapped best-effort like the
  existing report write.
- The on-demand report endpoints (`GET /api/settlement/{id}/reports/{member_id}`
  + `.pdf`, `GET /api/me/settlements/{id}/report` + `.pdf`) compute a fresh
  forecast and render the section too.

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
