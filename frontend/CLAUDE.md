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

### Types

- `Member = {id,member_reference,full_name,email:string|null,join_date,created_at,updated_at,status:"active"|"inactive"|null,participates:boolean|null}`
- `StatusPeriod = {id,status,effective_from,effective_to:string|null,note:string|null,created_at}`
- `ParticipationPeriod = {id,participates:boolean,effective_from,effective_to:string|null,reason:string|null,created_at}`
- `Txn = {id,member_id,txn_type:"payment"|"payment_reversal"|"adjustment_credit"|"adjustment_debit",amount_ore:number,amount_nok:string,currency,value_date,reason:string|null,reference:string|null,reverses_transaction_id:number|null,created_by_user_id,recorded_at}`
- `AuditEvent = {id,occurred_at,actor_user_id:number|null,actor_label,event_type,entity_type,entity_id:string|null,summary,detail:object|null,ip:string|null}`

## Status

- G1 (scaffold + auth shell): PASS
- G2 (members + status + participation): PASS
- G3 (ledger + audit log): PASS
- G4 (member portal): PASS

`npm run check` (tsc + eslint + 20 vitest) and `npm run build` both green.
