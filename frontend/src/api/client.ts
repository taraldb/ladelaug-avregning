// Thin, typed fetch wrappers around the FastAPI backend's JSON API.
//
// - Every call sends `credentials: "include"` so the HttpOnly `ladelaug_session`
//   cookie rides along. The frontend never reads that cookie.
// - Every mutating call (POST/PATCH/DELETE) sends `X-Requested-With: fetch`;
//   without it the backend answers 403 `{code: "csrf"}`.
// - Every error response has the shape `{"detail": {"code", "message"}}`. We
//   surface that as an `ApiError` exposing `status`, `code`, `message`.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const WRITE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

function fallbackCode(status: number): string {
  switch (status) {
    case 401:
      return "not_authenticated";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 422:
      return "validation_error";
    case 429:
      return "rate_limited";
    default:
      return "error";
  }
}

function fallbackMessage(status: number): string {
  return `Request failed with status ${status}`;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function errorFromResponse(status: number, data: unknown): ApiError {
  const detail = (data as { detail?: unknown } | undefined)?.detail;
  if (detail && typeof detail === "object") {
    const d = detail as { code?: unknown; message?: unknown };
    const code = typeof d.code === "string" ? d.code : fallbackCode(status);
    const message =
      typeof d.message === "string" ? d.message : fallbackMessage(status);
    return new ApiError(status, code, message);
  }
  if (typeof detail === "string") {
    return new ApiError(status, fallbackCode(status), detail);
  }
  return new ApiError(status, fallbackCode(status), fallbackMessage(status));
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, credentials: "include", headers };
  if (WRITE_METHODS.has(method)) {
    headers["X-Requested-With"] = "fetch";
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network request failed";
    throw new ApiError(0, "network_error", message);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  const data = text ? safeParse(text) : undefined;

  if (!res.ok) {
    throw errorFromResponse(res.status, data);
  }
  return data as T;
}

export function get<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>("POST", path, body ?? {});
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PATCH", path, body);
}

export function del<T>(path: string): Promise<T> {
  return request<T>("DELETE", path);
}

// SWR fetcher: `useSWR<T>(key, fetcher)`.
export function fetcher<T>(path: string): Promise<T> {
  return get<T>(path);
}

// --- domain types --------------------------------------------------------

export type Role = "admin" | "member";

export interface AuthUser {
  id: number;
  email: string;
  role: Role;
  member_id: number | null;
  disabled: boolean;
}

export interface CurrentUser extends AuthUser {
  version: string;
}

export interface LoginResponse {
  user: AuthUser;
}

export type MemberStatus = "active" | "inactive";

export interface Member {
  id: number;
  member_reference: string;
  full_name: string;
  email: string | null;
  join_date: string;
  created_at: string;
  updated_at: string;
  status: MemberStatus | null;
  participates: boolean | null;
}

export interface MemberCreate {
  member_reference: string;
  full_name: string;
  email?: string;
  join_date: string;
}

export type MemberPatch = Partial<{
  member_reference: string;
  full_name: string;
  email: string;
  join_date: string;
}>;

export interface StatusPeriod {
  id: number;
  status: MemberStatus;
  effective_from: string;
  effective_to: string | null;
  note: string | null;
  created_at: string;
}

export interface ParticipationPeriod {
  id: number;
  participates: boolean;
  effective_from: string;
  effective_to: string | null;
  reason: string | null;
  created_at: string;
}

export type TxnType =
  | "payment"
  | "payment_reversal"
  | "adjustment_credit"
  | "adjustment_debit";

export interface LedgerTxn {
  id: number;
  member_id: number;
  txn_type: TxnType;
  amount_ore: number;
  amount_nok: string;
  currency: string;
  value_date: string;
  reason: string | null;
  reference: string | null;
  reverses_transaction_id: number | null;
  created_by_user_id: number | null;
  recorded_at: string;
}

export interface Balance {
  member_id: number;
  balance_nok: string;
  balance_ore: number;
}

export interface LedgerPage {
  transactions: LedgerTxn[];
  total: number;
  balance_nok: string;
  balance_ore: number;
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor_user_id: number | null;
  actor_label: string;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  detail: Record<string, unknown> | null;
  ip: string | null;
}

export type AuditSortColumn = "occurred_at" | "id" | "event_type";
export type SortDir = "asc" | "desc";

export interface AuditEventsResponse {
  events: AuditEvent[];
  total: number;
  counts: Record<string, number>;
}

export interface MyStatus {
  status: MemberStatus | null;
  participates: boolean | null;
  history: StatusPeriod[];
}

// --- auth --------------------------------------------------------------

export function login(email: string, password: string): Promise<LoginResponse> {
  return post<LoginResponse>("/api/auth/login", { email, password });
}

export function logout(): Promise<{ ok: boolean }> {
  return post<{ ok: boolean }>("/api/auth/logout");
}

export function getMe(): Promise<CurrentUser> {
  return get<CurrentUser>("/api/auth/me");
}

// --- members (admin) -------------------------------------------------

export function listMembers(): Promise<{ members: Member[] }> {
  return get<{ members: Member[] }>("/api/members");
}

export function getMember(id: number): Promise<Member> {
  return get<Member>(`/api/members/${id}`);
}

export function createMember(body: MemberCreate): Promise<Member> {
  return post<Member>("/api/members", body);
}

export function updateMember(id: number, body: MemberPatch): Promise<Member> {
  return patch<Member>(`/api/members/${id}`, body);
}

export function changeStatus(
  id: number,
  body: { status: MemberStatus; effective_from?: string; note?: string },
): Promise<{ period: StatusPeriod }> {
  return post<{ period: StatusPeriod }>(`/api/members/${id}/status`, body);
}

export function statusHistory(id: number): Promise<{ periods: StatusPeriod[] }> {
  return get<{ periods: StatusPeriod[] }>(`/api/members/${id}/status-history`);
}

export function changeParticipation(
  id: number,
  body: { participates: boolean; effective_from?: string; reason?: string },
): Promise<{ period: ParticipationPeriod }> {
  return post<{ period: ParticipationPeriod }>(
    `/api/members/${id}/participation`,
    body,
  );
}

export function participationHistory(
  id: number,
): Promise<{ periods: ParticipationPeriod[] }> {
  return get<{ periods: ParticipationPeriod[] }>(
    `/api/members/${id}/participation-history`,
  );
}

// --- ledger (admin) ------------------------------------------------

export function getBalance(memberId: number): Promise<Balance> {
  return get<Balance>(`/api/members/${memberId}/balance`);
}

export function getLedger(
  memberId: number,
  params: { limit?: number; offset?: number } = {},
): Promise<LedgerPage> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return get<LedgerPage>(`/api/members/${memberId}/ledger?${qs.toString()}`);
}

export function recordPayment(
  memberId: number,
  body: { amount: string; value_date?: string; reference?: string },
): Promise<LedgerTxn> {
  return post<LedgerTxn>(`/api/members/${memberId}/payments`, body);
}

export function recordAdjustment(
  memberId: number,
  body: {
    direction: "credit" | "debit";
    amount: string;
    reason: string;
    reference?: string;
  },
): Promise<LedgerTxn> {
  return post<LedgerTxn>(`/api/members/${memberId}/adjustments`, body);
}

export function reversePayment(txnId: number): Promise<LedgerTxn> {
  return post<LedgerTxn>(`/api/ledger-transactions/${txnId}/reverse`);
}

// --- audit log (admin) -------------------------------------------

export function listAuditEvents(params: {
  eventType?: string | null;
  entityType?: string | null;
  entityId?: string | null;
  sortBy?: AuditSortColumn;
  sortDir?: SortDir;
  limit?: number;
  offset?: number;
}): Promise<AuditEventsResponse> {
  const qs = new URLSearchParams();
  if (params.eventType) qs.set("event_type", params.eventType);
  if (params.entityType) qs.set("entity_type", params.entityType);
  if (params.entityId) qs.set("entity_id", params.entityId);
  if (params.sortBy) qs.set("sort_by", params.sortBy);
  if (params.sortDir) qs.set("sort_dir", params.sortDir);
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return get<AuditEventsResponse>(`/api/audit-events?${qs.toString()}`);
}

// --- member self-service -----------------------------------------

export function getMyMember(): Promise<Member> {
  return get<Member>("/api/me");
}

export function getMyBalance(): Promise<Balance> {
  return get<Balance>("/api/me/balance");
}

export function getMyLedger(
  params: { limit?: number; offset?: number } = {},
): Promise<LedgerPage> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return get<LedgerPage>(`/api/me/ledger?${qs.toString()}`);
}

export function getMyStatus(): Promise<MyStatus> {
  return get<MyStatus>("/api/me/status");
}
