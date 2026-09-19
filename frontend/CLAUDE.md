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
  `formatNok`/`formatOre` render `kr` first (`kr 1 500,00`). In a **table cell**
  use `<Money value={...}>` (or `<Money ore={...}>`) instead of raw `formatNok`:
  in a right-aligned `tabular-nums` column it keeps `kr` a small constant gap
  left of a fixed-width digit box, so both the `kr` and the øre line up down the
  column. Keep raw `formatNok` for amounts in prose / stat tiles. Free-text numeric inputs pass their value through
  `normalizeDecimalInput` before the API call, so both `"123,45"` and `"123.45"`
  mean 123.45 (mirrors `money.normalise_decimal_input` on the backend, which is
  the authority).
- Auth state comes from `useAuth()` (SWR on `GET /api/auth/me`). `<RequireAuth>` sends
  unauthenticated users to `/login`; `<RequireAdmin>` sends `role=member` to `/` (the site
  root). Route paths are Norwegian and centralised in `src/routes.ts` (`ROUTES`):
  `/medlemmer`, `/brukere`, `/ladere`, `/avregninger`, `/bevegelser`, `/revisjonslogg`,
  `/prognose`, `/system`. The member "min side" IS the root `/` (no suffix); an admin hitting
  `/` is redirected to `/medlemmer`. `/login` and `/auth/*` stay English (the latter is in
  already-sent email links).

## API response shapes the MSW handlers assert against (contract-drift guard)

Base path `/api`, same origin, session via HttpOnly cookie `ladelaug_session`.

- `POST /api/auth/login` `{email,password}` -> 200 `{user:{id,email,role:"admin"|"member",member_id:number|null,disabled:boolean}}`; 401 `not_authenticated`; 429 `rate_limited` (+ `Retry-After`); 403 `csrf` without `X-Requested-With`.
- `POST /api/auth/logout` -> 200 `{ok:true}`.
- `GET /api/auth/me` -> 200 `{id,email,role,member_id,disabled,version:string,view_as:{member_id:number,member_name:string}|null}`; 401 `not_authenticated`. `view_as` is set only when an admin is previewing the member portal "as" that member (read-only) — see `POST`/`DELETE /api/admin/view-as`.
- `POST /api/admin/view-as/{member_id}` (admin, `X-Requested-With`) -> 200 `{member_id,member_name}`; 404 `not_found`. Stamps the target on the admin's own session row so `get_current_member` resolves to it and every `/api/me/*` **write** returns 403 `view_as_read_only`. Audited `admin.view_as_started`. `DELETE /api/admin/view-as` -> 200 `{ok:true}` clears it (audited `admin.view_as_stopped`). Never hands over the member's session. In the SPA: `Members` row action "Se som medlem" → lands on `/` rendering `MyAccount`, with an amber "Du ser portalen som …" banner in the layout and the admin nav hidden until **Avslutt**.
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
- `GET /api/ledger-transactions?limit=&offset=&member_id=&txn_type=` (admin) -> `{transactions:[LedgerTxnRow],total}` (newest first; cross-member, each row joined to `member_name`/`member_reference`).

### Users / logins (admin)

- `GET /api/users` -> `{users:[User]}`.
- `POST /api/users` (201) `{email,password?:string|null,role:"admin"|"member",member_id?:number}` -> `User`. `password` omitted/`null` => activation-only account. 422 `email_taken` | `member_linked` | `validation_error` (member login needs `member_id`; admin login must not set it).
- `PATCH /api/users/{id}` (admin, `X-Requested-With`) partial `{email?,role?,member_id?}` -> `User`. Empty body 422 `validation_error`. Promoting to `admin` auto-nulls `member_id`; `role:"member"` needs a `member_id`. 422 `email_taken` | `member_linked` | `validation_error` | `cannot_demote_self` | `last_admin`; 404 `not_found` (unknown user or `member_id`).
- `POST /api/users/{id}/disable` / `POST /api/users/{id}/enable` (admin, `X-Requested-With`) -> `User`. Disable revokes the user's sessions; 422 `cannot_disable_self` | `last_admin`.
- `POST /api/users/{id}/password` (admin, `X-Requested-With`) `{password:string(>=10)}` -> `{ok:true}`; 422 `validation_error`.
- `User = {id,email,role:"admin"|"member",member_id:number|null,disabled:boolean}`.
- `GET /api/audit-events?event_type=&entity_type=&entity_id=&actor=&occurred_from=&occurred_to=&limit=&offset=&sort_by=&sort_dir=` -> `{events:[AuditEvent],total,counts:{[event_type]:number}}`. `actor` is an `actor_label` substring match; `occurred_from`/`occurred_to` bound `occurred_at` (ISO strings). `sort_by ∈ occurred_at|id|event_type`, `sort_dir ∈ asc|desc`.
- `GET /api/audit-events/{id}` -> `{event:AuditEvent}`; 404 `not_found`.
- `GET /api/audit-events/export.csv?<same filters>` -> `text/csv` attachment `revisjonslogg.csv` (admin), newest first, capped at 10000 rows.
- `GET /api/me` -> Member. `GET /api/me/balance` -> `{member_id,balance_nok:string,balance_ore:number,payment_account_number:string}` (`payment_account_number` from server config `payment.account_number`; `""` when unset — the dashboard shows it as a "Betal inn til kontonr …" hint under the balance tile). `GET /api/me/ledger?limit=&offset=` -> ledger page. `GET /api/me/status` -> `{status,participates,history:[StatusPeriod]}`.
- `PATCH /api/me` (member, `X-Requested-With`) partial `{full_name?,email?}` -> Member. Self-edit of the caller's own member record — **only** those two fields (`member_reference` / `join_date` stay admin-only); 422 `validation_error` on an empty body or a malformed email. Drives the "Min profil" page.
- `POST /api/me/password` (member, `X-Requested-With`) `{new_password:string}` -> `{ok:true}`. No current-password check (the live session is the proof); min 10 chars + a small known-weak blocklist (422 `validation_error`). On success every **other** session for the login is revoked (current one kept) and a `password_changed` email is queued; audited `auth.password_changed`.
- `GET /api/me/settlements` -> `{settlements:[MySettlement]}`; `report_url` is `/api/me/settlements/{id}/report` (PDF: same URL + `.pdf`). The report page links each supplier invoice as `invoices/{aid}` -> `GET /api/me/settlements/{id}/invoices/{aid}` (streams one PDF, member-scoped); invoices are **not** surfaced in the settlement list itself. The list also includes any **shared draft** (`is_draft:true`, `posted_at:null`) — a frozen settlement the board published for preview via `POST /api/settlement/{id}/share-draft`; its report/PDF/invoice endpoints work the same but the report is watermarked `UTKAST`. `MyAccount` renders those in a separate amber "Utkast til avregning" region.
- `GET /api/settlement/{id}` (admin) -> `SettlementDetail` incl. an `attachments:[SettlementAttachment]` list.
- `POST /api/settlement/{id}/lines` (201) `{description,allocation_method:"equal"|"consumption",amount,category?}` -> `{line}` (draft only). `amount` may be **negative** (a credit line) but not zero. `PATCH /api/settlement/{id}/lines/{lineId}` (admin, `X-Requested-With`, draft only) partial `{description?,allocation_method?,amount?,category?}` -> `SettlementDetail`; 422 `no_changes` (empty body) | `bad_amount` (zero) | `bad_method` | `description_required` | `not_draft`, 404 `not_found`. `DELETE /api/settlement/{id}/lines/{lineId}` -> `SettlementDetail`. All re-sync `invoice_total_nok`.
- `POST /api/settlement/{id}/attachments` (admin, multipart `files`, `X-Requested-With`) -> `SettlementDetail`; allowed in any status. `GET /api/settlement/{id}/attachments/{aid}` -> the file. `DELETE /api/settlement/{id}/attachments/{aid}` (admin, `X-Requested-With`) -> `SettlementDetail`; allowed in any status. 404 `not_found` for an unknown attachment.
- `POST /api/settlement/{id}/resend-reports` (admin, `X-Requested-With`) -> `{settlement_id,period_month,emails_queued:number}`. Posted settlements only (422 `not_posted`; 404 `not_found`). Recomputes from the frozen snapshot and appends a fresh batch of `queued` report emails — enqueue only, sent on the next queue drain. Audited `settlement.reports_resent`. Drives the **Send rapport-e-post på nytt** button on `SettlementDetail`.
- `POST` / `DELETE /api/settlement/{id}/share-draft` (admin, `X-Requested-With`) -> `SettlementDetail`. Publish / retract a frozen draft for member preview (`Settlement.draft_shared_at`). 422 `not_frozen` (share before freeze), `not_draft` (already posted), `not_shared` (retract when not shared). Audited `settlement.draft_shared` / `settlement.draft_unshared`. Drives the **Del utkast med medlemmer** / **Trekk tilbake** toggle shown on a frozen draft.

### Chargers (Release 1B, Epic 3 — admin)

- `GET /api/chargers` -> `{chargers:[Charger]}`. `Charger.deletable` is `true` only for a hand-entered charger (`zaptec_id === null`) with no imported usage.
- `POST /api/chargers` (201) `{name,serial_no?,zaptec_id?,device_type?}` -> `Charger`.
- `PATCH /api/chargers/{id}` (admin, `X-Requested-With`) partial `{name?,serial_no?,device_type?,is_active?}` -> `Charger`; 422 `no_changes` | `name_required`; `zaptec_id` is not patchable.
- `DELETE /api/chargers/{id}` (admin, `X-Requested-With`) -> 204. 422 `zaptec_charger` (mirrored from Zaptec — deactivate instead) | `charger_has_usage`; 404 `not_found`. Cascade-removes the charger's assignment history.
- `POST /api/chargers/{id}/assignments` `{member_id, effective_from?:"YYYY-MM-DD", note?}` -> `{assignment}`. `effective_from` defaults to today; back-date it to cover already-imported usage. Opening/closing an assignment auto-re-resolves member attribution for every non-posted month with usage for that charger.
- `Charger = {id,zaptec_id:string|null,name,serial_no:string|null,device_type:string|null,is_active:boolean,last_synced_at:string|null,created_at,updated_at,assigned_member_id:number|null,deletable:boolean}`

### Charging data / attribution (Release 1B, Epic 4 — admin)

- `GET /api/charging/consumption?month=YYYY-MM` -> `{month,total_kwh:string,unassigned_kwh:string,by_member:[{member_id:number,energy_kwh:string}]}` — live metered kWh for the month from imported sessions (before any freeze). The admin settlement page shows it as a "foreløpig" panel on drafts.
- `GET /api/charging/unassigned?month=YYYY-MM` -> `{month,total_kwh:string,chargers:[{charger_zaptec_id,charger_id:number|null,charger_name:string|null,sessions:number,energy_kwh:string}]}`. `total_kwh>0` blocks a settlement freeze for that month.
- `POST /api/charging/reresolve?month=YYYY-MM` (admin, `X-Requested-With`) -> `{month,sessions_changed:number}`. Re-computes `charger_id` + `member_id` for the month's imported rows from the current chargers and assignments.
- `GET /api/charging/history?months=N` (admin; `N` 1..24, default 12, 422 outside) -> `{months:[{month,assigned_kwh:string,unassigned_kwh:string,grid_kwh:string,session_count:number,invoice_kwh:string|null,invoice_total_nok:string|null,cost_per_kwh_nok:string|null,consumption_cost_nok:string|null,fixed_cost_nok:string|null,settled:boolean}]}` — rolling window ending the current Oslo month, oldest first. `assigned_kwh`+`unassigned_kwh` reconcile to `grid_kwh`; `invoice_kwh` / `invoice_total_nok` / `cost_per_kwh_nok` (`= invoice_total_nok / invoice_kwh`) / `consumption_cost_nok` / `fixed_cost_nok` are populated only for months with a posted settlement. `consumption_cost_nok` (invoice lines allocated by kWh share) + `fixed_cost_nok` (lines split equally) reconcile to `invoice_total_nok`, and are `null` if the settlement carries no itemised lines. Drives the admin **Forbruk** page's consumption + cost charts (`ConsumptionHistoryChart`, `GridRateChart`, `CostSplitChart`).
- `GET /api/charging/usage?hours=N&end=ISO` or `?month=YYYY-MM` (admin; `hours` 1..720 default 168, 422 outside; `end` an ISO-8601 datetime, 422 `bad_end` if malformed, floored to the hour, ignored with `month`; `month` wins if both given, 422 `bad_month` if malformed) -> `{hours:[{hour:string,avg_power_kw:string,charging_sessions:number,idle_sessions:number}]}` — either `hours` ending at `end` (default: now, current partial hour included as the last bucket) or every hour of one full local calendar month, oldest first. `avg_power_kw` is `charging_intervals` energy summed per hour (kWh over a 1h bucket == kW average). Session state is derived, not stored: a session counts as `charging_sessions` in an hour it has an energy>0 interval point, `idle_sessions` where it's occupied (`[started_at,ended_at)` overlaps the hour) with none — Zaptec omits interval rows during idle stretches rather than reporting zero-energy ones, so a gap is a real idle signal. A session synced without interval data can't be split and counts as idle for its whole span. Drives the admin **Forbruk** overview's `UsageChart` (2d/7d/Måned window toggle, all whole calendar days/months — today or the current month included in full even mid-day/mid-month — paged back/forward one window-width per click with the same ‹ range › arrows for every window kind; no raw date/month `<input>` on this chart).
- `GET /api/charging/peak-hours?month=YYYY-MM&limit=N` (admin; `month` defaults to the current Oslo month, 422 `bad_month` if malformed; `limit` 1..50 default 10, 422 outside) -> `{month,hours:[{hour,avg_power_kw,charging_sessions,idle_sessions}]}` — the `limit` busiest hours in that one calendar month (same hourly buckets as `/usage`), highest `avg_power_kw` first, ties broken by the earliest hour. Hours with no charging are excluded, so a quiet month returns fewer than `limit` rows (possibly none). Drives the admin **Forbruk** overview's `PeakHoursList` (own month picker, independent of `UsageChart`'s).
- `GET /api/charging/sessions?month=YYYY-MM&member_id=&limit=&offset=` (admin; `limit` capped at 500) -> `{month,total:number,sessions:[raw charging_sessions row]}` ordered by `started_at` **descending** (newest first). Each row: `{id,zaptec_session_id,charger_id:number|null,charger_zaptec_id,member_id:number|null,period_month,started_at,ended_at:string|null,energy_kwh:string,split_method:"none"|"interval"|"duration",user_full_name:string|null,source}`. `member_id` null = unassigned. Member/charger *names* are joined client-side. Drives the **Forbruk** page's `SessionHistory` table + size sparkline.
- `GET /api/charging/sessions/{zaptec_session_id}` (admin) -> `{zaptec_session_id,parts:[raw charging_sessions row],intervals:[{charger_zaptec_id,charger_id:number|null,member_id:number|null,period_month,interval_start,energy_kwh:string}]}`; 404 `not_found`. `parts` is one row per calendar month the session touched (oldest first); `intervals` is the 15-minute `charging_intervals` points imported for it (empty unless the sync pulled `EnergyDetails`). Drives the `SessionHistory` row-click drill-down (`SessionDetailModal`).
- Settlement `compute`/`preview` may emit a `{"code":"usage_stale"}` warning when the frozen snapshot no longer matches the imported usage (unassigned kWh appeared, or a session changed after `usage_frozen_at`). It is post-blocking — re-freeze to clear it.
- `GET /api/settlement/{id}/reports` (+ `/reports/summary[.pdf]`, `/reports/{member_id}[.pdf]`) render from the frozen snapshot and work for **any frozen settlement**, draft or posted — not only posted ones. The admin UI shows them (labelled "forhåndsvisning") once `usage_frozen_at` is set; `.pdf` needs WeasyPrint on the host (else 503 `pdf_unavailable`).

### Forecasting + low-balance (Release 1C, Epic 8)

- `GET /api/me/forecast` -> `MemberForecast` (member session). Always a flat, fully-populated object; when `available=false` the numeric fields are `0` and `reason ∈ "insufficient_history" | "no_grid_kwh"`.
- `GET /api/me/consumption?month=YYYY-MM` -> `MemberConsumption` (defaults to the current Oslo month); 422 `bad_month` on a malformed `month`.
- `GET /api/me/history?months=6` (member; `months` 1..24, 422 outside) -> `{months:[MemberHistoryMonth]}` — rolling window ending with the current Oslo month, oldest first. Each row: `{month,consumption_kwh,session_count,charge_nok:string|null,charge_ore:number|null,settled:boolean,balance_end_nok,balance_end_ore}`. `charge_*` is populated only for months whose settlement is posted; `balance_end_*` is the running ledger balance (`SUM(amount_ore)`) at that month's end, forward-filled. Drives the dashboard's `UsageHistoryChart`.
- `GET /api/forecast/settings` (admin) -> `ForecastSettings`.
- `PUT /api/forecast/settings` (admin, `X-Requested-With`) partial body `ForecastSettingsUpdate` -> `ForecastSettings`. An explicit `rate_override_ore_per_kwh:null` clears the override; 422 on non-positive rate / `buffer_months<=0` / negative cooldown / `lookback_settlements<1`.
- `GET /api/forecast/members` (admin) -> `{members:[MemberForecast]}` (one row per member; carries only `member_id`, join names from `GET /api/members`).
- `POST /api/notifications/low-balance-scan` (admin, `X-Requested-With`) -> `{scanned,below,queued,suppressed}` (`LowBalanceScanResult`). Enqueues warning emails; drain with `POST /api/notifications/process`.
- `POST /api/notifications/{id}/requeue` (admin, `X-Requested-With`) -> `{message:EmailMessage}` with `status:"queued"`. Puts one `failed`/`sent` message back on the queue (`attempts` reset, due now). 422 `not_requeueable` if it is already `queued`; 404 `not_found`. Enqueue only. Drives the per-row **Legg i kø igjen** button on `SystemHealth`.

### Release 1D — refunds, corrections, departure, charging access

- `POST /api/members/{id}/refunds` (admin, `X-Requested-With`) `{amount:"250.00",value_date?,reference?,allow_negative?:boolean}` -> a `refund` `Txn` (negative `amount_ore`); 422 `refund_exceeds_balance` unless `allow_negative`, 422 `validation_error` on amount<=0. `TxnType` now also includes `"refund"` and `"settlement_correction"`.
- `GET /api/settlement/{id}/correction` (admin) -> `CorrectionAssessment` — recompute a **posted** settlement from current usage vs the frozen lines/participation. `members[]` carries `charged_ore` (already charged, net), `corrected_charge_ore`, `delta_ore` (`= charged − corrected`; positive ⇒ credit to member), `consumption_kwh_before/after`, `in_snapshot`. 422 `not_posted` for a draft.
- `POST /api/settlement/{id}/correction` (admin, `X-Requested-With`) -> the assessment plus `{correction_id,sequence,members_adjusted,emails_queued}`; 422 `no_correction_needed` when nothing changed. Writes one `settlement_correction` ledger row per adjusted member and one email each.
- `GET /api/settlement/{id}` now also returns `corrections:SettlementCorrection[]` and, for a posted settlement, `correction_pending:boolean`.
- `GET /api/members/{id}/departure-check?effective_date=YYYY-MM-DD` (admin) -> `DepartureCheck` `{current_status,open_assignments:[{charger_id,charger_name,effective_from}],unsettled_months:string[],balance_ore,balance_nok,would_refund_ore}` (defaults to today).
- `POST /api/members/{id}/departure` (admin, `X-Requested-With`) `{effective_date,refund?:boolean,refund_reference?}` -> `DepartureResult` (check + `{status_changed,assignments_closed:number[],refund_txn_id:number|null,refunded_ore}`); 422 `unsettled_consumption` when `refund` is requested and any month is still unsettled.
- `GET /api/members/{id}/access` (admin) -> `{member_id,status:"warned"|"disabled"|"restored"|null,history:AccessEvent[]}`.
- `POST /api/members/{id}/access` (admin, `X-Requested-With`) `{action:"warned"|"disabled"|"restored",reason?,note?}` -> `{member_id,status,event:AccessEvent,history:AccessEvent[]}`. `warned`/`restored` also enqueue a member email; `disabled` does not. **No live Zaptec enforcement — status of record only.**
- `GET /api/me/access` (member) -> `{status:AccessAction|null,portal_url:string}` — drives the portal banner + Zaptec link.
- `GET /api/system/health` gains `corrections:{settlements_with_pending:number}` and `access:{disabled:number}` (informational; do not flip `ok`), plus `scheduler:{enabled:boolean,jobs:JobSchedule[]}` (a job in `last_status:"error"` **does** flip `ok`).
- `AccessEvent = {id,member_id,action,reason:string|null,note:string|null,created_at,created_by_user_id:number|null,email_message_id:number|null}`.

### Background jobs (in-process scheduler, admin)

- `GET /api/system/jobs` -> `{jobs:JobSchedule[]}` (the four seeded rows).
- `PUT /api/system/jobs/{name}` (admin, `X-Requested-With`) partial `{enabled?:boolean,cron?:string}` -> `JobSchedule`. Empty body 422 `validation_error`; unknown `name` 422 `unknown_job`; invalid 5-field cron 422 `bad_cron`. Disabling clears `next_run_at`.
- `POST /api/system/jobs/{name}/run` (admin, `X-Requested-With`) -> `{name,status:"ok"|"error",error:string|null,duration_ms:number,summary:object}`; runs the job now with the same bookkeeping. 422 `unknown_job`.
- `JobSchedule = {name:"drain_mail"|"low_balance_scan"|"gmail_token_check"|"zaptec_sync_sessions",enabled:boolean,cron:string,last_run_at:string|null,last_status:"ok"|"error"|"running"|null,last_error:string|null,last_duration_ms:number|null,next_run_at:string|null,updated_at:string|null,updated_by_user_id:number|null}`. `cron` is UTC. Missed slots are not replayed.

### Types

- `Member = {id,member_reference,full_name,email:string|null,join_date,created_at,updated_at,status:"active"|"inactive"|null,participates:boolean|null,balance_ore?:number|null,balance_nok?:string|null}` — balance fields are populated on `GET /api/members` and `GET /api/members/{id}`.
- `StatusPeriod = {id,status,effective_from,effective_to:string|null,note:string|null,created_at}`
- `ParticipationPeriod = {id,participates:boolean,effective_from,effective_to:string|null,reason:string|null,created_at}`
- `Txn = {id,member_id,txn_type:"payment"|"payment_reversal"|"adjustment_credit"|"adjustment_debit",amount_ore:number,amount_nok:string,currency,value_date,reason:string|null,reference:string|null,reverses_transaction_id:number|null,created_by_user_id,recorded_at}`
- `LedgerTxnRow = Txn & {member_name:string,member_reference:string}` — rows from `GET /api/ledger-transactions`. `txn_type` there may also be `"settlement_charge"`/`"settlement_reversal"`.
- `AuditEvent = {id,occurred_at,actor_user_id:number|null,actor_label,actor_role:string|null,event_type,entity_type,entity_id:string|null,summary,detail:object|null,ip:string|null,user_agent:string|null}`
- `MySettlement = {settlement_id,period_month,posted_at:string|null,is_draft:boolean,draft_shared_at:string|null,consumption_kwh:string,charge_nok:string,balance_after_nok:string,report_url:string}` — `is_draft` is a frozen settlement the board shared for preview; its report is watermarked `UTKAST` and the numbers are not final.
- `SettlementAttachment = {id:number,filename:string,bytes:number,uploaded_at:string}`; `SettlementDetail` gains `attachments:SettlementAttachment[]`.
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
