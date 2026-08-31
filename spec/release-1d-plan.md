# Release 1D — build plan

Product scope (`spec.md` Release 1D): **Corrections, Refunds, Member departure,
Charging-access workflows.**

Architecture and prior decisions: [`implementation-plan.md`](./implementation-plan.md),
[`release-1b-plan.md`](./release-1b-plan.md), [`release-1c-plan.md`](./release-1c-plan.md).
This document is the executable build plan for 1D.

Target version: **`0.5.0`** (`VERSION` + `pyproject.toml` in lockstep).
`0.4.0` is the already-committed "user provisioning + movements" batch
(`87d5c06`); several of its new files are untracked in the working tree and are
**left as-is** — out of scope for 1D.

## Status — COMPLETE (2026-08-31)

All of P1–P8 shipped. 347 pytest tests + 53 Vitest tests green; `ruff check` /
`ruff format --check` clean; `npm run build` green. Committed directly to `main`
(mirrors 1A/1B/1C).

| Phase | Scope | State | Commit |
|---|---|---|---|
| **P1** | Ledger: `refund` + `settlement_correction` txn types, migration `0010` | ☑ done | `519d541` |
| **P2** | API: member refunds (US-505) | ☑ done | `321899f` |
| **P3** | Settlement corrections engine (Epic 7 — US-701/702/703) | ☑ done | `df86ef3` |
| **P4** | API: correction endpoints + member notifications | ☑ done | `eef7a70` |
| **P5** | Member departure workflow (US-204) | ☑ done | `661bfce` |
| **P6** | Charging-access status + notifications (US-305, US-1003/1004) | ☑ done | `fa74b13` |
| **P7** | Web UI — corrections, refunds, departure, access | ☑ done | `c5a9412` |
| **P8** | Docs / version bump `0.5.0` | ☑ done | (this commit) |

### Deviations from this plan as written

- **US-505 uses a dedicated `refund` `txn_type`**, not the reserved
  `settlement_reversal` (which stays unused) — a refund and a settlement reversal
  are semantically different and the report/label code keys off the type.
- **The overdraw guard lives in `LedgerRepo.refund`** (`allow_negative` kwarg),
  not only the route, so `process_departure` gets it for free.
- **`assess_correction` derives the "already charged" baseline from the ledger**
  (`−SUM(amount_ore)` over the settlement's rows), not from a stored original, so
  a second correction nets against the first with no extra bookkeeping.
- **Charging access is its own router** (`routes/access.py`, `prefix=/api/members`)
  registered right after `members`, rather than folded into the members router.
- **P8 status-table + version bump is this commit**; P1–P7 each landed as a
  single commit (no per-phase `docs:` follow-ups this time).

**Done** = `uv run ruff check src tests` + `uv run ruff format --check` +
`uv run pytest -q` green (and `npm run check` from P7). Behaviour-changing items
touch `CHANGELOG.md`. Committed directly to `main` (mirrors 1A/1B/1C).

---

## Scope by user story

| US | Title | 1D work |
|---|---|---|
| US-204 | Member departure | `departure-check` preview + `POST /api/members/{id}/departure` orchestrating status→inactive, closing every open charger assignment, unsettled-consumption detection, and an optional full-balance refund. Nothing deleted. |
| US-305 | Charging-access status | `charging_access_events` log + `warned` / `disabled` / `restored` actions, each audited; member-portal banner + Zaptec portal link. **Recorded status + notifications only — live Zaptec enforcement stays Release 2 ("Direct Zaptec access control").** |
| US-505 | Refund member balance | `refund` ledger txn (lowers balance), optional accounting reference, audit `ledger.refunded`, overdraw guard with an explicit `allow_negative` override. |
| US-701 | Assess correction impact | `SettlementRepo.assess_correction` — recompute a posted settlement's allocations from **current** imported usage against its **frozen** invoice lines + frozen equal-cost participation; return the per-member diff. |
| US-702 | Calculate correction | Same call: `delta_ore = original_charge_ore − corrected_charge_ore` per member (positive ⇒ member over-charged ⇒ credit). |
| US-703 | Post correction | `post_correction` — one `settlement_correction` ledger row per changed member, a `settlement_corrections` / `settlement_correction_members` record, resolve the month's `late_session_flags`, audit `settlement.corrected`, notify each adjusted member. Original settlement untouched. |
| US-1003 | Access-removal warning | Email enqueued on the `warned` action. |
| US-1004 | Access-restored notification | Email enqueued on the `restored` action. |
| US-1104 | System health | Health payload gains `access: {disabled}` and `corrections: {settlements_with_pending}` counters. |

---

## Decisions locked for 1D

| # | Decision | Note |
|---|---|---|
| D1 | **One migration — `0010_corrections_refunds_access.sql`.** It rebuilds `ledger_transactions` (SQLite cannot `ALTER` a `CHECK`) to widen `txn_type` with `'refund'` and `'settlement_correction'`, mirroring the 0005 rebuild (drop triggers + `idx_ledger_member` / `idx_ledger_one_reversal`; create `_new`; copy every column incl. `settlement_id`; drop; rename; recreate the three indexes + both append-only triggers). It also creates `settlement_corrections`, `settlement_correction_members`, `charging_access_events`. | The existing six txn types are preserved; `settlement_reversal` stays reserved/unused. |
| D2 | **Refund** = `LedgerRepo.refund(*, member_id, amount, value_date, reference, actor)` → one `refund` row, `amount_ore = −nok_to_ore(amount)`, `reason` NULL, `reference` = optional accounting ref. Audit `ledger.refunded`. Route `POST /api/members/{id}/refunds` (`RefundIn{amount, value_date?, reference?, allow_negative=false}`) raises `refund_exceeds_balance` (422) when the refund would push the balance below zero and `allow_negative` is not set. | Money in integer øre via the existing `_ore_nok`. |
| D3 | **Correction assessment** requires `status == 'posted'`. It reuses the `compute()` allocation maths but swaps each snapshot member's `consumption_kwh` for the **current** `ChargingRepo.consumption_by_member(month)` value, and folds in any member who now has consumption but was not in the snapshot (consumption-only, `participates_equal = 0`, `is_active` from current status). Frozen invoice lines and frozen `participates_equal` are **not** re-read — participation is frozen at post time (US-203). | Pure read — no writes. |
| D4 | **Correction posting** writes, in one `_write()`: a `settlement_corrections` header (`sequence` 1-based per settlement, original/corrected totals, `basis_json`), one `settlement_correction_members` row + one `ledger_transactions` row (`txn_type='settlement_correction'`, `amount_ore = delta_ore`, `settlement_id` set, `reason = "Korrigering avregning {month} (#{seq})"`, `reference = month`) per member whose `delta_ore ≠ 0`, resolution of the month's open `late_session_flags`, and one `settlement.corrected` audit row. `no_correction_needed` (422) when every delta is zero. The posted `settlements` row and its `settlement_allocations` are untouched. | Reports are **not** regenerated — the correction email carries the numbers. |
| D5 | **Members notified** (US-703) = `NotificationRepo.enqueue_correction_reports(*, settlement_id, correction, base_url)` — one Norwegian email per adjusted member with a linked, enabled user (`template="settlement_correction"`): the delta (kr tilbakeført / kr ekstra å betale), the new balance, a portal link. The `POST` route returns `emails_queued`; drain with `/api/notifications/process`. | Mirrors `enqueue_settlement_reports`. |
| D6 | **Departure** = `MemberRepo.departure_check(member_id, *, effective_date)` → `{current_status, open_assignments, unsettled_months, balance_ore/nok}` and `MemberRepo.process_departure(member_id, *, effective_date, refund, refund_reference, actor)` → `set_status('inactive')` + `ChargerRepo.unassign` (+ re-resolve) for every open assignment + optional `LedgerRepo.refund` of the whole positive balance. `unsettled_months` (months ≤ `effective_date` with the member's sessions and no posted settlement) **block** a refund unless there are none; a non-positive balance simply skips the refund. One `member.departed` audit row summarises everything. | Historical rows are only effective-dated closed, never deleted. |
| D7 | **Charging access** = `AccessRepo` over `charging_access_events(member_id, action ∈ {warned,disabled,restored}, reason, note, created_at, created_by_user_id, email_message_id)`. `record()` enqueues the US-1003 email on `warned` and the US-1004 email on `restored`, links `email_message_id`, and audits `access.{action}`. `current(member_id)` = the latest event's action (or `None`). Routes `GET|POST /api/members/{id}/access`; portal `GET /api/me/access` → `{status, portal_url}`. `ZaptecConfig` gains `portal_url: str = "https://portal.zaptec.com"`. **No Zaptec write call — Release 2 owns enforcement.** | |
| D8 | **Health** gains `access: {disabled}` (distinct members whose latest access event is `disabled`) and `corrections: {settlements_with_pending}` (posted settlements whose `assess_correction` currently reports `has_changes`). Informational — they do **not** flip `ok`. | Computed on demand. |
| D9 | **Version `0.5.0`.** `VERSION` + `pyproject.toml` in lockstep; consolidated `CHANGELOG.md` "Release 1D" entry above any per-phase entries. | |

---

## Data model additions — `migrations/0010_corrections_refunds_access.sql`

```sql
-- 1. widen ledger_transactions.txn_type  (rebuild — see decision D1)
--    new members of the CHECK set: 'refund', 'settlement_correction'

CREATE TABLE settlement_corrections (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id       INTEGER NOT NULL REFERENCES settlements (id),
    sequence            INTEGER NOT NULL,          -- 1-based, per settlement
    original_total_ore  INTEGER NOT NULL,
    corrected_total_ore INTEGER NOT NULL,
    basis_json          TEXT,                      -- full assessment dict
    created_at          TEXT NOT NULL,
    created_by_user_id  INTEGER REFERENCES users (id)
);
CREATE UNIQUE INDEX idx_scorr_seq ON settlement_corrections (settlement_id, sequence);

CREATE TABLE settlement_correction_members (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id          INTEGER NOT NULL REFERENCES settlement_corrections (id),
    member_id              INTEGER NOT NULL REFERENCES members (id),
    consumption_kwh_before TEXT NOT NULL,
    consumption_kwh_after  TEXT NOT NULL,
    original_charge_ore    INTEGER NOT NULL,
    corrected_charge_ore   INTEGER NOT NULL,
    delta_ore              INTEGER NOT NULL,
    ledger_txn_id          INTEGER REFERENCES ledger_transactions (id)
);
CREATE INDEX idx_scm_correction ON settlement_correction_members (correction_id, member_id);

CREATE TABLE charging_access_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id          INTEGER NOT NULL REFERENCES members (id),
    action             TEXT NOT NULL CHECK (action IN ('warned', 'disabled', 'restored')),
    reason             TEXT,
    note               TEXT,
    created_at         TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users (id),
    email_message_id   INTEGER REFERENCES email_messages (id)
);
CREATE INDEX idx_cae_member ON charging_access_events (member_id, id DESC);
```

---

## Ordered work items (one reviewable commit each)

| # | Commit | Scope | User stories |
|---|---|---|---|
| **P1** | `feat(ledger): refunds + correction ledger types` | `migrations/0010_*` (full file — ledger rebuild + all three new tables); `LedgerRepo.refund`; `domain/ledger.py` type maps; `test_migrations.py` (widened CHECK accepts `refund` / `settlement_correction`, three tables + indexes present, ledger still append-only), `test_ledger.py` (refund lowers balance, `ledger.refunded` audit, overdraw guard at the repo returns the row / route enforces). | US-505 (engine) |
| **P2** | `feat(api): member refunds (US-505)` | `schemas.py` `RefundIn`; `routes/ledger.py` `POST /api/members/{id}/refunds`; `tests/unit/test_refunds_api.py` (happy path, optional reference, `refund_exceeds_balance`, `allow_negative` override, CSRF, RBAC). | US-505 |
| **P3** | `feat(settlement): corrections engine (Epic 7)` | `domain/settlement.py` — `assess_correction(settlement_id)`, `post_correction(settlement_id, *, actor)`, `corrections(settlement_id)`, `_current_consumption_snapshot` helper; `tests/unit/test_settlement_corrections.py` (no-change → `has_changes False`; a new late session shifts one member's share → correct `delta_ore` split, ledger rows, `settlement_corrections` rows, `late_session_flags` resolved, `no_correction_needed` guard, original settlement + allocations unchanged, sequence increments). | US-701, US-702, US-703 |
| **P4** | `feat(api): settlement correction endpoints + notify` | `routes/settlement.py` — `GET /api/settlement/{id}/correction` (assessment), `POST /api/settlement/{id}/correction` (`require_fetch`); `NotificationRepo.enqueue_correction_reports`; `tests/unit/test_settlement_correction_api.py` (assess shape, post → ledger + `emails_queued`, second post no-op 422, member 403). | US-703 |
| **P5** | `feat(members): departure workflow (US-204)` | `domain/members.py` — `departure_check`, `process_departure` (uses `ChargerRepo`, `LedgerRepo`, `ChargingRepo`); `routes/members.py` — `GET /api/members/{id}/departure-check`, `POST /api/members/{id}/departure` (`DepartureIn`); `schemas.py`; `tests/unit/test_member_departure.py` (check lists open assignments + unsettled months + balance; process closes assignments + sets inactive + refunds; refund blocked by unsettled month; non-positive balance skips refund; `member.departed` audit). | US-204 |
| **P6** | `feat(access): charging-access status + notifications` | `domain/access.py` `AccessRepo`; `routes/access.py` (mounted in `app.py`) `GET|POST /api/members/{id}/access`; `routes/me.py` `GET /api/me/access`; `config.py` `ZaptecConfig.portal_url`; `domain/notifications.py` `enqueue_access_warning` / `enqueue_access_restored`; `routes/system.py` health `access` + `corrections` counters; `schemas.py` (`AccessActionIn`, `AccessEventOut`); `tests/unit/test_charging_access.py` (warn → event + queued email + audit; disable → event, no email; restore → queued email; `current` reflects latest; `/api/me/access` carries `portal_url`; member 403 on the admin routes). | US-305, US-1003, US-1004, US-1104 |
| **P7** | `feat(web): Release 1D — corrections, refunds, departure, access` | `api/client.ts` wrappers + types (`Refund`, `CorrectionAssessment`, `DepartureCheck`, `AccessEvent`, extended `TxnType`, `SystemHealth`); `pages/MemberDetail.tsx` — Refund action in the ledger card, an "Utmelding" card (check → confirm), a "Ladetilgang" card (warn / disable / restore + history); `pages/SettlementDetail.tsx` — a "Korrigering" panel for posted settlements (assess table → confirm post → result); `pages/MyAccount.tsx` — access-status banner + Zaptec portal link; `pages/SystemHealth.tsx` — access / corrections counters; MSW handlers + Vitest for every new call; `frontend/CLAUDE.md` contract section. | US-204/305/505/701–703/1003/1004 |
| **P8** | `docs: Release 1D` | `README.md` status → 1D + the correction / departure / access workflows + the (unchanged) cron block; consolidated `CHANGELOG.md` "Release 1D" entry; `VERSION` + `pyproject.toml` → `0.5.0`; `spec/implementation-plan.md` status (1D **COMPLETE**); `src/ladelaug_avregning/webapp/CLAUDE.md` contract additions; mark every phase ☑ in this file with its commit hash. | — |

Dependency order: **P1 → P2, P3, P5, P6**; **P3 → P4**; **P7** needs P2/P4/P5/P6;
**P8** last.

---

## Residual risks

- **`ledger_transactions` rebuild** — third rebuild of this table (0001 → 0005 → 0010).
  The 0005 pattern is copied verbatim; `test_migrations.py` re-asserts append-only
  triggers + `idx_ledger_one_reversal` after 0010, and a fresh `migrate` on a
  populated dev DB is part of the P1 check.
- **Correction double-counting** — a `settlement_correction` row is itself a ledger
  entry, so a *second* `assess_correction` must compare against the **original**
  frozen `settlement_allocations` charge, never "balance now". The engine derives
  `original_charge_ore` from `settlement_allocations` (or the frozen snapshot's
  computed charge), not from the live balance.
- **Participation drift into a correction** — `assess_correction` re-reads only
  *consumption*; `participates_equal` and the invoice lines stay frozen, so a
  correction can never silently re-split the equal-cost lines because someone's
  participation flag changed after the post.
- **Departure refund vs. unsettled usage** — `process_departure` refuses a refund
  while any month ≤ the leaving date still has the member's sessions outside a
  posted settlement (`unsettled_consumption`, 422). The admin settles or corrects
  first, then re-runs departure.
- **Access enforcement is advisory** — 1D only records intent and notifies. The
  member can still charge until an admin acts in the Zaptec portal. The portal
  link and the banner make that explicit; `README` and `CHANGELOG` say so.
- **Refund overdraw** — blocked by default; `allow_negative: true` is the audited
  escape hatch (e.g. correcting an earlier over-charge).

---

## Manual verification checklist (hand back to the user)

1. `uv run python -m ladelaug_avregning migrate` against a copy of the live DB →
   `0010` applies; `sqlite3 … "PRAGMA integrity_check"` clean; a manual
   `UPDATE ledger_transactions …` still raises *append-only*.
2. Record a refund for a member with a positive balance → balance drops by the
   refund; `Bevegelser` shows a `Refusjon` row; audit `ledger.refunded`. A refund
   larger than the balance is refused unless "tillat negativ saldo" is ticked.
3. Post a settlement, import one more session for that month, open the settlement →
   "Korrigering tilgjengelig"; **Vurder korrigering** shows the per-member kWh
   before/after and the delta; **Bokfør korrigering** writes one
   `settlement_correction` per changed member, queues one email each, and resolves
   the month's late-session flags. A second **Bokfør** with no new data → 422.
4. `POST /api/notifications/process` → the corrected-settlement emails send.
5. Member departure: pick a leaving date, **Sjekk utmelding** lists open chargers +
   any unsettled month + the balance; **Meld ut** sets the member inactive from
   that date, closes every charger assignment, and (if asked, and nothing is
   unsettled) refunds the remaining balance — all under one `member.departed`
   audit row.
6. Charging access: **Send varsel** on a member → a `charging_access_events` row +
   a queued US-1003 email; **Steng** → recorded, banner on the member's "Min
   konto"; **Gjenåpne** → queued US-1004 email. The banner links the Zaptec
   portal. No charging is actually blocked (documented).
7. `GET /api/system/health` → `access.disabled` and `corrections.settlements_with_pending`
   reflect the above.
