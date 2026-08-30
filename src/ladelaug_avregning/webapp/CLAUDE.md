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
