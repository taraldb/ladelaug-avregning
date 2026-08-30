# ladelaug-avregning

EV charging co-op ("ladelaug") portal: prepaid member balances, monthly settlement of the
shared electricity invoice, and an append-only financial ledger + audit log.

**Status:** Release 1A in progress. Done: identity & authentication (password sign-in,
server-side sessions, RBAC, admin audit-log API). Next: member administration and the ledger
foundation. Charger management and Zaptec integration land in Release 1B.

## Stack

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLite (WAL), `uv`.
- Frontend: React 18 + Vite + TypeScript + Tailwind, built to `frontend/dist` and served by
  the FastAPI app.
- Money is handled as `Decimal` (integer øre canonical); the ledger and audit tables are
  append-only.

## Development

```sh
uv sync --extra dev
uv run ruff check src tests scripts
uv run ruff format --check
uv run pytest -q
```

Run locally:

```sh
cp config/config.example.yaml config/config.yaml
export LADELAUG_SECRET_KEY=$(openssl rand -hex 32)   # or put it in .env; set cookie_secure: false for plain HTTP
uv run python -m ladelaug_avregning migrate
uv run python -m ladelaug_avregning --config config/config.yaml create-admin \
    --email admin@example.com --password changeme123
uv run python -m ladelaug_avregning serve            # http://localhost:8080
```

Instead of `create-admin`, set `bootstrap_admin.email` / `bootstrap_admin.password` in
`config.yaml` to create the first administrator automatically on startup (only while the
`users` table is empty).

Frontend dev server (proxies `/api` to `:8080`):

```sh
cd frontend && npm install && npm run dev
```
