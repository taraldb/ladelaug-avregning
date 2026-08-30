# ladelaug-avregning

A web portal for a Norwegian EV-charging co-op ("ladelaug"). Members hold a
**prepaid balance**; each month the shared electricity invoice is **settled**
("avregning") across members — part as an equal share of fixed costs, part by
metered kWh. The portal keeps an **append-only financial ledger** and an
**append-only audit log**, and (from Release 1B) imports consumption from Zaptec,
runs the settlement, and produces per-member reports.

## Status — Release 1A

Release 1A is the foundation: identity, members, the ledger, and audit.

- **Identity & access** — email + password sign-in, server-side sessions
  (opaque cookie, argon2id, sliding expiry, instant revocation), login rate
  limiting, and role-based access (admin vs. member). Members only ever see
  their own data.
- **Member administration** — member records; effective-dated active/inactive
  status with full history; settlement-participation decisions (who is in the
  equal-cost split; excluded members still get consumption costs).
- **Financial ledger** — record payments, reverse a mistaken payment
  (equal-and-opposite row, once), manual credit/debit adjustments (reason
  required). Balance is always the sum of the append-only rows, never stored.
  Money is integer øre canonical with an exact companion decimal string.
- **Audit** — every mutation writes one audit event in the same transaction;
  admins get a filtered, paginated audit view.
- **Web UI** — a bundled React SPA served by the app: admin screens for members,
  status, participation, the ledger, and the audit log; a member "My account"
  view.

**Not in 1A** (planned): Zaptec sync and the settlement engine (1B), the member
forecasting portal and low-balance warnings (1C), corrections / refunds / member
departure / charging-access workflows (1D).

## Stack

- **Backend** — Python 3.12, FastAPI, Pydantic v2, SQLite (WAL), `uv`. One
  process, one writer serialised behind an `asyncio.Lock`; versioned SQL
  migrations run at startup.
- **Frontend** — React 18 + Vite + TypeScript + Tailwind + React Router + SWR,
  built to `frontend/dist` and served by the FastAPI app at `/`.

## Quick start (development)

```sh
# backend
uv sync --extra dev
cp config/config.example.yaml config/config.yaml          # then edit
export LADELAUG_SECRET_KEY=$(openssl rand -hex 32)        # or put it in .env
#   for plain-HTTP localhost, set auth.cookie_secure: false in config.yaml
uv run python -m ladelaug_avregning migrate
uv run python -m ladelaug_avregning create-admin --email admin@example.com --password 'a-strong-password'
uv run python -m ladelaug_avregning serve                 # http://localhost:8080

# frontend (separate terminal; proxies /api to :8080)
cd frontend
npm install
npm run dev                                               # http://localhost:5173
```

Production-like (SPA built and served by the API on one port):

```sh
cd frontend && npm run build && cd ..
uv run python -m ladelaug_avregning serve                 # serves the API + the built SPA on :8080
```

### Checks

```sh
uv run ruff check src tests scripts
uv run ruff format --check
uv run pytest -q
cd frontend && npm run check          # tsc --noEmit + eslint + vitest
```

## CLI

```
python -m ladelaug_avregning serve          # run the HTTP server (default)
python -m ladelaug_avregning migrate        # apply DB migrations and exit
python -m ladelaug_avregning create-admin --email <e> [--password <p>]
```

`create-admin` is idempotent-ish: a second run with an existing email exits
non-zero with a clear message. Alternatively set `bootstrap_admin.email` /
`bootstrap_admin.password` in `config.yaml` and the first startup with an empty
`users` table creates that admin automatically.

## Configuration

`config/config.yaml` (copy from `config/config.example.yaml`; gitignored). The
only secret is `auth.secret_key`, which is normally left blank in the file and
supplied via the `LADELAUG_SECRET_KEY` environment variable (or a `.env` file) —
**the app refuses to start if it is neither set nor in the file.**

| key | default | notes |
|---|---|---|
| `server.host` / `server.port` | `0.0.0.0` / `8080` | |
| `server.static_dir` | `frontend/dist` | built SPA; served at `/` when the directory exists |
| `database.path` | `state/ladelaug.db` | SQLite file (WAL) |
| `timezone` | `Europe/Oslo` | calendar day used for effective-dated rows |
| `logging.level` | `INFO` | `DEBUG`..`CRITICAL` |
| `auth.secret_key` | — | **required**; via `LADELAUG_SECRET_KEY` env is preferred |
| `auth.session_ttl_hours` | `720` | 30 days, sliding on activity |
| `auth.cookie_secure` | `true` | set `false` only for plain-HTTP localhost |
| `auth.cookie_name` | `ladelaug_session` | |
| `auth.login_max_attempts` / `auth.login_window_seconds` | `5` / `900` | rate limit per (email, IP) |
| `auth.argon2_time_cost` / `argon2_memory_cost_kib` / `argon2_parallelism` | `3` / `65536` / `2` | tune down for a low-power host |
| `bootstrap_admin.email` / `bootstrap_admin.password` | — | optional first-run admin |

## Deploy (Docker)

Images are published to `ghcr.io/taraldb/ladelaug-avregning` on pushes to `main`
and on tags. The image builds the frontend and bundles it.

```sh
docker run -d --name ladelaug-avregning \
  -p 8080:8080 \
  -e LADELAUG_SECRET_KEY=your-random-hex \
  -v /host/ladelaug/config:/app/config \
  -v /host/ladelaug/state:/app/state \
  ghcr.io/taraldb/ladelaug-avregning:latest
```

Put `config.yaml` in the mounted `config/` volume. `state/` holds the SQLite DB
(and its `-wal` / `-shm` sidecars).

**Behind a reverse proxy** (nginx / SWAG / Traefik / Caddy): the app runs uvicorn
with `proxy_headers=True` and `forwarded_allow_ips="*"`, so it honours
`X-Forwarded-Proto`. Your proxy **must** send `X-Forwarded-Proto: https` on TLS
requests, otherwise the `Secure` session cookie is set on a connection the
browser considers insecure and login appears to "not stick". A sample SWAG
config is in `deploy/swag/ladelaug-avregning.subdomain.conf`.

`docker-compose.yml` in the repo is for local development (`build: .`); for a
host, run the published image as above.

### Backup

Stop the container (or accept a slightly fuzzy copy) and copy the whole `state/`
directory — `ladelaug.db` plus any `ladelaug.db-wal` / `ladelaug.db-shm`. That is
the entire persistent state. Restore = put the files back and start.

## Releasing

`VERSION` at the repo root is the single source of truth, kept in lockstep with
`pyproject.toml`. `scripts/tag_release.sh --dry-run` shows the tag it would
create (`v<VERSION>`); drop `--dry-run` to create it, add `--push` to push.
