import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type {
  AuditEvent,
  AuthUser,
  LedgerTxn,
  Member,
  ParticipationPeriod,
  StatusPeriod,
} from "../api/client";

// --- fixtures & mock state ------------------------------------------
// Shapes here mirror the backend contract in frontend/CLAUDE.md. Keep them
// honest — a drifting handler makes the tests that assert against it worthless.

export const TEST_PASSWORD = "hunter2";

export const ADMIN_USER: AuthUser = {
  id: 1,
  email: "admin@example.com",
  role: "admin",
  member_id: null,
  disabled: false,
};

export const MEMBER_USER: AuthUser = {
  id: 2,
  email: "member@example.com",
  role: "member",
  member_id: 7,
  disabled: false,
};

const ACCOUNTS: AuthUser[] = [ADMIN_USER, MEMBER_USER];

interface MockState {
  session: AuthUser | null;
  members: Map<number, Member>;
  statusHistory: Map<number, StatusPeriod[]>;
  participationHistory: Map<number, ParticipationPeriod[]>;
  ledger: Map<number, LedgerTxn[]>;
  audit: AuditEvent[];
  seq: number;
}

function freshState(): MockState {
  return {
    session: null,
    members: new Map(),
    statusHistory: new Map(),
    participationHistory: new Map(),
    ledger: new Map(),
    audit: [],
    seq: 100,
  };
}

let state: MockState = freshState();

export function resetMockState(): void {
  state = freshState();
  mock1b = freshMock1b();
}

export function setSession(user: AuthUser | null): void {
  state.session = user;
}

const nextId = () => ++state.seq;

// --- money helpers (integer øre canonical) ---------------------------

export function nokToOre(value: string): number {
  const trimmed = value.trim();
  const neg = trimmed.startsWith("-");
  const [int, frac = ""] = trimmed.replace(/^-/, "").split(".");
  const ore = parseInt(int || "0", 10) * 100 + parseInt((frac + "00").slice(0, 2), 10);
  return neg ? -ore : ore;
}

export function oreToNok(ore: number): string {
  const sign = ore < 0 ? "-" : "";
  const abs = Math.abs(ore);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

// --- seed helpers ---------------------------------------------------

export function seedMember(overrides: Partial<Member> = {}): Member {
  const id = overrides.id ?? nextId();
  const now = "2024-01-01T09:00:00Z";
  const member: Member = {
    id,
    member_reference: overrides.member_reference ?? `M-${id}`,
    full_name: overrides.full_name ?? `Member ${id}`,
    email: overrides.email ?? null,
    join_date: overrides.join_date ?? "2024-01-01",
    created_at: overrides.created_at ?? now,
    updated_at: overrides.updated_at ?? now,
    status: overrides.status ?? "active",
    participates: overrides.participates ?? true,
  };
  state.members.set(id, member);
  if (!state.statusHistory.has(id)) {
    state.statusHistory.set(id, [
      {
        id: nextId(),
        status: member.status ?? "active",
        effective_from: member.join_date,
        effective_to: null,
        note: null,
        created_at: now,
      },
    ]);
  }
  if (!state.participationHistory.has(id)) {
    state.participationHistory.set(id, []);
  }
  if (!state.ledger.has(id)) state.ledger.set(id, []);
  return member;
}

export function seedLedgerTxn(
  memberId: number,
  overrides: Partial<LedgerTxn> = {},
): LedgerTxn {
  const id = overrides.id ?? nextId();
  const amountOre = overrides.amount_ore ?? 150000;
  const txn: LedgerTxn = {
    id,
    member_id: memberId,
    txn_type: overrides.txn_type ?? "payment",
    amount_ore: amountOre,
    amount_nok: overrides.amount_nok ?? oreToNok(amountOre),
    currency: overrides.currency ?? "NOK",
    value_date: overrides.value_date ?? "2024-02-01",
    reason: overrides.reason ?? null,
    reference: overrides.reference ?? null,
    reverses_transaction_id: overrides.reverses_transaction_id ?? null,
    created_by_user_id: overrides.created_by_user_id ?? 1,
    recorded_at: overrides.recorded_at ?? "2024-02-01T10:00:00Z",
  };
  const list = state.ledger.get(memberId) ?? [];
  list.push(txn);
  state.ledger.set(memberId, list);
  return txn;
}

export function seedAuditEvent(overrides: Partial<AuditEvent> = {}): AuditEvent {
  const id = overrides.id ?? nextId();
  const event: AuditEvent = {
    id,
    occurred_at: overrides.occurred_at ?? `2024-03-01T10:00:${String(id % 60).padStart(2, "0")}Z`,
    actor_user_id: overrides.actor_user_id ?? 1,
    actor_label: overrides.actor_label ?? "admin@example.com",
    event_type: overrides.event_type ?? "member.created",
    entity_type: overrides.entity_type ?? "member",
    entity_id: overrides.entity_id ?? "1",
    summary: overrides.summary ?? "Something happened",
    detail: overrides.detail ?? null,
    ip: overrides.ip ?? null,
  };
  state.audit.push(event);
  return event;
}

function recordAudit(
  eventType: string,
  entityType: string,
  entityId: string,
  summary: string,
): void {
  seedAuditEvent({
    event_type: eventType,
    entity_type: entityType,
    entity_id: entityId,
    summary,
  });
}

// --- helpers ------------------------------------------------------

function errorBody(code: string, message: string) {
  return { detail: { code, message } };
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function requireAdmin(): Response | null {
  if (!state.session) {
    return HttpResponse.json(errorBody("not_authenticated", "Not authenticated"), {
      status: 401,
    });
  }
  if (state.session.role !== "admin") {
    return HttpResponse.json(errorBody("forbidden", "Admin only"), { status: 403 });
  }
  return null;
}

function ledgerBalanceOre(memberId: number): number {
  return (state.ledger.get(memberId) ?? []).reduce((sum, t) => sum + t.amount_ore, 0);
}

function closePreviousPeriod<T extends { effective_to: string | null }>(
  periods: T[],
  effectiveFrom: string,
): void {
  const open = periods.find((p) => p.effective_to === null);
  if (open) open.effective_to = effectiveFrom;
}

const today = () => new Date().toISOString().slice(0, 10);

// --- handlers ---------------------------------------------------

export const handlers = [
  // --- auth -----------------------------------------------------
  http.get("/api/auth/me", () => {
    if (!state.session) {
      return HttpResponse.json(errorBody("not_authenticated", "Not authenticated"), {
        status: 401,
      });
    }
    return HttpResponse.json({ ...state.session, version: "test" });
  }),

  http.post("/api/auth/login", async ({ request }) => {
    if (request.headers.get("x-requested-with") !== "fetch") {
      return HttpResponse.json(errorBody("csrf", "Missing X-Requested-With"), {
        status: 403,
      });
    }
    const body = (await request.json()) as { email: string; password: string };
    const found = ACCOUNTS.find((a) => a.email === body.email);
    if (!found || body.password !== TEST_PASSWORD) {
      return HttpResponse.json(
        errorBody("not_authenticated", "Invalid email or password"),
        { status: 401 },
      );
    }
    state.session = found;
    return HttpResponse.json({ user: found });
  }),

  http.post("/api/auth/logout", () => {
    state.session = null;
    return HttpResponse.json({ ok: true });
  }),

  // --- members ------------------------------------------------
  http.get("/api/members", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    return HttpResponse.json({
      members: [...state.members.values()].sort((a, b) => a.id - b.id),
    });
  }),

  http.post("/api/members", async ({ request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const body = (await request.json()) as {
      member_reference: string;
      full_name: string;
      email?: string | null;
      join_date: string;
    };
    if (body.email && !EMAIL_RE.test(body.email)) {
      return HttpResponse.json(
        errorBody("validation_error", "email: not a valid email address"),
        { status: 422 },
      );
    }
    if (!body.member_reference?.trim() || !body.full_name?.trim()) {
      return HttpResponse.json(
        errorBody("validation_error", "member_reference and full_name are required"),
        { status: 422 },
      );
    }
    const taken = [...state.members.values()].some(
      (m) => m.member_reference === body.member_reference,
    );
    if (taken) {
      return HttpResponse.json(
        errorBody("reference_taken", "member_reference already in use"),
        { status: 422 },
      );
    }
    const member = seedMember({
      member_reference: body.member_reference,
      full_name: body.full_name,
      email: body.email || null,
      join_date: body.join_date,
      status: "active",
      participates: true,
    });
    recordAudit(
      "member.created",
      "member",
      String(member.id),
      `Member ${member.member_reference} created`,
    );
    return HttpResponse.json(member, { status: 201 });
  }),

  http.get("/api/members/:id", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const member = state.members.get(Number(params.id));
    if (!member) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    return HttpResponse.json(member);
  }),

  http.patch("/api/members/:id", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const member = state.members.get(Number(params.id));
    if (!member) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    const body = (await request.json()) as Partial<Member>;
    if (body.email && !EMAIL_RE.test(body.email)) {
      return HttpResponse.json(
        errorBody("validation_error", "email: not a valid email address"),
        { status: 422 },
      );
    }
    const updated: Member = {
      ...member,
      ...(body.member_reference !== undefined
        ? { member_reference: body.member_reference }
        : {}),
      ...(body.full_name !== undefined ? { full_name: body.full_name } : {}),
      ...(body.email !== undefined ? { email: body.email || null } : {}),
      ...(body.join_date !== undefined ? { join_date: body.join_date } : {}),
      updated_at: new Date().toISOString(),
    };
    state.members.set(member.id, updated);
    recordAudit(
      "member.updated",
      "member",
      String(member.id),
      `Member ${updated.member_reference} updated`,
    );
    return HttpResponse.json(updated);
  }),

  http.post("/api/members/:id/status", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const member = state.members.get(Number(params.id));
    if (!member) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    const body = (await request.json()) as {
      status: "active" | "inactive";
      effective_from?: string;
      note?: string;
    };
    if (body.status === member.status) {
      return HttpResponse.json(
        errorBody("status_unchanged", "member already has that status"),
        { status: 422 },
      );
    }
    const periods = state.statusHistory.get(member.id) ?? [];
    const effectiveFrom = body.effective_from ?? today();
    closePreviousPeriod(periods, effectiveFrom);
    const period: StatusPeriod = {
      id: nextId(),
      status: body.status,
      effective_from: effectiveFrom,
      effective_to: null,
      note: body.note?.trim() || null,
      created_at: new Date().toISOString(),
    };
    periods.push(period);
    state.statusHistory.set(member.id, periods);
    state.members.set(member.id, { ...member, status: body.status });
    recordAudit(
      "member.status_changed",
      "member",
      String(member.id),
      `Status set to ${body.status}`,
    );
    return HttpResponse.json({ period });
  }),

  http.get("/api/members/:id/status-history", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const member = state.members.get(Number(params.id));
    if (!member) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    return HttpResponse.json({
      periods: [...(state.statusHistory.get(member.id) ?? [])].sort(
        (a, b) => a.effective_from.localeCompare(b.effective_from) || a.id - b.id,
      ),
    });
  }),

  http.post("/api/members/:id/participation", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const member = state.members.get(Number(params.id));
    if (!member) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    const body = (await request.json()) as {
      participates: boolean;
      effective_from?: string;
      reason?: string;
    };
    if (body.participates === member.participates) {
      return HttpResponse.json(
        errorBody("participation_unchanged", "participation already set to that value"),
        { status: 422 },
      );
    }
    const periods = state.participationHistory.get(member.id) ?? [];
    const effectiveFrom = body.effective_from ?? today();
    closePreviousPeriod(periods, effectiveFrom);
    const period: ParticipationPeriod = {
      id: nextId(),
      participates: body.participates,
      effective_from: effectiveFrom,
      effective_to: null,
      reason: body.reason?.trim() || null,
      created_at: new Date().toISOString(),
    };
    periods.push(period);
    state.participationHistory.set(member.id, periods);
    state.members.set(member.id, { ...member, participates: body.participates });
    recordAudit(
      "member.participation_changed",
      "member",
      String(member.id),
      `Participation set to ${body.participates}`,
    );
    return HttpResponse.json({ period });
  }),

  http.get("/api/members/:id/participation-history", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const member = state.members.get(Number(params.id));
    if (!member) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    return HttpResponse.json({
      periods: [...(state.participationHistory.get(member.id) ?? [])].sort(
        (a, b) => a.effective_from.localeCompare(b.effective_from) || a.id - b.id,
      ),
    });
  }),

  // --- ledger (admin) ---------------------------------------
  http.get("/api/members/:id/balance", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const memberId = Number(params.id);
    if (!state.members.has(memberId)) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    const ore = ledgerBalanceOre(memberId);
    return HttpResponse.json({
      member_id: memberId,
      balance_nok: oreToNok(ore),
      balance_ore: ore,
    });
  }),

  http.get("/api/members/:id/ledger", ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const memberId = Number(params.id);
    if (!state.members.has(memberId)) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    return ledgerPage(memberId, request.url);
  }),

  http.post("/api/members/:id/payments", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const memberId = Number(params.id);
    if (!state.members.has(memberId)) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    const body = (await request.json()) as {
      amount: string;
      value_date?: string;
      reference?: string;
    };
    const ore = nokToOre(body.amount ?? "0");
    if (!Number.isFinite(ore) || ore <= 0) {
      return HttpResponse.json(
        errorBody("validation_error", "amount must be positive"),
        { status: 422 },
      );
    }
    const txn = seedLedgerTxn(memberId, {
      txn_type: "payment",
      amount_ore: ore,
      amount_nok: oreToNok(ore),
      value_date: body.value_date ?? today(),
      reference: body.reference?.trim() || null,
      recorded_at: new Date().toISOString(),
    });
    recordAudit(
      "ledger.payment_recorded",
      "ledger_transaction",
      String(txn.id),
      `Payment ${txn.amount_nok} NOK recorded for member ${memberId}`,
    );
    return HttpResponse.json(txn, { status: 201 });
  }),

  http.post("/api/members/:id/adjustments", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const memberId = Number(params.id);
    if (!state.members.has(memberId)) {
      return HttpResponse.json(errorBody("not_found", "member not found"), {
        status: 404,
      });
    }
    const body = (await request.json()) as {
      direction: "credit" | "debit";
      amount: string;
      reason: string;
      reference?: string;
    };
    if (!body.reason?.trim()) {
      return HttpResponse.json(
        errorBody("validation_error", "reason: must not be empty"),
        { status: 422 },
      );
    }
    const magnitude = nokToOre(body.amount ?? "0");
    if (!Number.isFinite(magnitude) || magnitude <= 0) {
      return HttpResponse.json(
        errorBody("validation_error", "amount must be positive"),
        { status: 422 },
      );
    }
    const signed = body.direction === "credit" ? magnitude : -magnitude;
    const txn = seedLedgerTxn(memberId, {
      txn_type: body.direction === "credit" ? "adjustment_credit" : "adjustment_debit",
      amount_ore: signed,
      amount_nok: oreToNok(signed),
      value_date: today(),
      reason: body.reason.trim(),
      reference: body.reference?.trim() || null,
      recorded_at: new Date().toISOString(),
    });
    recordAudit(
      "ledger.adjusted",
      "ledger_transaction",
      String(txn.id),
      `Adjustment (${body.direction}) ${txn.amount_nok} NOK for member ${memberId}`,
    );
    return HttpResponse.json(txn, { status: 201 });
  }),

  http.post("/api/ledger-transactions/:txnId/reverse", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const txnId = Number(params.txnId);
    let original: LedgerTxn | undefined;
    let memberId: number | undefined;
    for (const [mid, list] of state.ledger) {
      const found = list.find((t) => t.id === txnId);
      if (found) {
        original = found;
        memberId = mid;
        break;
      }
    }
    if (!original || memberId === undefined) {
      return HttpResponse.json(errorBody("not_found", "ledger transaction not found"), {
        status: 404,
      });
    }
    if (original.txn_type !== "payment") {
      return HttpResponse.json(errorBody("not_a_payment", "only payments can be reversed"), {
        status: 422,
      });
    }
    const alreadyReversed = (state.ledger.get(memberId) ?? []).some(
      (t) => t.reverses_transaction_id === txnId,
    );
    if (alreadyReversed) {
      return HttpResponse.json(
        errorBody("already_reversed", `payment #${txnId} is already reversed`),
        { status: 422 },
      );
    }
    const reversal = seedLedgerTxn(memberId, {
      txn_type: "payment_reversal",
      amount_ore: -original.amount_ore,
      amount_nok: oreToNok(-original.amount_ore),
      value_date: today(),
      reverses_transaction_id: txnId,
      recorded_at: new Date().toISOString(),
    });
    recordAudit(
      "ledger.payment_reversed",
      "ledger_transaction",
      String(reversal.id),
      `Payment #${txnId} reversed for member ${memberId}`,
    );
    return HttpResponse.json(reversal, { status: 201 });
  }),

  // --- audit log (admin) ---------------------------------
  http.get("/api/audit-events", ({ request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const url = new URL(request.url);
    const eventType = url.searchParams.get("event_type");
    const entityType = url.searchParams.get("entity_type");
    const entityId = url.searchParams.get("entity_id");
    const sortBy = url.searchParams.get("sort_by") ?? "occurred_at";
    const sortDir = url.searchParams.get("sort_dir") ?? "desc";
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const offset = Number(url.searchParams.get("offset") ?? "0");

    let events = [...state.audit];
    if (eventType) events = events.filter((e) => e.event_type === eventType);
    if (entityType) events = events.filter((e) => e.entity_type === entityType);
    if (entityId) events = events.filter((e) => e.entity_id === entityId);

    events.sort((a, b) => {
      const key = sortBy === "id" ? "id" : sortBy === "event_type" ? "event_type" : "occurred_at";
      const av = a[key];
      const bv = b[key];
      const cmp = av < bv ? -1 : av > bv ? 1 : a.id - b.id;
      return sortDir === "asc" ? cmp : -cmp;
    });

    const counts: Record<string, number> = {};
    for (const e of state.audit) {
      counts[e.event_type] = (counts[e.event_type] ?? 0) + 1;
    }

    return HttpResponse.json({
      events: events.slice(offset, offset + limit),
      total: events.length,
      counts,
    });
  }),

  // --- member self-service --------------------------------
  http.get("/api/me", () => {
    const member = currentMemberOr403();
    return member instanceof Response ? member : HttpResponse.json(member);
  }),

  http.get("/api/me/balance", () => {
    const member = currentMemberOr403();
    if (member instanceof Response) return member;
    const ore = ledgerBalanceOre(member.id);
    return HttpResponse.json({
      member_id: member.id,
      balance_nok: oreToNok(ore),
      balance_ore: ore,
    });
  }),

  http.get("/api/me/ledger", ({ request }) => {
    const member = currentMemberOr403();
    if (member instanceof Response) return member;
    return ledgerPage(member.id, request.url);
  }),

  http.get("/api/me/status", () => {
    const member = currentMemberOr403();
    if (member instanceof Response) return member;
    return HttpResponse.json({
      status: member.status,
      participates: member.participates,
      history: [...(state.statusHistory.get(member.id) ?? [])].sort(
        (a, b) => a.effective_from.localeCompare(b.effective_from) || a.id - b.id,
      ),
    });
  }),

  http.get("/api/me/settlements", () => {
    const member = currentMemberOr403();
    if (member instanceof Response) return member;
    return HttpResponse.json({ settlements: mock1b.mySettlements });
  }),

  // --- Release 1B: chargers, zaptec, settlements, system -------------

  http.get("/api/chargers", () =>
    HttpResponse.json({ chargers: mock1b.chargers }),
  ),
  http.post("/api/chargers", async ({ request }) => {
    const body = (await request.json()) as { name: string; serial_no?: string };
    const charger = {
      id: nextId(),
      zaptec_id: null,
      name: body.name,
      serial_no: body.serial_no ?? null,
      device_type: null,
      is_active: true,
      last_synced_at: null,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: "2026-08-01T00:00:00+00:00",
      assigned_member_id: null,
    };
    mock1b.chargers.push(charger);
    return HttpResponse.json(charger, { status: 201 });
  }),
  http.post("/api/chargers/:id/assignments", async ({ params, request }) => {
    const body = (await request.json()) as { member_id: number };
    const c = mock1b.chargers.find((x) => x.id === Number(params.id));
    if (c) c.assigned_member_id = body.member_id;
    return HttpResponse.json({ assignment: { id: nextId(), charger_id: Number(params.id) } });
  }),
  http.post("/api/chargers/:id/unassign", ({ params }) => {
    const c = mock1b.chargers.find((x) => x.id === Number(params.id));
    if (c) c.assigned_member_id = null;
    return HttpResponse.json({ assignment: { id: nextId(), charger_id: Number(params.id) } });
  }),

  http.get("/api/zaptec/status", () =>
    HttpResponse.json({
      enabled: false,
      installation_id: null,
      last: { chargers: null, sessions: null, intervals: null },
      recent: [],
      failures: 0,
    }),
  ),
  http.post("/api/zaptec/sync/chargers", () =>
    HttpResponse.json({ chargers_created: 0, chargers_updated: 0, installations: 0, chargers_seen: 0 }),
  ),
  http.post("/api/zaptec/sync/sessions", () =>
    HttpResponse.json({ rows_inserted: 0, rows_updated: 0, sessions_in: 0 }),
  ),

  http.get("/api/settlement", () =>
    HttpResponse.json({ settlements: mock1b.settlements }),
  ),
  http.post("/api/settlement/drafts", async ({ request }) => {
    const body = (await request.json()) as { period_month: string };
    const settlement = {
      id: nextId(),
      period_month: body.period_month,
      status: "draft" as const,
      invoice_kwh: null,
      invoice_total_nok: null,
      grid_kwh: null,
      attachment_filename: null,
      attachment_path: null,
      note: null,
      usage_frozen_at: null,
      created_at: "2026-08-01T00:00:00+00:00",
      posted_at: null,
    };
    mock1b.settlements.push(settlement);
    mock1b.details.set(settlement.id, { settlement, lines: [], snapshot: [] });
    return HttpResponse.json({ settlement });
  }),
  http.get("/api/settlement/:id", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    return d
      ? HttpResponse.json(d)
      : HttpResponse.json(errorBody("not_found", "not found"), { status: 404 });
  }),
  http.put("/api/settlement/:id/invoice", async ({ params, request }) => {
    const body = (await request.json()) as { invoice_kwh?: string };
    const d = mock1b.details.get(Number(params.id));
    if (d && body.invoice_kwh) d.settlement.invoice_kwh = body.invoice_kwh;
    return HttpResponse.json(d);
  }),
  http.post("/api/settlement/:id/lines", async ({ params, request }) => {
    const body = (await request.json()) as {
      description: string;
      allocation_method: "equal" | "consumption";
      amount: string;
    };
    const d = mock1b.details.get(Number(params.id));
    const line = {
      id: nextId(),
      settlement_id: Number(params.id),
      description: body.description,
      category: null,
      allocation_method: body.allocation_method,
      amount_ore: Math.round(Number(body.amount) * 100),
      amount_nok: Number(body.amount).toFixed(2),
      sort_order: (d?.lines.length ?? 0) + 1,
    };
    d?.lines.push(line);
    return HttpResponse.json({ line }, { status: 201 });
  }),
  http.delete("/api/settlement/:id/lines/:lineId", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) d.lines = d.lines.filter((l) => l.id !== Number(params.lineId));
    return HttpResponse.json(d);
  }),
  http.post("/api/settlement/:id/attachment", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) d.settlement.attachment_filename = "faktura.pdf";
    return HttpResponse.json({ settlement: d?.settlement });
  }),
  http.post("/api/settlement/:id/freeze", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) {
      d.settlement.usage_frozen_at = "2026-08-01T00:00:00+00:00";
      d.settlement.grid_kwh = "10";
    }
    return HttpResponse.json(d);
  }),
  http.get("/api/settlement/:id/preview", ({ params }) =>
    HttpResponse.json(previewFor(Number(params.id))),
  ),
  http.post("/api/settlement/:id/post", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) d.settlement.status = "posted";
    return HttpResponse.json({
      ...previewFor(Number(params.id)),
      status: "posted",
      members_charged: 1,
      emails_queued: 1,
    });
  }),
  http.get("/api/settlement/:id/reports", ({ params }) =>
    HttpResponse.json({
      settlement_id: Number(params.id),
      period_month: "2026-07",
      summary_url: `/api/settlement/${params.id}/reports/summary`,
      members: [
        {
          member_id: 7,
          full_name: "Member Seven",
          charge_nok: "100.00",
          url: `/api/settlement/${params.id}/reports/7`,
        },
      ],
    }),
  ),

  http.get("/api/system/health", () =>
    HttpResponse.json({
      version: "0.2.0",
      schema_version: 6,
      zaptec: { enabled: false, installation_id: null, last: {}, failed_runs: 0 },
      email: { queued: 0, sent: 2, failed: 0, next_attempt_at: null },
      failed_jobs: 0,
      ok: true,
    }),
  ),
  http.get("/api/notifications", () =>
    HttpResponse.json({
      stats: { queued: 0, sent: 2, failed: 0, next_attempt_at: null },
      messages: [],
    }),
  ),
  http.post("/api/notifications/process", () =>
    HttpResponse.json({ due: 0, sent: 0, failed: 0, retried: 0 }),
  ),

  http.post("/api/auth/magic-link", () => HttpResponse.json({ ok: true })),
  http.post("/api/auth/magic-link/consume", () =>
    HttpResponse.json({ user: MEMBER_USER }),
  ),
  http.post("/api/auth/password-reset/request", () =>
    HttpResponse.json({ ok: true }),
  ),
  http.post("/api/auth/password-reset/consume", () =>
    HttpResponse.json({ ok: true }),
  ),
];

interface Mock1bState {
  chargers: {
    id: number;
    zaptec_id: string | null;
    name: string;
    serial_no: string | null;
    device_type: string | null;
    is_active: boolean;
    last_synced_at: string | null;
    created_at: string;
    updated_at: string;
    assigned_member_id: number | null;
  }[];
  settlements: {
    id: number;
    period_month: string;
    status: "draft" | "posted";
    invoice_kwh: string | null;
    invoice_total_nok: string | null;
    grid_kwh: string | null;
    attachment_filename: string | null;
    attachment_path: string | null;
    note: string | null;
    usage_frozen_at: string | null;
    created_at: string;
    posted_at: string | null;
  }[];
  details: Map<
    number,
    {
      settlement: Mock1bState["settlements"][number];
      lines: {
        id: number;
        settlement_id: number;
        description: string;
        category: string | null;
        allocation_method: "equal" | "consumption";
        amount_ore: number;
        amount_nok: string;
        sort_order: number;
      }[];
      snapshot: unknown[];
    }
  >;
  mySettlements: {
    settlement_id: number;
    period_month: string;
    posted_at: string | null;
    consumption_kwh: string;
    charge_nok: string;
    balance_after_nok: string;
    report_url: string;
  }[];
}

let mock1b: Mock1bState = freshMock1b();

function freshMock1b(): Mock1bState {
  return { chargers: [], settlements: [], details: new Map(), mySettlements: [] };
}

function previewFor(id: number) {
  const d = mock1b.details.get(id);
  const total = (d?.lines ?? []).reduce((s, l) => s + l.amount_ore, 0);
  return {
    settlement_id: id,
    period_month: d?.settlement.period_month ?? "2026-07",
    status: d?.settlement.status ?? "draft",
    invoice_kwh: d?.settlement.invoice_kwh ?? null,
    grid_kwh: d?.settlement.grid_kwh ?? null,
    invoice_lines_total_nok: (total / 100).toFixed(2),
    total_charged_nok: (total / 100).toFixed(2),
    total_charged_ore: total,
    members: [
      {
        member_id: 7,
        member_reference: "M-7",
        full_name: "Member Seven",
        consumption_kwh: "10",
        session_count: 2,
        balance_before_nok: "1000.00",
        charge_nok: (total / 100).toFixed(2),
        charge_ore: total,
        balance_after_nok: ((100000 - total) / 100).toFixed(2),
        balance_after_ore: 100000 - total,
        lines: [],
      },
    ],
    lines: [],
    warnings: [] as { code: string }[],
  };
}

function ledgerPage(memberId: number, rawUrl: string): Response {
  const url = new URL(rawUrl);
  const limit = Number(url.searchParams.get("limit") ?? "50");
  const offset = Number(url.searchParams.get("offset") ?? "0");
  const all = [...(state.ledger.get(memberId) ?? [])].sort((a, b) => b.id - a.id);
  const ore = ledgerBalanceOre(memberId);
  return HttpResponse.json({
    transactions: all.slice(offset, offset + limit),
    total: all.length,
    balance_nok: oreToNok(ore),
    balance_ore: ore,
  });
}

function currentMemberOr403(): Member | Response {
  if (!state.session) {
    return HttpResponse.json(errorBody("not_authenticated", "Not authenticated"), {
      status: 401,
    });
  }
  const memberId = state.session.member_id;
  if (memberId == null) {
    return HttpResponse.json(
      errorBody("forbidden", "no linked member"),
      { status: 403 },
    );
  }
  const member = state.members.get(memberId);
  if (!member) {
    return HttpResponse.json(errorBody("not_found", "member not found"), {
      status: 404,
    });
  }
  return member;
}

export const server = setupServer(...handlers);
