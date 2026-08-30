# frontend — Ladelaug avregning SPA

React 18 + Vite 5 + TS (strict) + Tailwind 3 + react-router-dom v6 + SWR.
Tests: Vitest + Testing Library + MSW (jsdom).

- `npm run dev` — Vite dev server, proxies `/api` -> `http://127.0.0.1:8080`.
- `npm run build` — `tsc && vite build`; output in `dist/` (FastAPI serves it at `/`).
- `npm run check` — `tsc --noEmit && eslint . && vitest run`.

## Conventions

- All API access goes through `src/api/client.ts`. It sends `credentials: "include"`
  and adds `X-Requested-With: fetch` on every POST/PATCH/DELETE (else backend 403 `csrf`).
- Errors are always `{"detail": {"code", "message"}}` -> `ApiError { status, code, message }`.
- Money is a Decimal **string** from the API. Never `Number()` it for display math —
  format via `src/lib/format.ts` (`formatNok`, `formatDate`, `formatDateTime`).
- Auth state comes from `useAuth()` (SWR on `GET /api/auth/me`). `<RequireAuth>` sends
  unauthenticated users to `/login`; `<RequireAdmin>` sends `role=member` to `/my-account`.

## API response shapes the MSW handlers assert against (contract-drift guard)

Base path `/api`, same origin, session via HttpOnly cookie `ladelaug_session`.

- `POST /api/auth/login` `{email,password}` -> 200 `{user:{id,email,role:"admin"|"member",member_id:number|null,disabled:boolean}}`; 401 `not_authenticated`; 429 `rate_limited` (+ `Retry-After`); 403 `csrf` without `X-Requested-With`.
- `POST /api/auth/logout` -> 200 `{ok:true}`.
- `GET /api/auth/me` -> 200 `{id,email,role,member_id,disabled,version:string}`; 401 `not_authenticated`.
- `GET /api/members` -> `{members:[Member]}`.
- `POST /api/members` (201) `{member_reference,full_name,email?,join_date:"YYYY-MM-DD"}` -> Member; 422 `reference_taken` | `validation_error`.
- `GET /api/members/{id}` -> Member; 404 `not_found`.
- `PATCH /api/members/{id}` (partial) -> Member.
- `POST /api/members/{id}/status` `{status:"active"|"inactive",effective_from?,note?}` -> `{period:StatusPeriod}`; 422 `backdated` | `status_unchanged` | `validation_error`.
- `GET /api/members/{id}/status-history` -> `{periods:[StatusPeriod]}`.
- `POST /api/members/{id}/participation` `{participates:boolean,effective_from?,reason?}` -> `{period:ParticipationPeriod}`; 422 `participation_unchanged` | `backdated` | `validation_error`.
- `GET /api/members/{id}/participation-history` -> `{periods:[ParticipationPeriod]}`.
- `GET /api/members/{id}/balance` -> `{member_id,balance_nok:string,balance_ore:number}`.
- `GET /api/members/{id}/ledger?limit=&offset=` -> `{transactions:[Txn],total,balance_nok,balance_ore}` (newest first).
- `POST /api/members/{id}/payments` (201) `{amount:"1500.00",value_date?,reference?}` -> Txn; 422 `validation_error` if amount <= 0.
- `POST /api/members/{id}/adjustments` (201) `{direction:"credit"|"debit",amount:"50.00",reason:string(non-empty),reference?}` -> Txn; 422 `validation_error` on empty reason.
- `POST /api/ledger-transactions/{id}/reverse` (201) -> reversal Txn; 422 `already_reversed` | `not_a_payment`; 404 `not_found`.
- `GET /api/audit-events?event_type=&entity_type=&entity_id=&limit=&offset=&sort_by=&sort_dir=` -> `{events:[AuditEvent],total,counts:{[event_type]:number}}`. `sort_by ∈ occurred_at|id|event_type`, `sort_dir ∈ asc|desc`.
- `GET /api/me` -> Member. `GET /api/me/balance` -> Balance. `GET /api/me/ledger?limit=&offset=` -> ledger page. `GET /api/me/status` -> `{status,participates,history:[StatusPeriod]}`.
- `GET /api/me/settlements` -> `{settlements:[MySettlement]}`; each `report_url` is `/api/me/settlements/{id}/report` — the PDF is the same URL with `.pdf` appended.

### Chargers (Release 1B, Epic 3 — admin)

- `GET /api/chargers` -> `{chargers:[Charger]}`. `Charger.deletable` is `true` only for a hand-entered charger (`zaptec_id === null`) with no imported usage.
- `POST /api/chargers` (201) `{name,serial_no?,zaptec_id?,device_type?}` -> `Charger`.
- `PATCH /api/chargers/{id}` (admin, `X-Requested-With`) partial `{name?,serial_no?,device_type?,is_active?}` -> `Charger`; 422 `no_changes` | `name_required`; `zaptec_id` is not patchable.
- `DELETE /api/chargers/{id}` (admin, `X-Requested-With`) -> 204. 422 `zaptec_charger` (mirrored from Zaptec — deactivate instead) | `charger_has_usage`; 404 `not_found`. Cascade-removes the charger's assignment history.
- `POST /api/chargers/{id}/assignments` `{member_id, effective_from?:"YYYY-MM-DD", note?}` -> `{assignment}`. `effective_from` defaults to today; back-date it to cover already-imported usage. Opening/closing an assignment auto-re-resolves member attribution for every non-posted month with usage for that charger.
- `Charger = {id,zaptec_id:string|null,name,serial_no:string|null,device_type:string|null,is_active:boolean,last_synced_at:string|null,created_at,updated_at,assigned_member_id:number|null,deletable:boolean}`

### Charging data / attribution (Release 1B, Epic 4 — admin)

- `GET /api/charging/unassigned?month=YYYY-MM` -> `{month,total_kwh:string,chargers:[{charger_zaptec_id,charger_id:number|null,charger_name:string|null,sessions:number,energy_kwh:string}]}`. `total_kwh>0` blocks a settlement freeze for that month.
- `POST /api/charging/reresolve?month=YYYY-MM` (admin, `X-Requested-With`) -> `{month,sessions_changed:number}`. Re-computes `charger_id` + `member_id` for the month's imported rows from the current chargers and assignments.
- Settlement `compute`/`preview` may emit a `{"code":"usage_stale"}` warning when the frozen snapshot no longer matches the imported usage (unassigned kWh appeared, or a session changed after `usage_frozen_at`). It is post-blocking — re-freeze to clear it.

### Forecasting + low-balance (Release 1C, Epic 8)

- `GET /api/me/forecast` -> `MemberForecast` (member session). Always a flat, fully-populated object; when `available=false` the numeric fields are `0` and `reason ∈ "insufficient_history" | "no_grid_kwh"`.
- `GET /api/me/consumption?month=YYYY-MM` -> `MemberConsumption` (defaults to the current Oslo month); 422 `bad_month` on a malformed `month`.
- `GET /api/forecast/settings` (admin) -> `ForecastSettings`.
- `PUT /api/forecast/settings` (admin, `X-Requested-With`) partial body `ForecastSettingsUpdate` -> `ForecastSettings`. An explicit `rate_override_ore_per_kwh:null` clears the override; 422 on non-positive rate / `buffer_months<=0` / negative cooldown / `lookback_settlements<1`.
- `GET /api/forecast/members` (admin) -> `{members:[MemberForecast]}` (one row per member; carries only `member_id`, join names from `GET /api/members`).
- `POST /api/notifications/low-balance-scan` (admin, `X-Requested-With`) -> `{scanned,below,queued,suppressed}` (`LowBalanceScanResult`). Enqueues warning emails; drain with `POST /api/notifications/process`.

### Types

- `Member = {id,member_reference,full_name,email:string|null,join_date,created_at,updated_at,status:"active"|"inactive"|null,participates:boolean|null}`
- `StatusPeriod = {id,status,effective_from,effective_to:string|null,note:string|null,created_at}`
- `ParticipationPeriod = {id,participates:boolean,effective_from,effective_to:string|null,reason:string|null,created_at}`
- `Txn = {id,member_id,txn_type:"payment"|"payment_reversal"|"adjustment_credit"|"adjustment_debit",amount_ore:number,amount_nok:string,currency,value_date,reason:string|null,reference:string|null,reverses_transaction_id:number|null,created_by_user_id,recorded_at}`
- `AuditEvent = {id,occurred_at,actor_user_id:number|null,actor_label,event_type,entity_type,entity_id:string|null,summary,detail:object|null,ip:string|null}`
- `MySettlement = {settlement_id,period_month,posted_at:string|null,consumption_kwh:string,charge_nok:string,balance_after_nok:string,report_url:string}`
- `MemberForecast = {member_id,available:boolean,forecast_kwh:string,rate_ore_per_kwh:string,rate_source:"derived"|"override"|null,equal_share_ore:number,forecast_monthly_cost_ore:number,recommended_minimum_ore:number,balance_ore:number,recommended_topup_ore:number,low_balance:boolean,severity:"low"|"critical"|null,reason:string|null}` — money fields are canonical integer øre (format with `formatOre`), `forecast_kwh`/`rate_ore_per_kwh` are Decimal strings.
- `MemberConsumption = {member_id,month:string,consumption_kwh:string,session_count:number}`
- `ForecastSettings = {rate_override_ore_per_kwh:number|null,buffer_months:number,notify_cooldown_days:number,lookback_settlements:number,updated_at:string|null,updated_by_user_id:number|null}`
- `ForecastSettingsUpdate = Partial<{rate_override_ore_per_kwh:number|null,buffer_months:number,notify_cooldown_days:number,lookback_settlements:number}>`
- `LowBalanceScanResult = {scanned:number,below:number,queued:number,suppressed:number}`

## Status

- G1 (scaffold + auth shell): PASS
- G2 (members + status + participation): PASS
- G3 (ledger + audit log): PASS
- G4 (member portal): PASS
- Release 1C P6 (portal forecast/consumption/low-balance + admin forecast page): PASS

`npm run check` (tsc + eslint + vitest) and `npm run build` both green.
