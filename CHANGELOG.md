# Changelog

Newest entries on top. Dates are ISO (YYYY-MM-DD).

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
