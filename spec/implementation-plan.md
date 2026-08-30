# Implementation Plan — `ladelaug-avregning` (EV Charging Co-op Portal)

Product requirements are in [`spec.md`](./spec.md). This document is the **build
plan**: architecture decisions, the Release 1A work breakdown (with what actually
shipped), and a sketch of Releases 1B–1D. It is kept for the settlement-engine
work that starts in 1B.

---

## Status — 2026-08-30

**Release 1A is COMPLETE** (`0.1.0`). Identity, member administration, the
financial ledger, audit, member self-service, and a bundled React SPA.

**Release 1B is COMPLETE** (`0.2.0`) — charger management, Zaptec sync, the
settlement engine, HTML reports, the email queue, passwordless sign-in /
password reset, and system health. Work breakdown and decisions:
[`release-1b-plan.md`](./release-1b-plan.md). Migrations `0002`–`0006`;
233 pytest tests + 24 Vitest tests green.

| Phase | Scope | State | Commit |
|---|---|---|---|
| **A** | Scaffold + cross-cutting infra | ✅ done | `29d9755` |
| **B** | Identity (Epic 1) | ✅ done | `70fe3e3` |
| **C** | Member administration (Epic 2) | ✅ done | `4fb7e13` |
| **D** | *Charger management (Epic 3)* | — moved to 1B (decision #3) | — |
| **E** | Ledger foundation (Epic 5) | ✅ done | *(uncommitted at time of writing)* |
| **F** | Member self-service API | ✅ done | *(uncommitted)* |
| **G** | Frontend (G1–G4) | ✅ done | *(uncommitted)* |
| **H** | Release (docs, deploy, SPA serving) | ✅ done | *(uncommitted)* |

**Verification at close of 1A**

- Backend: `ruff check` + `ruff format --check` clean; **145 pytest tests pass**.
- Frontend: `npm run check` (tsc strict + eslint + **20 Vitest/MSW tests**, 7 files)
  and `npm run build` both green; SPA builds to `frontend/dist`.
- Full-stack manual smoke (server serving the built SPA): all 10 steps of the
  master smoke path below pass — including the append-only trigger and member
  data-scoping (`GET /api/members` as a member → 403).

Version stays `0.1.0` (`VERSION` + `pyproject.toml` in lockstep).
`scripts/tag_release.sh --dry-run` → `v0.1.0` once E–H are committed.

---

## Context

The portal is a prepaid-balance and monthly-settlement system for a Norwegian
EV-charging co-op ("ladelaug"). `spec.md` is product-only (11 epics, two roles,
a 4-release plan). The stack decision (made at planning time) was to mirror the
sibling repo `ynab-auto-sync` — the closest domain analog (immutable financial
ledger, deterministic rounding, append-only audit table, SQLite, FastAPI + a
static React SPA, `uv`).

This plan detailed **Release 1A** as executable work items and sketched 1B–1D.

## Decisions locked

| # | Decision | Note |
|---|---|---|
| 1 | **Stack mirrors ynab-auto-sync** | Python 3.12, FastAPI, Pydantic v2 (plain `BaseModel`, not pydantic-settings), uvicorn, SQLite WAL + `asyncio.Lock`, `uv`, pytest + pytest-asyncio (`asyncio_mode=auto`) + respx, ruff (line 100, py312, `ignore=["B008"]`), hatchling, `src/` layout. Frontend: React 18 + Vite 5 + TS strict + Tailwind 3, SWR, Vitest + Testing Library + MSW, built to `frontend/dist` and served by FastAPI at `/` **last**. |
| 2 | **Auth = server-side sessions** | Opaque 256-bit cookie token, `sha256` stored in a `sessions` table; instant revocation on logout / user-disable / expiry. argon2id via `argon2-cffi`. CSRF: `SameSite=Lax` + require `X-Requested-With: fetch` header on all mutations. No JWT. |
| 3 | **Release 1A = P0 only, Epic 3 deferred** | 1A ships US-101, US-104, US-201–203, US-501–504, US-1101–1103. **Epic 3 (charger management) moves entirely to 1B** with the live Zaptec sync — so there is **no Phase D** in 1A. Also deferred: US-102 magic-link + US-103 password reset → start of 1B (need email); US-204 departure + US-305 access status → 1D; US-505 refunds → 1D. |
| 4 | **Frontend uses `react-router`** | Nested routes + guards + URL params; scales into the Epic 9 portal. |
| 5 | Money canonical unit = **integer øre** (signed; `+` raises balance) + companion exact `amount_nok` TEXT (`Decimal` string). Both derived from one `Decimal` in `money.py` at write time. `ROUND_HALF_EVEN`, never `Decimal(float)`. |
| 6 | Effective-dating at **DATE** granularity (Europe/Oslo calendar day), half-open ranges `[effective_from, effective_to)`, `effective_to IS NULL` = open. |
| 7 | Versioned migrations: `migrations/NNNN_*.sql` + a `schema_migrations` table + a small forward-only runner in `migrations.py`, run synchronously in `Database.__init__` before the app serves. |
| 8 | `VERSION` file at repo root = single source of truth, kept in lockstep with `pyproject.toml` `version`. CI uses `astral-sh/setup-uv` + `uv sync` + `uv run` (commit `uv.lock`). |
| 9 | Immutability enforced two ways on `ledger_transactions` and `audit_events`: no update/delete repo methods **and** `BEFORE UPDATE/DELETE` SQLite triggers. Audit events kept **forever** (no prune job). |
| 10 | One login `user` per `member` (`users.member_id` unique, nullable — NULL = pure admin). Emails stored lower-cased, unique case-insensitive. Single uvicorn worker (rate-limit + lock assume it). |
| 11 | Include 1B deps (`httpx`, `tenacity`, `croniter`, `workalendar`, `tzdata`) in `pyproject.toml` now for a stable lock; unused in 1A. |
| 12 | `LICENSE` = MIT, ghcr image public. |

---

## Task 0 — model-pinned subagents ✅

`.claude/agents/{coder,code-scout,patcher}.md` created (mirror `ynab-auto-sync`,
with project context): **`coder`** (sonnet) for features/domain logic/migrations,
**`code-scout`** (haiku) read-only search, **`patcher`** (haiku) small edits and
doc touch-ups.

## Repo scaffold ✅

Python package `ladelaug_avregning`; distribution `ladelaug-avregning`; HTTP port
`8080`; runtime state in `state/` (gitignored). As-built layout:

```
ladelaug-avregning/
├── pyproject.toml  VERSION (0.1.0)  README.md  CHANGELOG.md  LICENSE
├── .gitignore  .dockerignore  .env.example  .python-version (3.12)
├── Dockerfile  docker-compose.yml  uv.lock
├── .github/workflows/{ci.yml, docker-publish.yml}
├── config/config.example.yaml
├── deploy/swag/ladelaug-avregning.subdomain.conf          # added in Phase H
├── migrations/0001_initial.sql
├── scripts/tag_release.sh
├── spec/{spec.md, implementation-plan.md}
├── src/ladelaug_avregning/
│   ├── __init__.py  __main__.py  config.py  logging_setup.py
│   ├── clock.py            # NEW vs plan — single "now" source, freezable in tests
│   ├── db.py  migrations.py  money.py  errors.py  audit.py  security.py
│   ├── domain/             # pure logic + repos, no FastAPI imports
│   │   ├── audit_repo.py  users.py  sessions.py  rate_limit.py
│   │   ├── members.py      # MemberRepo: records + status + participation
│   │   └── ledger.py       # LedgerRepo
│   └── webapp/
│       ├── app.py          # create_app(); SPAStaticFiles fallback (Phase H)
│       ├── deps.py         # get_db/get_config/get_current_user/get_audit_context/
│       │                   #   require_fetch/require_admin/get_current_member
│       ├── schemas.py      # shared pydantic request/response models
│       ├── CLAUDE.md       # HTTP-layer API contract
│       └── routes/{health,auth,audit,members,settlement,ledger,me}.py
├── tests/
│   ├── conftest.py         # db/config/client fixtures; seed_*_sync; make_member;
│   │                       #   make_session; admin_client/member_client; frozen_now
│   └── unit/test_*.py      # 17 modules, 145 tests
└── frontend/
    ├── package.json  vite.config.ts  tsconfig.json  (single flat config —
    │                 project references removed; see deviations)
    ├── tailwind/postcss/eslint configs  index.html  .gitignore
    └── src/
        ├── main.tsx  App.tsx  index.css  router.tsx  vite-env.d.ts
        ├── api/client.ts            # typed fetch wrappers + ApiError
        ├── auth/AuthContext.tsx     # SWR /api/auth/me
        ├── lib/format.ts            # formatNok / formatDate / formatDateTime / txnTypeLabel
        ├── components/{Table,Modal,DateField,StatTile}.tsx
        ├── pages/{Login,Members,MemberDetail,AuditLog,MyAccount}.tsx (+ .test.tsx)
        └── test/{setup.ts, handlers.ts, utils.tsx}   # MSW server + renderApp
```

**`pyproject.toml`** deps as decided (#11 pre-included 1B deps).
**`config/config.example.yaml`** — `server{host,port,static_dir}`, `database.path`,
`timezone`, `logging.level`, `auth{secret_key, session_ttl_hours: 720,
cookie_secure, cookie_name, login_max_attempts: 5, login_window_seconds: 900,
argon2_*}`, `bootstrap_admin{email, password}`. `AppConfig` validators fail fast
with a joined error string; `auth.secret_key` required (via `LADELAUG_SECRET_KEY`
env or the file) or the app refuses to start.

---

## Data model — `migrations/0001_initial.sql` ✅ (frozen; unchanged since it landed)

Timestamps: ISO-8601 UTC TEXT. Effective dates: `YYYY-MM-DD` TEXT. All money:
`amount_ore` INTEGER (signed) + `amount_nok` TEXT.

- **`schema_migrations`** `(version INTEGER PK, applied_at TEXT)`.
- **`users`** `id, email, email_normalized (UNIQUE), password_hash (nullable),
  role CHECK IN ('admin','member'), disabled INT DEFAULT 0,
  member_id INT REFERENCES members(id), password_changed_at, created_at, updated_at`.
  Partial `UNIQUE INDEX ON users(member_id) WHERE member_id IS NOT NULL`.
- **`sessions`** `id TEXT PK (= sha256(token) hex), user_id, created_at, expires_at,
  last_seen_at, revoked_at, ip, user_agent`. Indexes on `user_id`, `expires_at`.
- **`login_attempts`** `id, email_normalized, ip, occurred_at, succeeded`. Index
  `(email_normalized, ip, occurred_at)`. Opportunistic sweep of rows older than 24h on login.
- **`members`** `id, member_reference (UNIQUE), full_name, email, join_date DATE,
  created_at, updated_at`.
- **`member_status_periods`** `id, member_id, status CHECK IN ('active','inactive'),
  effective_from DATE, effective_to DATE NULL, note, created_at, created_by_user_id`.
  Partial `UNIQUE INDEX idx_msp_one_open ... WHERE effective_to IS NULL` (one open period).
- **`settlement_participation`** `id, member_id, participates INT, effective_from DATE,
  effective_to DATE NULL, reason, created_at, created_by_user_id`. Same partial unique index (`idx_sp_one_open`).
- **`ledger_transactions`** — append-only. `id, member_id, txn_type CHECK IN
  ('payment','payment_reversal','adjustment_credit','adjustment_debit'), amount_ore INT,
  amount_nok TEXT, currency DEFAULT 'NOK', value_date DATE, reason, reference,
  reverses_transaction_id REFERENCES ledger_transactions(id), created_by_user_id,
  recorded_at`. `INDEX (member_id, id)`; partial `UNIQUE INDEX idx_ledger_one_reversal
  ON reverses_transaction_id WHERE NOT NULL`. `BEFORE UPDATE`/`BEFORE DELETE`
  triggers → `RAISE(ABORT, 'ledger_transactions is append-only')`.
- **`audit_events`** — append-only. `id, occurred_at, actor_user_id REFERENCES
  users(id), actor_label TEXT, event_type, entity_type, entity_id TEXT, summary,
  detail_json TEXT, ip`. Indexes: `(occurred_at DESC)`, `(event_type, occurred_at
  DESC)`, `(entity_type, entity_id)`, `(actor_user_id, occurred_at DESC)`. Same
  append-only triggers.

**Invariants (all enforced in code as planned):** disabled user cannot
authenticate (`get_current_user` re-checks every request + disabling revokes all
sessions); one open effective-dated row per member/participation (partial unique
index + repo closes the open row under the write lock, rejecting `effective_from`
earlier than the current open row); `balance(member)` is **never stored** — always
`SELECT COALESCE(SUM(amount_ore),0)`; reversal amount = `-original.amount_ore` and
original must be a `payment`, reversed at most once; adjustments require a
non-empty `reason`; `amount_ore` and `amount_nok` never drift (one `Decimal`
source); every mutation writes exactly one `audit_events` row in the same
transaction.

## Migration mechanism (`migrations.py`) ✅

`run_migrations(conn, dir)`: create `schema_migrations` if absent; apply each
`NNNN_*.sql` not yet applied inside one transaction; record version + timestamp.
Forward-only. Runs synchronously in `Database.__init__` before `create_app`.
`python -m ladelaug_avregning migrate` runs the same function. `0001_initial.sql`
is frozen — every later schema change is a new file. **No migration was needed
for Phases B–H** (the 1A schema was complete in `0001`).

## Auth approach ✅

- **Password hashing**: argon2id (`argon2-cffi`) — `security.py`: `hash_password`,
  `verify_password`, `needs_rehash` (transparent upgrade on next successful login),
  `new_session_token`, `hash_token` (sha256), `constant_time_eq`. Params
  config-driven.
- **Session cookie**: `secrets.token_urlsafe(32)` → `Set-Cookie:
  ladelaug_session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=…`
  (`Secure` off only via `auth.cookie_secure`). Server stores `sha256(token)`.
  Sliding expiry throttled to once / 5 min. Logout and user-disable revoke.
- **CSRF**: `SameSite=Lax` + every `POST/PATCH/DELETE` must carry
  `X-Requested-With: fetch` (dep `require_fetch` → 403 `csrf`). Frontend
  `api/client.ts` always sends it.
- **Rate limiting** (`domain/rate_limit.py`): count `login_attempts` for
  `(email_normalized, ip)` within the window; at `>= login_max_attempts` with the
  most recent a failure → `429` + `Retry-After` **before** any argon2 work. Every
  attempt writes a row; success/failure also write `user.signed_in` /
  `user.sign_in_failed` audit events.
- **RBAC** (`webapp/deps.py`): `get_current_user` (cookie → sha256 →
  `SessionRepo.get_valid` → load user → `401` + revoke if disabled → throttled
  `last_seen_at` bump); `require_admin` (`403`); `get_current_member` (`403` if
  `member_id is None`). Admin routers declare
  `APIRouter(dependencies=[Depends(require_admin)])`.
- **"Members see only their own data"**: no member-callable `/api/members/*`.
  Member data served **only** from `routes/me.py` under `/api/me/*`, each handler
  resolving the member id from `Depends(get_current_member)` — never a
  path/query param. `test_me_scoping.py` proves member A can't read member B.

## Cross-cutting infra (built in Phase A) ✅

1. **`db.py` `Database`** — one `sqlite3.Connection` (`check_same_thread=False`,
   `Row` factory, WAL, `busy_timeout=5000`, `foreign_keys=ON`); runs migrations in
   `__init__`; `asyncio.Lock`; `async with self._write() as cur:` acquires the
   lock, yields a cursor, commits / rolls back. Reads hit the connection directly.
   Repo classes live in `domain/`.
2. **`audit.py`** — `AuditContext(actor_user_id, actor_label, ip)` +
   `AuditContext.system()`.
   - `write_audit_row(cur, ctx, *, event_type, entity_type, entity_id, summary,
     detail=None)` — **synchronous, lock-free**, runs on a cursor the caller
     already holds. *This helper is a deviation from the plan (see notes): the
     plan's `record_audit` opens its own `_write()`, and `asyncio.Lock` is not
     reentrant, so a repo inside `_write()` cannot call it.*
   - `record_audit(db, ctx, ...)` — async, opens its own `_write()`; kept for
     stand-alone events (e.g. failed login) with no accompanying mutation.
3. **`tests/conftest.py`** — `config`, `db`, `client` (`TestClient(create_app(...))`,
   shares the `db` file); `seed_user_sync` / `seed_member_sync` / `make_member` /
   `make_session` (throwaway `Database` on the same path so the app connection's
   lock is never bound to a short-lived loop); `admin_client` / `member_client`
   (preset session cookie); `frozen_now` (monkeypatches `clock.now_utc`).
4. **Error shape** — every error `{"detail": {"code": "...", "message": "..."}}` +
   status (`DomainError`→422, `AuthError`→401/403, `NotFoundError`→404,
   `RateLimitError`→429). `register_exception_handlers(app)` also maps
   `RequestValidationError` → 422 `{code: "validation_error", ...}` *(deviation —
   added in Phase C so body-validation errors match the contract)* and uncaught →
   `500` generic.
5. **Money** — `money.py` (`parse_nok`, `nok_to_ore`, `ore_to_nok`) is the only
   `Decimal`↔`int` boundary. First real caller is `LedgerRepo` (Phase E).
6. **Version** — `VERSION` → `__init__.__version__` → `/api/health` +
   `/api/auth/me` → frontend footer.

---

## Ordered work items — Release 1A

Each item was one reviewable commit (Conventional Commits + `Co-Authored-By:
Claude`; user runs `git commit`). Behaviour-changing items touched `CHANGELOG.md`.
An item is done when `uv run ruff check` + `uv run pytest -q` (and `npm run
check`) pass.

### Phase A — scaffold & cross-cutting infra ✅ (`29d9755`)

A0 subagents · A1 scaffold + tooling · A2 `config.py` + example · A3 `db.py` +
`migrations.py` + `0001_initial.sql` + `conftest` · A4 `errors.py` + `create_app`
(health only) + `deps.py` + `routes/health.py` · A5 `money.py` · A6 `audit.py` +
`AuditRepo` · A7 `security.py`. All tests as specified.

### Phase B — identity (Epic 1) ✅ (`70fe3e3`)

- **B1** — `domain/users.py` `UserRepo` (`create`, `get_by_email`, `get`,
  `set_disabled`, `set_password`, `list`) + `__main__.py` `create-admin` +
  `_bootstrap_admin` (first-run admin when `users` empty). *US-101 (partial),
  US-104 (foundation), US-1101.*
- **B2** — `domain/sessions.py` `SessionRepo` + `domain/rate_limit.py`
  `LoginRateLimiter` + `routes/auth.py` (`POST /api/auth/login|logout`,
  `GET /api/auth/me`) + `deps.py` (`get_current_user`, `get_audit_context`,
  `require_fetch`). Transparent argon2 rehash, sliding expiry, revoke-on-logout,
  429-before-argon2. *US-101 complete.*
- **B3** — `deps.py` `require_admin` + `get_current_member`. *US-104.*
- **B4** — `routes/audit.py` (`GET /api/audit-events` with
  `event_type`/`entity_type`/`entity_id`/`limit`/`offset`/`sort_by`/`sort_dir`;
  `GET /api/audit-events/{id}`), router-level `require_admin`. *US-1101/1102/1103
  read path.*
- Prereqs added here: **`clock.py`** and **`audit.write_audit_row`** (deviations).

### Phase C — member administration (Epic 2) ✅ (`4fb7e13`)

- **C1** — `domain/members.py` `MemberRepo` (`create`, `get`, `list`, `update`
  with before/after audit detail) + `routes/members.py`
  (`POST/GET/PATCH /api/members`, `GET /api/members/{id}`) + `schemas.py`
  (`MemberIn/Patch/Out` with email + date validators). Prereq: the
  `RequestValidationError` → uniform 422 handler. *US-201.*
- **C2** — `MemberRepo.set_status` / `status_history` / `status_map` /
  `current_status` / `active_member_ids(on_date)` + `POST
  /api/members/{id}/status`, `GET .../status-history`. Close-open-row-then-insert
  under the write lock; reject back-dating and no-op changes; `member.status_changed`
  audit; `MemberOut` gains computed `status`. Shared `_replace_open_period`
  helper (deviation — reused for participation). *US-202.*
- **C3** — `set_participation` / `participation_history` /
  `suggested_participants(on_date)` (active members, explicit row wins else
  default-include) / `consumption_cost_recipients` (all active — excluded members
  still get consumption costs) + `POST /api/members/{id}/participation`, `GET
  .../participation-history`, and **`routes/settlement.py`** `GET
  /api/settlement/suggested-participants`. `MemberOut` gains `participates`.
  Code + CHANGELOG note: the 1B engine must **snapshot**
  `settlement_participation` at post time. *US-203.*

### Phase D — *(none; Epic 3 charger management → Release 1B, decision #3)*

### Phase E — ledger foundation (Epic 5) ✅ *(uncommitted)*

- **E1** — `domain/ledger.py` `LedgerRepo`:
  - `record_payment(*, member_id, amount: Decimal, value_date, reference, actor)`
  - `reverse_payment(*, txn_id, actor)` — original must be `txn_type='payment'`
    (`not_a_payment`), not already reversed (`already_reversed`, DB index as
    backstop); reversal `amount_ore = -original.amount_ore`.
  - `adjust(*, member_id, direction: 'credit'|'debit', amount, reason, reference,
    actor)` — non-empty `reason` (`reason_required`), positive `amount`
    (`bad_amount`); `credit` → `+`, `debit` → `-`.
  - `balance(member_id) -> Decimal` (`SUM(amount_ore)` → `ore_to_nok`).
  - `list(member_id, *, limit, offset) -> (rows, total)` newest-first.
  - Helper `_ore_nok(ore)` derives `(amount_ore, amount_nok)` from one value.
  - Every method: one `ledger_transactions` INSERT + one `audit_events` row in
    the same `_write()`; no update/delete methods. Audit event types
    `ledger.payment_recorded` / `ledger.adjusted` / `ledger.payment_reversed`,
    `entity_type="ledger_transaction"`.
- `routes/ledger.py` (no router prefix — mirrors `routes/audit.py`; router-level
  `require_admin`, per-write `require_fetch`): `GET /api/members/{id}/balance`,
  `GET /api/members/{id}/ledger`, `POST /api/members/{id}/payments`,
  `POST /api/members/{id}/adjustments`, `POST /api/ledger-transactions/{id}/reverse`.
- `schemas.py`: `PaymentIn` / `AdjustmentIn` (amount through `parse_nok`, must be
  `> 0`), `LedgerTxnOut`, `BalanceOut`.
- `tests/unit/test_ledger.py` — repo + route + RBAC + append-only trigger.
  *US-501/502/503/504, US-1102. Refunds (US-505) stay in 1D.*

### Phase F — member self-service API ✅ *(uncommitted)*

- **F1** — `routes/me.py`: `GET /api/me`, `/api/me/balance`, `/api/me/ledger`,
  `/api/me/status` — every handler `member_id = Depends(get_current_member)`, no
  path/query id. `test_me_scoping.py`: member A can't see member B; pure admin →
  `403`; anon → `401`; `/api/me/balance` matches `LedgerRepo.balance`;
  `/api/me/ledger` is exactly member A's rows. *US-104, US-501 (member-facing).*

### Phase G — frontend ✅ *(uncommitted)*

React 18 + Vite 5 + TS strict + Tailwind 3 + `react-router-dom` v6 + SWR;
Vitest + Testing Library + MSW. `npm run check` = `tsc --noEmit && eslint .
&& vitest run`. Built to `frontend/dist`.

- **G1** — scaffold + auth shell: all config, `main.tsx`/`App.tsx`/`index.css`,
  `router.tsx` (`<RequireAuth>` → `/login` on 401; `<RequireAdmin>` → `/my-account`
  for members), `api/client.ts` (typed wrappers for **every** endpoint + `ApiError`
  from `detail.code`/`message`, `X-Requested-With` on writes, `credentials:
  "include"`), `auth/AuthContext.tsx` (SWR `/api/auth/me`), `pages/Login.tsx`,
  `lib/format.ts`, `test/{setup.ts, handlers.ts (full MSW mock of the API),
  utils.tsx (renderApp)}`. Tests: `Login`, `AuthContext`, `client`.
- **G2** — admin members: `pages/Members.tsx` (list + create modal),
  `pages/MemberDetail.tsx` (profile edit; status timeline + change form with
  effective date; participation toggle + history); `components/{Table,Modal,
  DateField}.tsx`. Tests: create → in list; invalid email → inline 422; status
  change → new timeline entry; participation persists; member session redirected.
- **G3** — admin ledger + audit log: `MemberDetail.tsx` gains a balance
  `StatTile`, a ledger `Table`, and "Registrer innbetaling" / "Manuell justering"
  (reason required — submit disabled while blank) / per-payment-row "Reverser"
  modals; `pages/AuditLog.tsx` (paginated table, filter by `event_type` /
  `entity_type`, `counts` summary, manual "Oppdater" — not live). Tests: payment →
  balance + row; reverse → reversal row + balance moves back; empty-reason submit
  disabled; audit filter + pagination.
- **G4** — member portal: `pages/MyAccount.tsx` (balance `StatTile`, my-ledger
  table, my-status block — all from `/api/me/*`; clear empty state if the account
  has no linked member). Layout: `role=member` lands on `/my-account` with no admin
  nav; `role=admin` has no "Min konto" link. Tests: member session renders
  balance + ledger; admin layout hides the portal nav.

**20 Vitest tests across 7 files; `npm run build` produces `dist/`.**

### Phase H — release ✅ *(uncommitted)*

- **H1** — full `README.md` (setup, `create-admin` / `bootstrap_admin`, config
  reference table, Docker/ghcr deploy, the `X-Forwarded-Proto` reverse-proxy
  caveat, backup = copy `state/`, release process); `deploy/swag/
  ladelaug-avregning.subdomain.conf`; consolidated "Release 1A" `CHANGELOG` entry
  above the per-phase entries; `VERSION`/`pyproject` confirmed `0.1.0`.
- **SPA serving** — `webapp/app.py` `SPAStaticFiles` subclass: a GET that would
  404 (a client-side route like `/members/3` on hard refresh) returns
  `index.html`; `/api/*` is untouched (routes registered first; unmatched `api/`
  paths still get a JSON 404). `test_static_spa.py` covers it. *(Deviation — the
  plan said plain `StaticFiles(html=True)`, which does not fall back for nested
  client routes.)*

---

## Deviations from the original plan

1. **`src/ladelaug_avregning/clock.py`** (new) — `now_utc()` / `today_oslo()`.
   The plan had modules call `datetime.now(UTC)` directly and freeze via
   monkeypatching `datetime.now`. A single indirection is cleaner and is what
   `frozen_now` patches; `today_oslo().isoformat()` is the source for
   effective-date defaults.
2. **`audit.write_audit_row(cur, ...)`** (new) — the plan's `record_audit` opens
   its own `db._write()`. `asyncio.Lock` is **not reentrant**, so a repo already
   holding `_write()` deadlocks if it calls `record_audit`. `write_audit_row` is
   the lock-free, same-cursor variant used by every repo mutation;
   `record_audit` is kept for stand-alone events.
3. **`MemberRepo._replace_open_period(cur, ...)`** — a shared helper for the
   "close the open effective-dated row, insert a new open one, reject
   back-dating / no-op" logic, used by both `set_status` and `set_participation`
   (the plan described the logic twice).
4. **Uniform 422 for request-body validation** — `errors.py` now handles
   `fastapi.exceptions.RequestValidationError` → `{"detail": {"code":
   "validation_error", "message": "..."}}`. Without it, pydantic body errors
   returned FastAPI's default array shape, breaking the documented contract.
5. **`SPAStaticFiles`** — SPA client-route fallback (see Phase H above).
6. **`frontend/tsconfig.json`** is a single flat config (`"include": ["src",
   "vite.config.ts"]`), not the Vite-template split `tsconfig.json` +
   `tsconfig.node.json` project references — TS 5.6 rejects `noEmit` on a
   referenced composite project, and a flat config type-checks everything in one
   `tsc --noEmit` pass with no friction.
7. **`routes/settlement.py`** is its own module (`prefix="/api/settlement"`) — the
   plan folded `suggested-participants` into `routes/members.py`. A dedicated
   module is where the 1B settlement engine will grow.
8. **`make_member` conftest fixture** — added so status/participation/ledger tests
   can create a real member (with its audit row) without going through HTTP.
9. Commits: E, F, G, H were built and verified but left **uncommitted** at the
   user's request. Suggested split when committing: `feat(ledger)`,
   `feat(api): member self-service`, `feat(web): Release 1A frontend`,
   `feat(web): SPA fallback`, `docs: Release 1A`.

---

## Releases 1B–1D (sketch — unchanged)

- **1B — Zaptec + settlement engine.** **First task: a throwaway
  `scripts/probe_zaptec.py`** against the real installation to verify the
  archived-session endpoint, pagination, and 15-min interval-data shape before any
  adapter is designed. Then: `zaptec` adapter (`httpx` + `tenacity`); **Epic 3
  charger management** (deferred from 1A — `chargers` + `charger_assignments`
  tables via `0002_*.sql`, idempotent `upsert_from_zaptec`, effective-dated
  non-overlapping assignments, US-303 multi-charger, US-304 unassigned-consumption
  detection blocking settlement); Epic 4 (session/interval import, cross-month
  split US-405, late-session detection US-406); Epic 6 settlement engine (draft →
  freeze usage snapshot → invoice lines → equal-cost + consumption allocation →
  deterministic residual-øre rounding → preview → post = ledger entries +
  reports); Epic 10 email (also unblocks US-102/103); PDF reports. Depends on 1A
  ledger + members + participation (**snapshot `settlement_participation` at post
  time**).
- **1C — Member portal + forecasting.** Epic 8 (forecast from last 3 settlement
  months, no seasonality; admin rate override; recommended minimum balance;
  low-balance warning email + dashboard with duplicate suppression), Epic 9
  dashboard/history/PDF download, US-1104 system health. Depends on 1B settlements.
- **1D — Corrections, refunds, departure, access.** Epic 7 (assess/calculate/post
  correction as adjustment transactions, original preserved, members notified),
  US-505 refunds, US-204 member departure (end-status + end-assignments +
  unsettled detection + refund), US-305 charging-access status with real Zaptec
  enforcement.

---

## Verification

**Backend**
```
uv sync --extra dev
uv run ruff check src tests scripts
uv run ruff format --check
uv run pytest -q                       # 145 passed
```
**Frontend**
```
cd frontend && npm install && npm run check && npm run build   # 20 tests; dist/ built
```
**Run prod-like**: `cd frontend && npm run build && cd .. && uv run python -m
ladelaug_avregning serve` (API + built SPA on :8080). **Docker**: `docker build
-t ladelaug-avregning:dev . && docker compose up`.

**Manual smoke path (all green at close of 1A)**
1. `create-admin` prints success; a second run → "email already exists".
2. Sign in as admin → `Set-Cookie: ladelaug_session=…; HttpOnly` present; lands
   on Members. Hard-refresh on `/members/42` → SPA loads (not 404).
3. New member `Kari Nordmann`, ref `A-07`, join date → appears in list.
4. Set status `active` from a date → timeline shows one open period;
   `/api/settlement/suggested-participants` lists `A-07`.
5. Record payment `1500.00` NOK → ledger `+1 500,00`, balance `1 500,00`.
6. Manual adjustment debit `50.00`, reason "korrigering" → balance `1 450,00`;
   empty reason → `validation_error`.
7. Reverse the `1500` payment → reversal row `-1 500,00`, balance `-50,00`;
   reversing again → `already_reversed`.
8. Log in as Kari (member) → `/api/me/balance` `-50,00`, `/api/me/ledger` 3 rows;
   `GET /api/members` → `403`.
9. Back as admin → Audit Log (newest first): `user.signed_in`, `member.created`,
   `member.status_changed`, `ledger.payment_recorded`, `ledger.adjusted`,
   `ledger.payment_reversed`, each with actor + timestamp + amount/summary;
   filter `entity_type=ledger_transaction` narrows to the three financial rows.
10. `sqlite3 state/ladelaug.db "UPDATE ledger_transactions SET amount_ore=0 WHERE
    id=1;"` → `Error: ledger_transactions is append-only`.

## Residual risks (carried into 1B)

- **Effective-dated write races** — mitigated by the single `asyncio.Lock` +
  partial unique index on the open row; back-dated inserts get an explicit range
  check inside the lock.
- **Cookie `Secure` behind the reverse proxy** — `uvicorn.run(...,
  proxy_headers=True, forwarded_allow_ips="*")`; the proxy must send
  `X-Forwarded-Proto: https` (documented in `README.md` + `deploy/`).
- **Disabling a user must kill live sessions** — `UserRepo.set_disabled` revokes
  all sessions in the same transaction; `get_current_user` re-checks `disabled`
  every request anyway.
- **argon2 CPU on a low-power box** — params config-driven; the rate-limit check
  runs before hashing; benchmark on the target box and tune.
- **`amount_ore` / `amount_nok` drift** — both from one value via `_ore_nok`; a
  test asserts `ore_to_nok(row.amount_ore) == Decimal(row.amount_nok)` across a mix.
- **Migration crash mid-file** — each file runs inside one transaction (SQLite DDL
  is transactional).
- **Frontend/backend contract drift** — MSW handlers written against the shapes
  the pytest suite asserts; `frontend/src/test/handlers.ts` + `frontend/CLAUDE.md`
  document the contract.
- **`settlement_participation` not yet snapshotted** — 1A stores the live wish
  only; the 1B settlement engine MUST snapshot it at post time.
