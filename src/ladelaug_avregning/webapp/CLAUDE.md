# HTTP layer — API contract

- **Error shape.** Every error response is `{"detail": {"code": "<machine>", "message": "<human>"}}`
  with a status matching the exception (`DomainError` 422, `AuthError` 401/403, `NotFoundError`
  404, `RateLimitError` 429 + `Retry-After`). Raise the `errors.py` types; never hand-roll a
  `JSONResponse`.

- **CSRF.** Every mutating request (`POST`/`PATCH`/`DELETE`) must carry
  `X-Requested-With: fetch`. Mount `Depends(require_fetch)` on the route (or router). The
  frontend `api/client.ts` always sends it; a browser cannot set it cross-origin without a
  preflight these endpoints do not grant. Pairs with `SameSite=Lax` on the session cookie.

- **Auth & roles.** `get_current_user` resolves the `ladelaug_session` cookie and re-checks
  `disabled` on every request. Admin routers declare
  `APIRouter(dependencies=[Depends(require_admin)])` so new admin endpoints are gated by
  construction. Member-facing data is served **only** from `/api/me/*` (Phase F), each handler
  taking `member_id = Depends(get_current_member)` — never a path/query id. Members self-edit
  via `PATCH /api/me` (`MemberRepo.update`, name + email only) and `POST /api/me/password`
  (`UserRepo.set_password` + `SessionRepo.revoke_all_for_user_except` keeping the current
  token + a `password_changed` email + `auth.password_changed` audit; no current-password
  check). Password rules live in `security.password_policy_error` (length + a known-weak
  blocklist), shared with the `__main__` bootstrap.

- **Audit.** Every mutation writes exactly one `audit_events` row. Inside a repo that already
  holds `db._write()`, use `audit.write_audit_row(cur, ...)` (lock-free); for a stand-alone
  event use `await audit.record_audit(db, ...)`. `asyncio.Lock` is not reentrant.
  `audit.py` is the only writer — `AuditRepo` is read-only. `AuditContext` also carries
  `ip` / `user_agent` / `actor_role`, filled by `deps.get_audit_context` from the request +
  session. The table is append-only (triggers) and retained **indefinitely** — there is no
  purge job by design; add a windowed archive if storage ever matters.

- **Users.** `routes/users.py` (`/api/users`, `require_admin`) provisions logins via
  `UserRepo`. `POST` accepts `password=None` (activation-only account, NULL hash).
  `disable` re-checks `cannot_disable_self` / `last_admin` in the route before calling
  `UserRepo.set_disabled` (which revokes the user's sessions in-transaction).
  `PATCH /api/users/{id}` -> `UserRepo.update` (partial `email`/`role`/`member_id`,
  diff-then-`UPDATE`, `user.updated` audit). The route resolves the effective
  role/member_id against the current row, auto-nulls `member_id` on promotion to
  admin, and enforces `cannot_demote_self` / `last_admin` / the member-link
  consistency rules before the repo call; `email` changes also rewrite
  `email_normalized`. Role is read fresh per request (`deps.get_current_user`), so
  a demotion takes effect on the next request without a session revoke.

- **Ledger.** `LedgerRepo.list_all` is the cross-member movements read
  (`GET /api/ledger-transactions`, admin); `balance_ore_map` feeds the `balance_ore` /
  `balance_nok` fields on `MemberOut` for the member list/detail routes. Live balance is
  still `SUM(amount_ore)` — never stored. `running_balance_by_month` returns the
  cumulative balance at each month's end (grouped on `substr(value_date,1,7)`), forward-
  filled by the caller — feeds the dashboard's `GET /api/me/history`.

- **Settlement invoices.** A settlement has many `settlement_attachments` rows
  (migration 0009; legacy `settlements.attachment_*` columns are dead). `SettlementRepo`
  `add_attachment` / `remove_attachment` work in **any** status — invoices can be
  fixed after posting — and only `attachments()` being empty blocks `post()` and
  raises the `attachment_missing` compute warning. Files live at
  `state/attachments/<settlement_id>/<attachment_id>-<name>`. Admin CRUD is on
  `/api/settlement/{id}/attachments[...]`; members read their posted settlements'
  invoices via `/api/me/settlements/{id}/invoices/{aid}`.

- **Shared drafts (member preview).** `POST` / `DELETE
  /api/settlement/{id}/share-draft` set / clear `settlements.draft_shared_at`
  (migration 0014) via `SettlementRepo.share_draft` / `unshare_draft` (422
  `not_frozen` / `not_draft` / `not_shared`; audited `settlement.draft_shared` /
  `settlement.draft_unshared`). `shared_draft_for_member` returns a member's
  frozen + shared + in-snapshot drafts. `/api/me/settlements` adds them with
  `is_draft:true`; `_my_settlement_or_403` returns `(row, is_draft)` and the
  member report endpoints pass `draft=is_draft` into `render_member_report`,
  which then renders a diagonal `UTKAST` page watermark + `UTKAST –` title
  prefix (no in-body banner/heading marker). `member_entry`
  / `compute` already work on any frozen settlement, so no posting is needed.
  Re-freezing a shared draft keeps it shared.

- **Forecast (1C).** `ForecastRepo` is a pure read-model — it computes from posted settlements
  + the ledger and persists nothing except the `forecast_settings` singleton (audited via
  `update_settings`) and the `low_balance_notifications` history rows. Member-facing:
  `/api/me/forecast`, `/api/me/consumption`, `/api/me/history` (rolling N-month strip:
  per-month kWh + posted-settlement charge + month-end running balance). Admin: `/api/forecast/settings` (GET/PUT),
  `/api/forecast/members`. Money in `MemberForecastOut` is canonical integer øre; the object
  is always fully populated (`available: false` → zeros + a `reason`).

- **Background jobs.** A `scheduler.SchedulerRunner` task is started from the `create_app`
  lifespan only when `config.scheduler.enabled`; it reuses `app.state.db` (same event loop
  → same write `asyncio.Lock`). It reads the `job_schedules` table (migration 0011) each
  tick and runs each enabled job whose `next_run_at` passed — sequentially, and `next_run_at`
  is always recomputed forward (no catch-up). Job bodies live in `scheduler/jobs.py` and only
  wrap existing coroutines (`NotificationRepo.process_queue` / `.scan_low_balances`,
  `ZaptecSync.sync_sessions`). Admin surface on the `system` router: `GET /api/system/jobs`,
  `PUT /api/system/jobs/{name}` (`+require_fetch`, `JobScheduleRepo.update` — audited
  `system.job_schedule_updated`, `bad_cron` on an invalid expr), `POST /api/system/jobs/{name}/run`.
  `mark_started` / `mark_finished` are deliberately **unaudited**. `GET /api/system/health`
  carries `scheduler: {enabled, jobs}` and folds a job in `last_status='error'` into
  `failed_jobs` / `ok`.

- **PDF (1C).** `reports.pdf.PDF_AVAILABLE` is set by a guarded `import weasyprint` (its
  native libs may be absent). `html_to_pdf` raises `DomainError("pdf_unavailable", status=503)`
  when unavailable; the `.pdf` report routes let that propagate. Never import `weasyprint` at
  module top level outside `reports/pdf.py`.

- **Refunds (1D).** `POST /api/members/{id}/refunds` → `LedgerRepo.refund` inserts a `refund`
  row (negative `amount_ore`) + `ledger.refunded`. `refund_exceeds_balance` (422) unless
  `allow_negative`. `txn_type` CHECK widened in migration `0010` (`refund`,
  `settlement_correction`).

- **Settlement corrections (1D, Epic 7).** `SettlementRepo.assess_correction` (posted only,
  422 `not_posted`) recomputes from *current* `ChargingRepo.consumption_by_member` against the
  frozen `settlement_invoice_lines` + frozen `participates_equal`; `delta_ore = charged_ore −
  corrected_charge_ore` where `charged_ore` is `−SUM(amount_ore)` over the settlement's ledger
  rows (so a 2nd correction nets against the 1st). `post_correction` writes one
  `settlement_correction` ledger row per non-zero delta + a `settlement_corrections` /
  `settlement_correction_members` record, resolves the month's `late_session_flags`, audits
  `settlement.corrected`. Routes `GET`/`POST /api/settlement/{id}/correction`; the `POST`
  calls `NotificationRepo.enqueue_correction_reports`. `_detail()` adds `corrections` and
  `correction_pending`.

- **Re-send / re-queue emails.** `POST /api/settlement/{id}/resend-reports`
  (`+require_fetch`, posted only → 422 `not_posted`) reuses `SettlementRepo.compute`
  + `NotificationRepo.enqueue_settlement_reports` to append a fresh batch of `queued`
  `settlement_report` rows (no dedup — a repeat call adds another batch), then a
  stand-alone `record_audit("settlement.reports_resent")`. `POST
  /api/notifications/{id}/requeue` (`+require_fetch`) → `NotificationRepo.requeue`:
  a `failed`/`sent` row goes back to `status='queued'`, `attempts=0`,
  `last_error=NULL`, `sent_at=NULL`, `next_attempt_at=now`, with an in-transaction
  `notifications.email_requeued` audit row; an already-`queued` row is 422
  `not_requeueable`, unknown id 404. Both endpoints only enqueue — `process_queue`
  still does the sending. **Exception:** the `/api/auth/magic-link` and
  `/api/auth/password-reset/request` handlers call `NotificationRepo.send_now`
  right after `enqueue` (via `_deliver_now`, building a sender from
  `config.state_dir`) so the link goes out on the request; a send failure there
  is swallowed and the row is left queued for the scheduler.

- **Member departure (1D, US-204).** `MemberRepo.departure_check` /
  `process_departure` orchestrate `set_status('inactive')` + `ChargerRepo.unassign` per open
  assignment (+ `reresolve_after_assignment`) + an optional `LedgerRepo.refund` of the whole
  positive balance, refused (`unsettled_consumption`, 422) while any month ≤ the leaving date
  has the member's sessions outside a posted settlement. One stand-alone `member.departed`
  audit row via `record_audit`. Routes on the members router.

- **Charging access (1D, US-305).** `domain/access.py` `AccessRepo` over
  `charging_access_events`; `routes/access.py` (its own `require_admin` router,
  `prefix="/api/members"`, registered right after `members`) — `GET`/`POST
  /api/members/{id}/access`. `record()` does one `_write()` that inserts the `email_messages`
  row (for `warned`/`restored` only), the event, and the `access.{action}` audit row (the
  low-balance pattern). Portal: `GET /api/me/access` → `{status, portal_url}`
  (`config.zaptec.portal_url`). **No Zaptec write call — status of record only.** Health adds
  `access: {disabled}` + `corrections: {settlements_with_pending}` (informational).
