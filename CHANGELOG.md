# Changelog

Newest entries on top. Dates are ISO (YYYY-MM-DD).

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
