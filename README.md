# ladelaug-avregning

A web portal for a Norwegian EV-charging co-op ("ladelaug"). Members hold a
**prepaid balance**; each month the shared electricity invoice is **settled**
("avregning") across members — part as an equal share of fixed costs, part by
metered kWh. The portal keeps an **append-only financial ledger** and an
**append-only audit log**, and (from Release 1B) imports consumption from Zaptec,
runs the settlement, and produces per-member reports. Release 1C adds a member
portal with a consumption forecast, low-balance warning emails, and PDF reports.

## Status — Release 1C (`0.3.1`)

Release 1A was the foundation (identity, members, the append-only ledger,
audit). Release 1B turned a monthly electricity invoice into per-member charges
(chargers, Zaptec sync, the settlement engine, HTML reports, email). Release 1C
gives members a forward view and finishes the reporting.

`0.3.1` is a charger bug-fix batch: synced chargers store the hardware serial
(`DeviceId`) rather than a name duplicate, admins can edit and delete
hand-entered chargers, Zaptec sync adopts a matching manual charger instead of
duplicating it, and usage imported before its charger or assignment existed is
attributed retroactively (with an unassigned-kWh banner and a "re-run
allocation" action). See `spec/charger-attribution-fix.md`.

- **Forecasting** — a trailing-mean forecast (last 3 posted settlements, no
  seasonality) of each member's next-month kWh and cost, a recommended minimum
  balance (`cost × buffer_months`, default 2), and a recommended top-up.
  Tunables (`rate_override_ore_per_kwh`, `buffer_months`, `notify_cooldown_days`,
  `lookback_settlements`) live in a DB row an admin edits at `/forecast` — no
  redeploy. `GET /api/me/forecast`, `GET /api/forecast/settings|members`.
- **Current-month consumption** — `GET /api/me/consumption?month=` shows metered
  kWh + session count for the running month, before any settlement exists.
- **Low-balance warnings** — `POST /api/notifications/low-balance-scan` (or the
  `low-balance-scan` CLI) enqueues a warning email for every member below their
  recommended minimum, with cooldown / balance-drop / `low→critical` escalation
  suppression so cron can run it hourly. A dashboard banner shows the same.
- **PDF reports** — WeasyPrint renders the settlement report to PDF:
  `GET /api/settlement/{id}/reports/{member_id}.pdf`, `.../summary.pdf`,
  `GET /api/me/settlements/{id}/report.pdf`; `.pdf` siblings are also written
  under `state/reports/<month>/` at post time. The report's forecast section
  ("Prognose neste måned", "Anbefalt innbetaling") is now filled in.
- **System health** — `GET /api/system/health` also reports
  `low_balance: {warned_total, members_below}`.

<details><summary>Release 1B (<code>0.2.0</code>)</summary>

Release 1A was the foundation (identity, members, the append-only ledger,
audit). Release 1B adds the machinery that turns a monthly electricity invoice
into per-member charges.

- **Chargers** — records (hand-entered or mirrored from Zaptec) and
  effective-dated charger→member assignments (one open per charger; a member
  may hold several at once).
- **Zaptec integration** — import chargers, archived charging sessions, and
  15-minute interval data; idempotent; sessions that cross a month boundary are
  split (interval data first, pro-rata by duration otherwise). Consumption on a
  charger with no assignment is *unassigned* and blocks the settlement until
  resolved. Config-gated by `zaptec.enabled`.
- **Settlement engine** — one settlement per calendar month:
  `draft → freeze → preview → post`. Freeze snapshots participation,
  consumption, and balance-before. Invoice lines are split *equally* (across
  participants) or *by consumption* (by kWh share); rounding is deterministic
  and total-preserving. Preview shows warnings (negative balances, missing
  invoice kWh / attachment, zero consumption, late sessions). Post writes one
  immutable `settlement_charge` ledger row per member and is idempotent. An
  invoice PDF must be attached before posting.
- **Reports** — a self-contained HTML report per member plus a summary, saved
  under `state/reports/<month>/` and served to admins and to the member.
- **Email** — a queued sender with retry/backoff (`console` / `file` / `smtp`
  backends). Posting a settlement queues a report email per member.
- **Passwordless sign-in & password reset** — single-use expiring links; the
  request endpoints never disclose whether an account exists.
- **System health** — `GET /api/system/health`: Zaptec sync state, email queue
  stats, failed jobs, versions.

</details>

**Not in 1C** (planned): corrections / refunds / member departure /
charging-access workflows (1D).

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
python -m ladelaug_avregning serve            # run the HTTP server (default)
python -m ladelaug_avregning migrate          # apply DB migrations and exit
python -m ladelaug_avregning create-admin --email <e> [--password <p>]
python -m ladelaug_avregning low-balance-scan  # enqueue low-balance warning emails (cron)
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
| `zaptec.enabled` | `false` | gate for all Zaptec sync endpoints (503 while off) |
| `zaptec.username` | — | Zaptec login; password via `ZAPTEC_PASSWORD` env |
| `zaptec.installation_id` | — | optional; blank syncs every visible installation |
| `zaptec.page_size` / `zaptec.max_retries` | `500` / `3` | |
| `email.backend` | `console` | `console` (log) / `file` (`state/mail/*.eml`) / `smtp` |
| `email.from_address` / `email.base_url` | — | sender + public origin for links in emails |
| `email.smtp_host` / `smtp_port` / `smtp_username` / `smtp_password` / `smtp_starttls` | — | used when `backend: smtp` |
| `email.magic_link_ttl_minutes` / `password_reset_ttl_minutes` | `30` / `60` | |

**Forecast tunables are not in `config.yaml`** — `rate_override_ore_per_kwh`
(blank = derive from history), `buffer_months` (`2.0`), `notify_cooldown_days`
(`14`), and `lookback_settlements` (`3`) live in the `forecast_settings` DB row
and are edited by an admin at `/forecast` (or `PUT /api/forecast/settings`), so
they change without a restart.

### Zaptec + settlement workflow

1. Set `zaptec.*` and `export ZAPTEC_PASSWORD=…` (or put it in `.env`). Verify
   the API shape first with `uv run python scripts/probe_zaptec.py` (throwaway).
2. `POST /api/zaptec/sync/chargers`, then assign each charger to a member
   (Ladere screen).
3. `POST /api/zaptec/sync/sessions?month=YYYY-MM` to import that month's
   charging. Resolve any unassigned consumption, then re-import or
   `POST /api/charging/reresolve?month=YYYY-MM`.
4. Create a settlement draft for the month, add invoice lines (equal /
   consumption), set the invoiced kWh, upload the invoice PDF.
5. **Freeze** (snapshots participation + usage), **Preview** (check the
   warnings and per-member impact), then **Post**. Posting is irreversible and
   writes the ledger charges + HTML reports and queues the report emails.
6. Drain the email queue: `POST /api/notifications/process` — run it from cron,
   e.g. `*/10 * * * * curl -fsS -X POST -H 'X-Requested-With: fetch' --cookie …`
   or a small authenticated script. A monthly session sync can be scheduled the
   same way.
7. Low-balance warnings: `python -m ladelaug_avregning low-balance-scan` (or
   `POST /api/notifications/low-balance-scan`) enqueues a warning email for each
   member below their recommended minimum balance. Safe to run hourly — the
   cooldown / balance-drop / severity-escalation rule suppresses repeats. Follow
   it with the queue drain in step 6.

### Reports

- `GET /api/settlement/{id}/reports/{member_id}` (HTML) / `…/{member_id}.pdf`
  (PDF, admin), `…/reports/summary` / `…/summary.pdf`.
- `GET /api/me/settlements/{id}/report` / `…/report.pdf` (the member's own).
- PDF needs WeasyPrint's native libraries (bundled in the Docker image; see
  Deploy). Without them the HTML endpoints work and the `.pdf` ones return
  `503 pdf_unavailable`.

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
(and its `-wal` / `-shm` sidecars), plus `attachments/` (invoice PDFs),
`reports/` (generated settlement HTML **and PDF**), and `mail/` (`.eml` files
when `email.backend: file`). One `state/` volume covers all of it.

The runtime image installs WeasyPrint's native dependencies (Pango, HarfBuzz,
cairo, DejaVu fonts) so the PDF report endpoints work out of the box. Running
the app outside Docker without those system libraries is supported — the app
starts and the `.pdf` endpoints return `503 pdf_unavailable` while HTML reports
keep working.

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
