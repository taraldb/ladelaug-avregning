# Release 1C — build plan

Product scope (`spec.md` Release 1C): **Member portal, Forecasting, Low-balance
warnings** — plus **PDF settlement reports (US-906)**, the one explicit deferral
from Release 1B.

Architecture and prior decisions: [`implementation-plan.md`](./implementation-plan.md),
[`release-1b-plan.md`](./release-1b-plan.md). This document is the executable
build plan for 1C.

Target version: **`0.3.0`** (`VERSION` + `pyproject.toml` in lockstep).

## Status — IN PROGRESS (planning done 2026-08-30)

| Phase | Scope | State | Commit |
|---|---|---|---|
| **P1** | Forecast engine (`domain/forecast.py`, `0007` settings) | ☑ done | `194e846` |
| **P2** | Forecast + consumption API (`/api/forecast/*`, `/api/me/forecast`, `/api/me/consumption`) | ☑ done | `4a5a965` |
| **P3** | Low-balance warnings (`0007` history table, scan job, CLI, health) | ☑ done | `e132cdf` |
| **P4** | PDF settlement reports (WeasyPrint) | ☐ not started | — |
| **P5** | Forecast section in the member HTML report | ☐ not started | — |
| **P6** | Web UI — member portal dashboard + forecast admin | ☐ not started | — |
| **P7** | Docs / version bump `0.3.0` | ☐ not started | — |

**Done** = `uv run ruff check` + `uv run ruff format --check` + `uv run pytest -q`
green (and `npm run check` from P6). Behaviour-changing items touch
`CHANGELOG.md`.

---

## Scope by user story

| US | Title | 1C work |
|---|---|---|
| US-801 | Forecast usage | Trailing mean of the member's consumption over the last ≤3 posted settlements; no seasonality. |
| US-802 | Forecast pricing | Consumption rate derived from historical settlements; admin override in `forecast_settings`. |
| US-803 | Estimate equal-cost share | Mean equal-line total ÷ participant count over the last ≤3 posted settlements. |
| US-804 | Recommended minimum balance | `forecast_monthly_cost × buffer_months` (default 2.0). |
| US-805 | Low-balance warning | Email + dashboard banner; duplicate suppression via `low_balance_notifications` + cooldown / escalation rule. |
| US-901 | Account summary | `MyAccount` gains a forecast card (balance already there). |
| US-902 | View consumption | `GET /api/me/consumption?month=` — current-month metered kWh before any settlement exists. |
| US-903 | View estimated costs | `GET /api/me/forecast` — forecast cost breakdown (equal + consumption). |
| US-904 | Settlement history | Already shipped in 1B (`/api/me/settlements`); 1C adds the PDF link. |
| US-905 | Settlement reports | Fill the 1B "Prognose / anbefalt innbetaling" stub in `render_member_report`. |
| US-906 | PDF download | WeasyPrint renders the existing HTML report; admin + member `.pdf` endpoints; best-effort PDF files at post time. |
| US-1104 | System health | Extend the existing health payload with low-balance counters. |

---

## Decisions locked for 1C

| # | Decision | Note |
|---|---|---|
| C1 | **Forecast model = trailing mean over the last N posted settlements** (`forecast_settings.lookback_settlements`, default 3), no seasonality (US-801). Per member: mean of `settlement_members.consumption_kwh` across the ≤N most recent posted settlements the member appears in. Zero postings for that member → `available: false`. | `domain/forecast.py`. |
| C2 | **Forecast consumption rate** (øre/kWh) is derived per historical settlement as `sum(consumption invoice-line amount_ore) ÷ grid_kwh`, then averaged over the last ≤N posted settlements with `grid_kwh > 0`. `forecast_settings.rate_override_ore_per_kwh` (admin, US-802) replaces the derived rate when set. If no settlement has a positive `grid_kwh` **and** no override → `available: false`. | `Decimal` for the kWh×rate step only; result in `int` øre. |
| C3 | **Equal-cost share estimate** (US-803) = mean over the last ≤N posted settlements of `sum(equal invoice-line amount_ore) ÷ count(participates_equal members in that snapshot)`. A member's forecast includes it only when their **current effective participation** (`MemberRepo.effective_participation`) is true. | Settlements with zero equal participants are skipped. |
| C4 | **Recommended minimum balance** (US-804) = `forecast_monthly_cost_ore × buffer_months` where `forecast_monthly_cost_ore = round(forecast_kwh × rate_ore_per_kwh) + equal_share_ore`. `buffer_months` from `forecast_settings` (default `2.0`). | Recommended top-up shown in the portal = `max(0, recommended_minimum_ore − balance_ore)`. |
| C5 | **Low balance** (US-805) when `balance_ore < recommended_minimum_ore`. Severity `critical` when `balance_ore < forecast_monthly_cost_ore` (cannot cover next month), otherwise `low`. | The portal banner and the email both use this severity. |
| C6 | **Low-balance warning emails** are enqueued by an explicit scan — `POST /api/notifications/low-balance-scan` (admin, `require_fetch`, cron-drainable, mirrors `/process`) and a `low-balance-scan` CLI subcommand. **Suppression:** a new email is enqueued for a member only if *any* of — no `low_balance_notifications` row within `forecast_settings.notify_cooldown_days` (default 14); OR `balance_ore` dropped ≥ 100 øre since the last row; OR severity escalated to `critical` from a previous `low`. Every send writes one `low_balance_notifications` row (linked to the `email_messages` id) and one audit event (`notifications.low_balance_warned`). | Members with `available: false` forecasts are always skipped. |
| C7 | **Forecast settings** = one singleton row (`forecast_settings`, `id` CHECK `= 1`) seeded by the migration. Admin reads/writes via `GET` / `PUT /api/forecast/settings`. Each write is one audit row (`forecast.settings_updated`, before/after in `detail`). No new `config.yaml` block — tunables live in the DB so an admin changes them from the UI without a redeploy. | |
| C8 | **Forecast is a pure read-model.** `ForecastRepo` computes on demand from posted settlements + the ledger. Nothing is persisted except the settings row (C7) and the notification-history row (C6). | |
| C9 | **PDF = WeasyPrint** rendering the existing self-contained HTML report. `reports/pdf.py` exposes `html_to_pdf(html: str) -> bytes` and `PDF_AVAILABLE: bool`. If the import fails the `.pdf` endpoints return `503 pdf_unavailable` and a settlement post still writes the HTML. Endpoints: `GET /api/settlement/{id}/reports/{member_id}.pdf` and `.../reports/summary.pdf` (admin), `GET /api/me/settlements/{id}/report.pdf` (member). `write_reports` also writes `medlem-<id>.pdf` + `sammendrag.pdf` when WeasyPrint is available (best-effort — an `OSError`/`Exception` there never breaks a post). | Dockerfile runtime stage gains the WeasyPrint apt deps. |
| C10 | **HTML report forecast section** (fills the 1B stub) — `render_member_report(result, member, forecast=None)`. When `forecast` is present and `available`, it renders "Prognose neste måned" (kWh, estimated cost) and "Anbefalt saldo / innbetaling". `SettlementRepo.post` computes each member's forecast *after* the charges land and passes it into `write_reports`; the live report endpoints compute it on the fly. | Keep `render_summary_report` unchanged. |
| C11 | **Member portal dashboard stays in `MyAccount.tsx`** — no new route. A forecast card, a current-month consumption card, and a low-balance banner are added above the existing history. Admin forecast settings get a small dedicated page reachable from the "System" nav. | |
| C12 | **`ChargingRepo` gains no schema** — `member_consumption(member_id, month)` is `consumption_by_member(month).get(member_id, Decimal(0))` for the pre-settlement current-month figure (US-902). | |

---

## Data model additions — `migrations/0007_forecast.sql`

```sql
CREATE TABLE forecast_settings (
    id                         INTEGER PRIMARY KEY CHECK (id = 1),
    rate_override_ore_per_kwh  INTEGER,
    buffer_months              REAL    NOT NULL DEFAULT 2.0,
    notify_cooldown_days       INTEGER NOT NULL DEFAULT 14,
    lookback_settlements       INTEGER NOT NULL DEFAULT 3,
    updated_at                 TEXT,
    updated_by_user_id         INTEGER REFERENCES users (id)
);
INSERT INTO forecast_settings (id) VALUES (1);

CREATE TABLE low_balance_notifications (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id                 INTEGER NOT NULL REFERENCES members (id),
    severity                  TEXT NOT NULL CHECK (severity IN ('low', 'critical')),
    balance_ore               INTEGER NOT NULL,
    recommended_minimum_ore   INTEGER NOT NULL,
    forecast_monthly_cost_ore INTEGER NOT NULL,
    email_message_id          INTEGER REFERENCES email_messages (id),
    created_at                TEXT NOT NULL
);
CREATE INDEX idx_lbn_member ON low_balance_notifications (member_id, created_at DESC);
```

`0007` is one migration file with both tables (they ship together in 1C).

---

## Ordered work items (one reviewable commit each)

| # | Commit | Scope | User stories |
|---|---|---|---|
| **P1** | `feat(forecast): trailing-mean forecast engine` | `migrations/0007_forecast.sql`; `domain/forecast.py` `ForecastRepo` — `settings()`, `update_settings(*, actor, **fields)` (audit), `history_stats()` (per-settlement rate + equal-share, plus the trailing means), `member_forecast(member_id)` → `{available, forecast_kwh, rate_ore_per_kwh, rate_source: 'derived'|'override', equal_share_ore, forecast_monthly_cost_ore, recommended_minimum_ore, balance_ore, recommended_topup_ore, low_balance, severity}`, `all_member_forecasts()`; `test_forecast.py` (rate derivation, override, <N history, no-grid-kWh, equal-share w/ participation, recommended-minimum, severity boundaries, money in øre). | US-801, US-802, US-803, US-804 |
| **P2** | `feat(api): forecast settings + member forecast/consumption` | `webapp/routes/forecast.py` (admin router: `GET` / `PUT /api/forecast/settings`, `GET /api/forecast/members` overview for the admin table); `routes/me.py` gains `GET /api/me/forecast` and `GET /api/me/consumption?month=` (defaults to the current Oslo month); `ChargingRepo.member_consumption`; `schemas.py` (`ForecastSettingsIn/Out`, `MemberForecastOut`); register the router in `app.py`; extend `test_me_scoping.py`; `test_forecast_api.py`. | US-802, US-901, US-902, US-903, US-904 |
| **P3** | `feat(notifications): low-balance warnings` | `0007` `low_balance_notifications` (in the same migration as P1 — P1 writes the file, P3 only adds code); `NotificationRepo.scan_low_balances(*, actor)` — iterate `ForecastRepo.all_member_forecasts()`, apply the C6 suppression rule, `enqueue` a Norwegian warning email + insert the history row + audit; `routes/notifications.py` `POST /api/notifications/low-balance-scan`; `__main__.py` `low-balance-scan` subcommand (mirrors how a cron would call it); `routes/system.py` health payload gains `low_balance: {warned_total, members_below}`; `test_low_balance.py` (first send, cooldown suppression, balance-drop re-send, low→critical escalation, no-forecast skip). | US-805, US-1104 |
| **P4** | `feat(reports): PDF settlement reports` | add `weasyprint` to `pyproject.toml` deps; `reports/pdf.py` (`PDF_AVAILABLE`, `html_to_pdf`); `reports/__init__.py` re-exports; `routes/settlement.py` — `GET /{id}/reports/{member_id}.pdf`, `GET /{id}/reports/summary.pdf` (admin; `503 pdf_unavailable` when not available); `routes/me.py` — `GET /api/me/settlements/{id}/report.pdf`; `reports.write_reports` writes `.pdf` siblings best-effort; `Dockerfile` runtime stage installs `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 fonts-dejavu-core` (final list per WeasyPrint 60+); `test_report_pdf.py` (`skipif not PDF_AVAILABLE`: bytes start `%PDF`; the 503 branch tested by monkeypatching `PDF_AVAILABLE`). | US-906 |
| **P5** | `feat(reports): forecast section in member report` | `render_member_report(result, member, forecast=None)` — replace the stub `<footer>` line with a real "Prognose neste måned" + "Anbefalt saldo / innbetaling" section when `forecast` is given; `SettlementRepo.post` builds `{member_id: ForecastRepo.member_forecast(...)}` after the ledger writes and passes it to `write_reports`; `write_reports` threads `forecasts` through; live endpoints in `routes/settlement.py` + `routes/me.py` pass a fresh forecast; update `test_settlement_reports.py`. | US-905 |
| **P6** | `feat(web): Release 1C member portal + forecast admin` | `MyAccount.tsx` — low-balance banner (severity-coloured), forecast card (forecast kWh, est. monthly cost, recommended minimum balance, recommended top-up), current-month consumption card (`/api/me/consumption`); each settlement-history row gets a "PDF" link beside "Rapport". New `pages/ForecastSettings.tsx` (route `/forecast`, admin-only, linked from the nav next to "System"): rate override, buffer months, cooldown days, lookback; a "Kjør lavsaldo-varsling nå" button → `POST /api/notifications/low-balance-scan`; an overview table from `GET /api/forecast/members`. `api/client.ts` wrappers + types; MSW handlers for every new endpoint; Vitest (`MyAccount` forecast/banner, `ForecastSettings` save + scan). Update `frontend/CLAUDE.md` contract section. | US-805, US-901..904, US-906 |
| **P7** | `docs: Release 1C` | `README.md` — forecast settings, the low-balance-scan cron line (alongside `/process` and the monthly sync), the WeasyPrint deploy note + PDF endpoints, config table unchanged (note the tunables are DB-side); consolidated `CHANGELOG.md` "Release 1C" entry above the per-phase entries; `VERSION` + `pyproject.toml` → `0.3.0`; `spec/implementation-plan.md` status + refreshed 1D sketch; `webapp/CLAUDE.md` contract additions. Mark every phase ☑ in this file's status table with its commit hash. | — |

Dependency order: **P1 → P2, P3, P5**; **P4** independent (needs only 1B reports);
**P6** needs P2 (+ P4 for the PDF link); **P7** last.

---

## Residual risks

- **WeasyPrint system deps in Docker** — the runtime image is `python:3.12-slim`;
  WeasyPrint needs Pango/HarfBuzz/FFI shared libs. Pin the apt package list, keep
  the `PDF_AVAILABLE` guard so the app runs without them, and add a CI check that
  the built image can `import weasyprint`.
- **Sparse settlement history** — fewer than one posting for a member, or no
  historical `grid_kwh > 0`, yields `available: false`; forecast endpoints return
  a neutral body, the portal shows "ikke nok historikk", and **no email is ever
  enqueued without an available forecast**.
- **Rate-derivation divide-by-zero** — settlements with `grid_kwh` 0/NULL are
  excluded from the rate mean; `Decimal`, never `float`; `settlement_members
  .consumption_kwh` parsed with `Decimal`.
- **Duplicate low-balance emails** — the `low_balance_notifications` history plus
  the cooldown / balance-drop / escalation rule (C6); `scan_low_balances` is
  idempotent within the cooldown window; safe to run from cron every hour.
- **Forecast money rounding** — all forecast arithmetic in `int` øre; the single
  `Decimal` boundary is `forecast_kwh × rate_ore_per_kwh`, `ROUND_HALF_EVEN`.
- **Report forecast at post time** — computed *after* the ledger rows are written
  so `balance_ore` in the report reflects the just-posted charge; a failure in
  the forecast step is swallowed like the existing report-write guard.
- **PDF endpoint auth** — the member `.pdf` route resolves the member from the
  session (never a path id), same as the existing HTML report route; admin
  `.pdf` routes sit under the `require_admin` router.

---

## Manual verification checklist (hand back to the user)

1. `docker build` the image, then `docker run --rm … python -c "import weasyprint"`
   exits 0.
2. With ≥3 posted settlements: `GET /api/me/forecast` for a member returns a
   plausible `forecast_kwh` / `forecast_monthly_cost_nok`; `recommended_minimum`
   ≈ `buffer_months` × monthly cost.
3. Admin sets `rate_override_ore_per_kwh` in the UI → the member forecast cost
   moves; an audit event `forecast.settings_updated` with before/after appears.
4. `POST /api/notifications/low-balance-scan` then `POST /api/notifications/process`
   → members below their recommended minimum get exactly one email; a second scan
   the same day sends nothing; lower a member's balance and re-scan → one new
   email; a `low → critical` transition re-sends even within the cooldown.
5. `GET /api/me/settlements/{id}/report.pdf` → `Content-Type: application/pdf`,
   opens in a viewer, Norwegian characters (æ ø å) render.
6. The posted-settlement HTML report now shows the "Prognose neste måned" and
   "Anbefalt innbetaling" section instead of the placeholder line.
7. README cron block: the low-balance scan + queue drain + monthly sync commands
   all run against a real instance.
