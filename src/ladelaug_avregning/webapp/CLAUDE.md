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
  taking `member_id = Depends(get_current_member)` — never a path/query id.

- **Audit.** Every mutation writes exactly one `audit_events` row. Inside a repo that already
  holds `db._write()`, use `audit.write_audit_row(cur, ...)` (lock-free); for a stand-alone
  event use `await audit.record_audit(db, ...)`. `asyncio.Lock` is not reentrant.

- **Users.** `routes/users.py` (`/api/users`, `require_admin`) provisions logins via
  `UserRepo`. `POST` accepts `password=None` (activation-only account, NULL hash).
  `disable` re-checks `cannot_disable_self` / `last_admin` in the route before calling
  `UserRepo.set_disabled` (which revokes the user's sessions in-transaction).

- **Ledger.** `LedgerRepo.list_all` is the cross-member movements read
  (`GET /api/ledger-transactions`, admin); `balance_ore_map` feeds the `balance_ore` /
  `balance_nok` fields on `MemberOut` for the member list/detail routes. Live balance is
  still `SUM(amount_ore)` — never stored.

- **Settlement invoices.** A settlement has many `settlement_attachments` rows
  (migration 0009; legacy `settlements.attachment_*` columns are dead). `SettlementRepo`
  `add_attachment` / `remove_attachment` work in **any** status — invoices can be
  fixed after posting — and only `attachments()` being empty blocks `post()` and
  raises the `attachment_missing` compute warning. Files live at
  `state/attachments/<settlement_id>/<attachment_id>-<name>`. Admin CRUD is on
  `/api/settlement/{id}/attachments[...]`; members read their posted settlements'
  invoices via `/api/me/settlements/{id}/invoices/{aid}`.

- **Forecast (1C).** `ForecastRepo` is a pure read-model — it computes from posted settlements
  + the ledger and persists nothing except the `forecast_settings` singleton (audited via
  `update_settings`) and the `low_balance_notifications` history rows. Member-facing:
  `/api/me/forecast`, `/api/me/consumption`. Admin: `/api/forecast/settings` (GET/PUT),
  `/api/forecast/members`. Money in `MemberForecastOut` is canonical integer øre; the object
  is always fully populated (`available: false` → zeros + a `reason`).

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
