import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type {
  AuditEvent,
  AuthUser,
  ForecastSettings,
  LedgerTxn,
  Member,
  MemberConsumption,
  MemberForecast,
  ParticipationPeriod,
  StatusPeriod,
  User,
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
  users: User[];
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
    users: [
      { id: 1, email: "admin@example.com", role: "admin", member_id: null, disabled: false },
      { id: 2, email: "member@example.com", role: "member", member_id: 7, disabled: false },
    ],
    statusHistory: new Map(),
    participationHistory: new Map(),
    ledger: new Map(),
    audit: [],
    seq: 100,
  };
}

let state: MockState = freshState();

let accessStatus: "warned" | "disabled" | "restored" | null = null;

interface JobScheduleRow {
  name: string;
  enabled: boolean;
  cron: string;
  last_run_at: string | null;
  last_status: "ok" | "error" | "running" | null;
  last_error: string | null;
  last_duration_ms: number | null;
  next_run_at: string | null;
  updated_at: string | null;
  updated_by_user_id: number | null;
}

const freshJobs = (): JobScheduleRow[] =>
  [
    ["drain_mail", "*/10 * * * *"],
    ["low_balance_scan", "0 * * * *"],
    ["zaptec_sync_sessions", "30 3 * * *"],
  ].map(([name, cron]) => ({
    name,
    enabled: false,
    cron,
    last_run_at: null,
    last_status: null,
    last_error: null,
    last_duration_ms: null,
    next_run_at: null,
    updated_at: null,
    updated_by_user_id: null,
  }));

let jobSchedules: JobScheduleRow[] = freshJobs();

/** Seed the charging-access status returned by GET /api/me/access and
 *  GET /api/members/:id/access. */
export function seedAccessStatus(
  status: "warned" | "disabled" | "restored" | null,
): void {
  accessStatus = status;
}

export function resetMockState(): void {
  state = freshState();
  mock1b = freshMock1b();
  forecast = freshForecast();
  accessStatus = null;
  jobSchedules = freshJobs();
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

export function seedUser(overrides: Partial<User> = {}): User {
  const user: User = {
    id: overrides.id ?? nextId(),
    email: overrides.email ?? `user${overrides.id ?? state.seq}@example.com`,
    role: overrides.role ?? "member",
    member_id: overrides.member_id ?? null,
    disabled: overrides.disabled ?? false,
  };
  state.users.push(user);
  return user;
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

export function seedCharger(
  overrides: Partial<Mock1bState["chargers"][number]> = {},
): Mock1bState["chargers"][number] {
  const id = overrides.id ?? nextId();
  const charger = {
    id,
    zaptec_id: overrides.zaptec_id ?? null,
    name: overrides.name ?? `Charger ${id}`,
    serial_no: overrides.serial_no ?? null,
    device_type: overrides.device_type ?? null,
    is_active: overrides.is_active ?? true,
    last_synced_at: overrides.last_synced_at ?? null,
    created_at: overrides.created_at ?? "2026-08-01T00:00:00+00:00",
    updated_at: overrides.updated_at ?? "2026-08-01T00:00:00+00:00",
    assigned_member_id: overrides.assigned_member_id ?? null,
    deletable: false,
    has_usage: overrides.has_usage ?? false,
  };
  mock1b.chargers.push(charger);
  return charger;
}

export function seedAuditEvent(overrides: Partial<AuditEvent> = {}): AuditEvent {
  const id = overrides.id ?? nextId();
  const event: AuditEvent = {
    id,
    occurred_at: overrides.occurred_at ?? `2024-03-01T10:00:${String(id % 60).padStart(2, "0")}Z`,
    actor_user_id: overrides.actor_user_id ?? 1,
    actor_label: overrides.actor_label ?? "admin@example.com",
    actor_role: overrides.actor_role ?? "admin",
    event_type: overrides.event_type ?? "member.created",
    entity_type: overrides.entity_type ?? "member",
    entity_id: overrides.entity_id ?? "1",
    summary: overrides.summary ?? "Something happened",
    detail: overrides.detail ?? null,
    ip: overrides.ip ?? null,
    user_agent: overrides.user_agent ?? null,
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

// --- forecasting fixtures (Epic 8) --------------------------------

interface ForecastMockState {
  settings: ForecastSettings;
  byMember: Map<number, MemberForecast>;
  consumption: Map<number, MemberConsumption>;
}

function freshForecast(): ForecastMockState {
  return {
    settings: {
      rate_override_ore_per_kwh: null,
      buffer_months: 2,
      notify_cooldown_days: 14,
      lookback_settlements: 3,
      updated_at: null,
      updated_by_user_id: null,
    },
    byMember: new Map(),
    consumption: new Map(),
  };
}

let forecast: ForecastMockState = freshForecast();

/** An "available" forecast that is comfortably above its recommended minimum. */
export function seedForecast(
  memberId: number,
  overrides: Partial<MemberForecast> = {},
): MemberForecast {
  const base: MemberForecast = {
    member_id: memberId,
    available: true,
    forecast_kwh: "120.5",
    rate_ore_per_kwh: "185",
    rate_source: "derived",
    equal_share_ore: 25000,
    forecast_monthly_cost_ore: 47293,
    recommended_minimum_ore: 94586,
    balance_ore: 150000,
    recommended_topup_ore: 0,
    low_balance: false,
    severity: null,
    reason: null,
  };
  const merged: MemberForecast = { ...base, ...overrides };
  forecast.byMember.set(memberId, merged);
  return merged;
}

/** A forecast that trips the low-balance rule (`severity` "low" or "critical"). */
export function seedLowBalanceForecast(
  memberId: number,
  severity: "low" | "critical" = "low",
): MemberForecast {
  const balance_ore = severity === "critical" ? 12000 : 60000;
  return seedForecast(memberId, {
    balance_ore,
    recommended_topup_ore: 94586 - balance_ore,
    low_balance: true,
    severity,
  });
}

export function seedUnavailableForecast(
  memberId: number,
  balanceOre = 0,
): MemberForecast {
  return seedForecast(memberId, {
    available: false,
    forecast_kwh: "0",
    rate_ore_per_kwh: "0",
    rate_source: null,
    equal_share_ore: 0,
    forecast_monthly_cost_ore: 0,
    recommended_minimum_ore: 0,
    balance_ore: balanceOre,
    recommended_topup_ore: 0,
    low_balance: false,
    severity: null,
    reason: "insufficient_history",
  });
}

export function seedConsumption(
  memberId: number,
  overrides: Partial<MemberConsumption> = {},
): MemberConsumption {
  const merged: MemberConsumption = {
    member_id: memberId,
    month: "2026-08",
    consumption_kwh: "42.75",
    session_count: 6,
    ...overrides,
  };
  forecast.consumption.set(memberId, merged);
  return merged;
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

function withBalance(member: Member): Member {
  const ore = ledgerBalanceOre(member.id);
  return { ...member, balance_ore: ore, balance_nok: oreToNok(ore) };
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
      members: [...state.members.values()]
        .sort((a, b) => a.id - b.id)
        .map(withBalance),
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
    return HttpResponse.json(withBalance(member));
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

  // --- users (admin) ---------------------------------------
  http.get("/api/users", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    return HttpResponse.json({ users: [...state.users].sort((a, b) => b.id - a.id) });
  }),

  http.post("/api/users", async ({ request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const body = (await request.json()) as {
      email: string;
      password?: string | null;
      role: "admin" | "member";
      member_id?: number | null;
    };
    if (!body.email?.trim() || !EMAIL_RE.test(body.email.trim())) {
      return HttpResponse.json(
        errorBody("validation_error", "email: not a valid email address"),
        { status: 422 },
      );
    }
    if (body.password != null && body.password !== "" && body.password.length < 10) {
      return HttpResponse.json(
        errorBody("validation_error", "password must be at least 10 characters"),
        { status: 422 },
      );
    }
    if (body.role === "member" && body.member_id == null) {
      return HttpResponse.json(
        errorBody("validation_error", "a member login requires member_id"),
        { status: 422 },
      );
    }
    if (body.role === "admin" && body.member_id != null) {
      return HttpResponse.json(
        errorBody("validation_error", "an admin login must not set member_id"),
        { status: 422 },
      );
    }
    if (
      state.users.some(
        (u) => u.email.toLowerCase() === body.email.trim().toLowerCase(),
      )
    ) {
      return HttpResponse.json(
        errorBody("email_taken", "An account with that email already exists."),
        { status: 422 },
      );
    }
    if (
      body.member_id != null &&
      state.users.some((u) => u.member_id === body.member_id)
    ) {
      return HttpResponse.json(
        errorBody("member_linked", "That member already has a login."),
        { status: 422 },
      );
    }
    const user: User = {
      id: nextId(),
      email: body.email.trim(),
      role: body.role,
      member_id: body.role === "member" ? (body.member_id ?? null) : null,
      disabled: false,
    };
    state.users.push(user);
    recordAudit("user.created", "user", String(user.id), `User ${user.email} created`);
    return HttpResponse.json(user, { status: 201 });
  }),

  http.post("/api/users/:id/disable", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const user = state.users.find((u) => u.id === Number(params.id));
    if (!user) {
      return HttpResponse.json(errorBody("not_found", "user not found"), { status: 404 });
    }
    if (user.id === state.session?.id) {
      return HttpResponse.json(
        errorBody("cannot_disable_self", "You cannot disable your own account."),
        { status: 422 },
      );
    }
    if (
      user.role === "admin" &&
      !user.disabled &&
      !state.users.some((u) => u.role === "admin" && !u.disabled && u.id !== user.id)
    ) {
      return HttpResponse.json(
        errorBody("last_admin", "Cannot disable the last active administrator."),
        { status: 422 },
      );
    }
    user.disabled = true;
    recordAudit("user.disabled", "user", String(user.id), `User ${user.id} disabled`);
    return HttpResponse.json(user);
  }),

  http.post("/api/users/:id/enable", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const user = state.users.find((u) => u.id === Number(params.id));
    if (!user) {
      return HttpResponse.json(errorBody("not_found", "user not found"), { status: 404 });
    }
    user.disabled = false;
    recordAudit("user.enabled", "user", String(user.id), `User ${user.id} re-enabled`);
    return HttpResponse.json(user);
  }),

  http.post("/api/users/:id/password", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const user = state.users.find((u) => u.id === Number(params.id));
    if (!user) {
      return HttpResponse.json(errorBody("not_found", "user not found"), { status: 404 });
    }
    const body = (await request.json()) as { password: string };
    if (!body.password || body.password.length < 10) {
      return HttpResponse.json(
        errorBody("validation_error", "password must be at least 10 characters"),
        { status: 422 },
      );
    }
    recordAudit(
      "user.password_changed",
      "user",
      String(user.id),
      `Password changed for user ${user.id}`,
    );
    return HttpResponse.json({ ok: true });
  }),

  http.patch("/api/users/:id", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const user = state.users.find((u) => u.id === Number(params.id));
    if (!user) {
      return HttpResponse.json(errorBody("not_found", "user not found"), { status: 404 });
    }
    const body = (await request.json()) as {
      email?: string;
      role?: "admin" | "member";
      member_id?: number | null;
    };
    if (Object.keys(body).length === 0) {
      return HttpResponse.json(
        errorBody("validation_error", "provide at least one field to update"),
        { status: 422 },
      );
    }
    if (body.email != null && (!body.email.trim() || !EMAIL_RE.test(body.email.trim()))) {
      return HttpResponse.json(
        errorBody("validation_error", "email: not a valid email address"),
        { status: 422 },
      );
    }

    const newRole = body.role ?? user.role;
    let newMemberId: number | null;
    if ("member_id" in body) {
      newMemberId = body.member_id ?? null;
    } else if (body.role === "admin") {
      newMemberId = null;
    } else {
      newMemberId = user.member_id;
    }

    if (user.role === "admin" && newRole !== "admin") {
      if (user.id === state.session?.id) {
        return HttpResponse.json(
          errorBody("cannot_demote_self", "You cannot remove your own administrator role."),
          { status: 422 },
        );
      }
      if (
        !user.disabled &&
        !state.users.some((u) => u.role === "admin" && !u.disabled && u.id !== user.id)
      ) {
        return HttpResponse.json(
          errorBody("last_admin", "Cannot demote the last active administrator."),
          { status: 422 },
        );
      }
    }

    if (newRole === "member" && newMemberId == null) {
      return HttpResponse.json(
        errorBody("validation_error", "a member login requires member_id"),
        { status: 422 },
      );
    }
    if (newRole === "admin" && newMemberId != null) {
      return HttpResponse.json(
        errorBody("validation_error", "an admin login must not set member_id"),
        { status: 422 },
      );
    }

    if (
      body.email != null &&
      state.users.some(
        (u) =>
          u.id !== user.id &&
          u.email.toLowerCase() === body.email!.trim().toLowerCase(),
      )
    ) {
      return HttpResponse.json(
        errorBody("email_taken", "An account with that email already exists."),
        { status: 422 },
      );
    }
    if (
      newMemberId != null &&
      state.users.some((u) => u.id !== user.id && u.member_id === newMemberId)
    ) {
      return HttpResponse.json(
        errorBody("member_linked", "That member already has a login."),
        { status: 422 },
      );
    }

    if (body.email != null) user.email = body.email.trim();
    user.role = newRole;
    user.member_id = newMemberId;
    recordAudit("user.updated", "user", String(user.id), `User ${user.id} updated`);
    return HttpResponse.json(user);
  }),

  // --- ledger (admin) ---------------------------------------
  http.get("/api/ledger-transactions", ({ request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const memberIdParam = url.searchParams.get("member_id");
    const txnType = url.searchParams.get("txn_type");

    let rows = [...state.ledger.entries()].flatMap(([mid, list]) => {
      const m = state.members.get(mid);
      return list.map((t) => ({
        ...t,
        member_name: m?.full_name ?? `Member ${mid}`,
        member_reference: m?.member_reference ?? `M-${mid}`,
      }));
    });
    if (memberIdParam) rows = rows.filter((t) => t.member_id === Number(memberIdParam));
    if (txnType) rows = rows.filter((t) => t.txn_type === txnType);
    rows.sort((a, b) => b.id - a.id);
    return HttpResponse.json({
      transactions: rows.slice(offset, offset + limit),
      total: rows.length,
    });
  }),

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

  http.get("/api/audit-events/export.csv", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    const header = "id,occurred_at,actor_label,event_type,summary";
    const body = state.audit
      .map((e) => `${e.id},${e.occurred_at},${e.actor_label},${e.event_type},${e.summary}`)
      .join("\n");
    return new HttpResponse(`${header}\n${body}\n`, {
      headers: { "content-type": "text/csv" },
    });
  }),

  http.get("/api/audit-events/:id", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const event = state.audit.find((e) => e.id === Number(params.id));
    return event
      ? HttpResponse.json({ event })
      : HttpResponse.json(errorBody("not_found", "audit event not found"), { status: 404 });
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
    HttpResponse.json({
      chargers: mock1b.chargers.map((c) => ({
        ...c,
        deletable: c.zaptec_id === null && !c.has_usage,
      })),
    }),
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
      deletable: true,
      has_usage: false,
    };
    mock1b.chargers.push(charger);
    return HttpResponse.json(charger, { status: 201 });
  }),
  http.patch("/api/chargers/:id", async ({ params, request }) => {
    const c = mock1b.chargers.find((x) => x.id === Number(params.id));
    if (!c)
      return HttpResponse.json(
        { detail: { code: "not_found", message: "not found" } },
        { status: 404 },
      );
    const body = (await request.json()) as Partial<{
      name: string;
      serial_no: string | null;
      device_type: string | null;
      is_active: boolean;
    }>;
    Object.assign(c, body);
    return HttpResponse.json({
      ...c,
      deletable: c.zaptec_id === null && !c.has_usage,
    });
  }),
  http.delete("/api/chargers/:id", ({ params }) => {
    const c = mock1b.chargers.find((x) => x.id === Number(params.id));
    if (!c)
      return HttpResponse.json(
        { detail: { code: "not_found", message: "not found" } },
        { status: 404 },
      );
    if (c.zaptec_id !== null)
      return HttpResponse.json(
        { detail: { code: "zaptec_charger", message: "Deaktiver i stedet." } },
        { status: 422 },
      );
    if (c.has_usage)
      return HttpResponse.json(
        { detail: { code: "charger_has_usage", message: "Laderen har importert forbruk." } },
        { status: 422 },
      );
    mock1b.chargers = mock1b.chargers.filter((x) => x.id !== c.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/chargers/:id/assignments", async ({ params, request }) => {
    const body = (await request.json()) as {
      member_id: number;
      effective_from?: string;
    };
    const c = mock1b.chargers.find((x) => x.id === Number(params.id));
    if (c) c.assigned_member_id = body.member_id;
    return HttpResponse.json({
      assignment: {
        id: nextId(),
        charger_id: Number(params.id),
        member_id: body.member_id,
        effective_from: body.effective_from ?? "2026-01-01",
        effective_to: null,
      },
    });
  }),
  http.post("/api/chargers/:id/unassign", ({ params }) => {
    const c = mock1b.chargers.find((x) => x.id === Number(params.id));
    if (c) c.assigned_member_id = null;
    return HttpResponse.json({ assignment: { id: nextId(), charger_id: Number(params.id) } });
  }),

  http.get("/api/charging/consumption", ({ request }) => {
    const month = new URL(request.url).searchParams.get("month") ?? "";
    const c = mock1b.consumption.get(month) ?? {
      total_kwh: "0",
      unassigned_kwh: "0",
      by_member: [],
    };
    return HttpResponse.json({ month, ...c });
  }),
  http.get("/api/charging/unassigned", ({ request }) => {
    const month = new URL(request.url).searchParams.get("month") ?? "";
    const chargers = mock1b.unassigned.get(month) ?? [];
    const total = chargers.reduce((s, c) => s + Number(c.energy_kwh), 0);
    return HttpResponse.json({
      month,
      chargers,
      total_kwh: total.toFixed(3),
    });
  }),
  http.post("/api/charging/reresolve", ({ request }) => {
    const month = new URL(request.url).searchParams.get("month") ?? "";
    const had = mock1b.unassigned.get(month)?.length ?? 0;
    mock1b.unassigned.delete(month);
    return HttpResponse.json({ month, sessions_changed: had });
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
    mock1b.details.set(settlement.id, {
      settlement,
      lines: [],
      snapshot: [],
      attachments: [],
      corrections: [],
    });
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
  http.patch("/api/settlement/:id/lines/:lineId", async ({ params, request }) => {
    const body = (await request.json()) as Partial<{
      description: string;
      allocation_method: "equal" | "consumption";
      amount: string;
      category: string | null;
    }>;
    if (Object.keys(body).length === 0) {
      return HttpResponse.json(
        errorBody("validation_error", "provide at least one field to update"),
        { status: 422 },
      );
    }
    const d = mock1b.details.get(Number(params.id));
    const line = d?.lines.find((l) => l.id === Number(params.lineId));
    if (!d || !line) {
      return HttpResponse.json(errorBody("not_found", "not found"), { status: 404 });
    }
    if (body.description !== undefined) line.description = body.description;
    if (body.allocation_method !== undefined) {
      line.allocation_method = body.allocation_method;
    }
    if (body.category !== undefined) line.category = body.category;
    if (body.amount !== undefined) {
      line.amount_ore = Math.round(Number(body.amount) * 100);
      line.amount_nok = Number(body.amount).toFixed(2);
    }
    return HttpResponse.json(d);
  }),
  http.delete("/api/settlement/:id/lines/:lineId", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) d.lines = d.lines.filter((l) => l.id !== Number(params.lineId));
    return HttpResponse.json(d);
  }),
  // Note: the real endpoint parses a multipart body; parsing it here is
  // unreliable under jsdom+undici, so the mock fabricates a deterministic
  // filename per call (the client POSTs one file at a time).
  http.post("/api/settlement/:id/attachments", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) {
      d.attachments.push({
        id: nextId(),
        filename: `faktura-${d.attachments.length + 1}.pdf`,
        bytes: 3,
        uploaded_at: "2026-08-01T00:00:00+00:00",
      });
    }
    return HttpResponse.json(d, { status: 201 });
  }),
  http.get("/api/settlement/:id/attachments/:aid", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    const found = d?.attachments.find((a) => a.id === Number(params.aid));
    if (!found) {
      return HttpResponse.json(errorBody("not_found", "not found"), { status: 404 });
    }
    return new HttpResponse(new Blob([`%PDF ${found.filename}`]), {
      headers: { "content-type": "application/pdf" },
    });
  }),
  http.delete("/api/settlement/:id/attachments/:aid", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d) {
      d.attachments = d.attachments.filter((a) => a.id !== Number(params.aid));
    }
    return HttpResponse.json(d);
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
  http.post("/api/settlement/:id/resend-reports", ({ params }) => {
    const d = mock1b.details.get(Number(params.id));
    if (d && d.settlement.status !== "posted") {
      return HttpResponse.json(errorBody("not_posted", "not posted"), { status: 422 });
    }
    return HttpResponse.json({
      settlement_id: Number(params.id),
      period_month: "2026-07",
      emails_queued: 2,
    });
  }),

  http.get("/api/system/health", () =>
    HttpResponse.json({
      version: "0.2.0",
      schema_version: 6,
      scheduler: { enabled: false, jobs: jobSchedules },
      zaptec: { enabled: false, installation_id: null, last: {}, failed_runs: 0 },
      email: { queued: 0, sent: 2, failed: 0, next_attempt_at: null },
      corrections: { settlements_with_pending: 0 },
      access: { disabled: 0 },
      failed_jobs: 0,
      ok: true,
    }),
  ),

  http.get("/api/system/jobs", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    return HttpResponse.json({ jobs: jobSchedules });
  }),

  http.put("/api/system/jobs/:name", async ({ params, request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const row = jobSchedules.find((j) => j.name === params.name);
    if (!row) {
      return HttpResponse.json(errorBody("unknown_job", "unknown job"), {
        status: 422,
      });
    }
    const body = (await request.json()) as { enabled?: boolean; cron?: string };
    if (body.enabled === undefined && body.cron === undefined) {
      return HttpResponse.json(
        errorBody("validation_error", "provide 'enabled' and/or 'cron'"),
        { status: 422 },
      );
    }
    if (body.cron !== undefined && body.cron.trim().split(/\s+/).length !== 5) {
      return HttpResponse.json(errorBody("bad_cron", "invalid cron expression"), {
        status: 422,
      });
    }
    if (body.enabled !== undefined) row.enabled = body.enabled;
    if (body.cron !== undefined) row.cron = body.cron;
    row.next_run_at = row.enabled ? "2026-09-01T00:00:00+00:00" : null;
    row.updated_at = new Date().toISOString();
    row.updated_by_user_id = state.session?.id ?? null;
    recordAudit(
      "system.job_schedule_updated",
      "job_schedules",
      row.name,
      `Job schedule updated: ${row.name}`,
    );
    return HttpResponse.json(row);
  }),

  http.post("/api/system/jobs/:name/run", ({ params }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const row = jobSchedules.find((j) => j.name === params.name);
    if (!row) {
      return HttpResponse.json(errorBody("unknown_job", "unknown job"), {
        status: 422,
      });
    }
    row.last_run_at = new Date().toISOString();
    row.last_status = "ok";
    row.last_error = null;
    row.last_duration_ms = 5;
    return HttpResponse.json({
      name: row.name,
      status: "ok",
      error: null,
      duration_ms: 5,
      summary: {},
    });
  }),

  // --- Release 1D: refunds, corrections, departure, access --------

  http.post("/api/members/:id/refunds", async ({ params, request }) => {
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
      reference?: string;
      allow_negative?: boolean;
    };
    const magnitude = nokToOre(body.amount ?? "0");
    if (!Number.isFinite(magnitude) || magnitude <= 0) {
      return HttpResponse.json(
        errorBody("validation_error", "amount must be positive"),
        { status: 422 },
      );
    }
    if (!body.allow_negative && magnitude > ledgerBalanceOre(memberId)) {
      return HttpResponse.json(
        errorBody("refund_exceeds_balance", "refund exceeds the balance"),
        { status: 422 },
      );
    }
    const txn = seedLedgerTxn(memberId, {
      txn_type: "refund",
      amount_ore: -magnitude,
      amount_nok: oreToNok(-magnitude),
      value_date: today(),
      reference: body.reference?.trim() || null,
      recorded_at: new Date().toISOString(),
    });
    recordAudit(
      "ledger.refunded",
      "ledger_transaction",
      String(txn.id),
      `Refund ${txn.amount_nok} NOK for member ${memberId}`,
    );
    return HttpResponse.json(txn, { status: 201 });
  }),

  http.get("/api/members/:id/departure-check", ({ params, request }) => {
    const url = new URL(request.url);
    return HttpResponse.json({
      member_id: Number(params.id),
      effective_date: url.searchParams.get("effective_date") ?? "2026-09-01",
      current_status: "active",
      open_assignments: [],
      unsettled_months: [],
      balance_ore: 0,
      balance_nok: "0.00",
      would_refund_ore: 0,
    });
  }),

  http.post("/api/members/:id/departure", async ({ params, request }) => {
    const body = (await request.json()) as {
      effective_date: string;
      refund?: boolean;
    };
    return HttpResponse.json({
      member_id: Number(params.id),
      effective_date: body.effective_date,
      current_status: "active",
      open_assignments: [],
      unsettled_months: [],
      balance_ore: 0,
      balance_nok: "0.00",
      would_refund_ore: 0,
      status_changed: true,
      assignments_closed: [],
      refund_txn_id: null,
      refunded_ore: 0,
    });
  }),

  http.get("/api/members/:id/access", ({ params }) =>
    HttpResponse.json({
      member_id: Number(params.id),
      status: accessStatus,
      history: [],
    }),
  ),

  http.post("/api/members/:id/access", async ({ params, request }) => {
    const body = (await request.json()) as {
      action: "warned" | "disabled" | "restored";
      reason?: string;
    };
    const event = {
      id: nextId(),
      member_id: Number(params.id),
      action: body.action,
      reason: body.reason ?? null,
      note: null,
      created_at: "2026-08-20T00:00:00+00:00",
      created_by_user_id: 1,
      email_message_id: body.action === "disabled" ? null : nextId(),
    };
    return HttpResponse.json({
      member_id: Number(params.id),
      status: body.action,
      event,
      history: [event],
    });
  }),

  http.get("/api/me/access", () =>
    HttpResponse.json({
      status: accessStatus,
      portal_url: "https://portal.zaptec.com",
    }),
  ),

  http.get("/api/settlement/:id/correction", ({ params }) =>
    HttpResponse.json({
      settlement_id: Number(params.id),
      period_month: "2026-07",
      status: "posted",
      has_changes: true,
      sequence_next: 1,
      unresolved_late_flags: 1,
      original_total_charged_ore: 100000,
      corrected_total_charged_ore: 100000,
      members: [
        {
          member_id: 7,
          member_reference: "M-7",
          full_name: "Member Seven",
          in_snapshot: true,
          consumption_kwh_before: "10.000",
          consumption_kwh_after: "20.000",
          charged_ore: 50000,
          charged_nok: "500.00",
          corrected_charge_ore: 66667,
          corrected_charge_nok: "666.67",
          delta_ore: -16667,
          delta_nok: "-166.67",
        },
      ],
    }),
  ),

  http.post("/api/settlement/:id/correction", ({ params }) =>
    HttpResponse.json({
      settlement_id: Number(params.id),
      period_month: "2026-07",
      status: "posted",
      has_changes: true,
      sequence_next: 2,
      unresolved_late_flags: 0,
      original_total_charged_ore: 0,
      corrected_total_charged_ore: 0,
      members: [],
      correction_id: nextId(),
      sequence: 1,
      members_adjusted: 0,
      emails_queued: 0,
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
  http.post("/api/notifications/:id/requeue", ({ params }) =>
    HttpResponse.json({
      message: {
        id: Number(params.id),
        to_address: "member@example.test",
        subject: "Avregning 2026-07",
        template: "settlement_report",
        status: "queued",
        attempts: 0,
        max_attempts: 5,
        last_error: null,
        next_attempt_at: "2026-08-31T00:00:00+00:00",
        created_at: "2026-08-01T00:00:00+00:00",
        sent_at: null,
      },
    }),
  ),

  // --- Release 1C: forecast + low-balance --------------------------

  http.get("/api/me/forecast", () => {
    const member = currentMemberOr403();
    if (member instanceof Response) return member;
    const fc =
      forecast.byMember.get(member.id) ??
      seedUnavailableForecast(member.id, ledgerBalanceOre(member.id));
    return HttpResponse.json(fc);
  }),

  http.get("/api/me/consumption", ({ request }) => {
    const member = currentMemberOr403();
    if (member instanceof Response) return member;
    const month = new URL(request.url).searchParams.get("month") ?? "2026-08";
    const seeded = forecast.consumption.get(member.id);
    return HttpResponse.json(
      seeded ?? {
        member_id: member.id,
        month,
        consumption_kwh: "0",
        session_count: 0,
      },
    );
  }),

  http.get("/api/forecast/settings", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    return HttpResponse.json(forecast.settings);
  }),

  http.put("/api/forecast/settings", async ({ request }) => {
    const denied = requireAdmin();
    if (denied) return denied;
    const body = (await request.json()) as Partial<ForecastSettings>;
    const keys = [
      "rate_override_ore_per_kwh",
      "buffer_months",
      "notify_cooldown_days",
      "lookback_settlements",
    ] as const;
    let changed = false;
    for (const k of keys) {
      if (k in body && body[k] !== forecast.settings[k]) {
        forecast.settings[k] = body[k] as never;
        changed = true;
      }
    }
    if (changed) {
      forecast.settings.updated_at = new Date().toISOString();
      forecast.settings.updated_by_user_id = state.session?.id ?? null;
      recordAudit(
        "forecast.settings_updated",
        "forecast_settings",
        "1",
        "Forecast settings updated",
      );
    }
    return HttpResponse.json(forecast.settings);
  }),

  http.get("/api/forecast/members", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    return HttpResponse.json({ members: [...forecast.byMember.values()] });
  }),

  http.post("/api/notifications/low-balance-scan", () => {
    const denied = requireAdmin();
    if (denied) return denied;
    const available = [...forecast.byMember.values()].filter((f) => f.available);
    const below = available.filter((f) => f.low_balance);
    if (below.length > 0) {
      recordAudit(
        "notifications.low_balance_warned",
        "member",
        String(below[0].member_id),
        "Low-balance warning enqueued",
      );
    }
    return HttpResponse.json({
      scanned: available.length,
      below: below.length,
      queued: below.length,
      suppressed: 0,
    });
  }),

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
    deletable: boolean;
    has_usage?: boolean;
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
      attachments: {
        id: number;
        filename: string;
        bytes: number;
        uploaded_at: string;
      }[];
      corrections: unknown[];
      correction_pending?: boolean;
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
  unassigned: Map<string, UnassignedCharger[]>;
  consumption: Map<string, MonthConsumption>;
}

interface UnassignedCharger {
  charger_zaptec_id: string;
  charger_id: number | null;
  charger_name: string | null;
  sessions: number;
  energy_kwh: string;
}

interface MonthConsumption {
  total_kwh: string;
  unassigned_kwh: string;
  by_member: { member_id: number; energy_kwh: string }[];
}

let mock1b: Mock1bState = freshMock1b();

function freshMock1b(): Mock1bState {
  return {
    chargers: [],
    settlements: [],
    details: new Map(),
    mySettlements: [],
    unassigned: new Map(),
    consumption: new Map(),
  };
}

export function seedUnassigned(month: string, chargers: UnassignedCharger[]): void {
  mock1b.unassigned.set(month, chargers);
}

export function seedMySettlement(
  overrides: Partial<Mock1bState["mySettlements"][number]> = {},
): Mock1bState["mySettlements"][number] {
  const id = overrides.settlement_id ?? nextId();
  const entry = {
    settlement_id: id,
    period_month: overrides.period_month ?? "2026-07",
    posted_at: overrides.posted_at ?? "2026-08-01T00:00:00+00:00",
    consumption_kwh: overrides.consumption_kwh ?? "12.5",
    charge_nok: overrides.charge_nok ?? "450.00",
    balance_after_nok: overrides.balance_after_nok ?? "1050.00",
    report_url: overrides.report_url ?? `/api/me/settlements/${id}/report`,
  };
  mock1b.mySettlements.push(entry);
  return entry;
}

export function seedMonthConsumption(month: string, c: MonthConsumption): void {
  mock1b.consumption.set(month, c);
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
