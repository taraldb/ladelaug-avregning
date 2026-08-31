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

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PUT", path, body);
}

export function del<T>(path: string): Promise<T> {
  return request<T>("DELETE", path);
}

/** Multipart POST (file upload). Sends the CSRF header, no Content-Type (the
 * browser sets the multipart boundary). */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "X-Requested-With": "fetch", Accept: "application/json" },
      body: form,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network request failed";
    throw new ApiError(0, "network_error", message);
  }
  const text = await res.text();
  const data = text ? safeParse(text) : undefined;
  if (!res.ok) throw errorFromResponse(res.status, data);
  return data as T;
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
  balance_ore?: number | null;
  balance_nok?: string | null;
}

export interface User {
  id: number;
  email: string;
  role: Role;
  member_id: number | null;
  disabled: boolean;
}

export interface UserCreate {
  email: string;
  password?: string | null;
  role: Role;
  member_id?: number | null;
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
  | "adjustment_debit"
  | "settlement_charge"
  | "settlement_reversal"
  | "settlement_correction"
  | "refund";

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

export interface LedgerTxnRow extends LedgerTxn {
  member_name: string;
  member_reference: string;
}

export interface LedgerTxnsPage {
  transactions: LedgerTxnRow[];
  total: number;
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

// --- member departure (US-204, admin) --------------------------

export interface DepartureCheck {
  member_id: number;
  effective_date: string;
  current_status: MemberStatus | null;
  open_assignments: {
    charger_id: number;
    charger_name: string;
    effective_from: string;
  }[];
  unsettled_months: string[];
  balance_ore: number;
  balance_nok: string;
  would_refund_ore: number;
}

export interface DepartureResult extends DepartureCheck {
  status_changed: boolean;
  assignments_closed: number[];
  refund_txn_id: number | null;
  refunded_ore: number;
}

export function departureCheck(
  memberId: number,
  effectiveDate?: string,
): Promise<DepartureCheck> {
  const qs = effectiveDate ? `?effective_date=${encodeURIComponent(effectiveDate)}` : "";
  return get<DepartureCheck>(`/api/members/${memberId}/departure-check${qs}`);
}

export function processDeparture(
  memberId: number,
  body: { effective_date: string; refund?: boolean; refund_reference?: string },
): Promise<DepartureResult> {
  return post<DepartureResult>(`/api/members/${memberId}/departure`, body);
}

// --- charging access status (US-305, admin) -------------------

export type AccessAction = "warned" | "disabled" | "restored";

export interface AccessEvent {
  id: number;
  member_id: number;
  action: AccessAction;
  reason: string | null;
  note: string | null;
  created_at: string;
  created_by_user_id: number | null;
  email_message_id: number | null;
}

export interface AccessState {
  member_id: number;
  status: AccessAction | null;
  history: AccessEvent[];
}

export function getMemberAccess(memberId: number): Promise<AccessState> {
  return get<AccessState>(`/api/members/${memberId}/access`);
}

export function recordMemberAccess(
  memberId: number,
  body: { action: AccessAction; reason?: string; note?: string },
): Promise<AccessState & { event: AccessEvent }> {
  return post<AccessState & { event: AccessEvent }>(
    `/api/members/${memberId}/access`,
    body,
  );
}

// --- users (admin) -----------------------------------------------

export function listUsers(): Promise<{ users: User[] }> {
  return get<{ users: User[] }>("/api/users");
}

export function createUser(body: UserCreate): Promise<User> {
  return post<User>("/api/users", body);
}

export function setUserDisabled(id: number, disabled: boolean): Promise<User> {
  return post<User>(`/api/users/${id}/${disabled ? "disable" : "enable"}`);
}

export function setUserPassword(
  id: number,
  password: string,
): Promise<{ ok: boolean }> {
  return post<{ ok: boolean }>(`/api/users/${id}/password`, { password });
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

export function recordRefund(
  memberId: number,
  body: {
    amount: string;
    value_date?: string;
    reference?: string;
    allow_negative?: boolean;
  },
): Promise<LedgerTxn> {
  return post<LedgerTxn>(`/api/members/${memberId}/refunds`, body);
}

export function listLedgerTransactions(
  params: {
    limit?: number;
    offset?: number;
    memberId?: number | null;
    txnType?: string | null;
  } = {},
): Promise<LedgerTxnsPage> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  if (params.memberId != null) qs.set("member_id", String(params.memberId));
  if (params.txnType) qs.set("txn_type", params.txnType);
  return get<LedgerTxnsPage>(`/api/ledger-transactions?${qs.toString()}`);
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

export interface MyAccess {
  status: AccessAction | null;
  portal_url: string;
}

export function getMyAccess(): Promise<MyAccess> {
  return get<MyAccess>("/api/me/access");
}

// --- chargers (admin, Epic 3) -----------------------------------

export interface Charger {
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
}

export interface ChargerAssignment {
  id: number;
  charger_id: number;
  member_id: number;
  effective_from: string;
  effective_to: string | null;
  note: string | null;
  created_at: string;
}

export function listChargers(): Promise<{ chargers: Charger[] }> {
  return get<{ chargers: Charger[] }>("/api/chargers");
}

export function createCharger(body: {
  name: string;
  serial_no?: string;
  zaptec_id?: string;
  device_type?: string;
}): Promise<Charger> {
  return post<Charger>("/api/chargers", body);
}

export function updateCharger(
  chargerId: number,
  body: {
    name?: string;
    serial_no?: string | null;
    device_type?: string | null;
    is_active?: boolean;
  },
): Promise<Charger> {
  return patch<Charger>(`/api/chargers/${chargerId}`, body);
}

export function deleteCharger(chargerId: number): Promise<void> {
  return del<void>(`/api/chargers/${chargerId}`);
}

export function assignCharger(
  chargerId: number,
  body: { member_id: number; effective_from?: string; note?: string },
): Promise<{ assignment: ChargerAssignment }> {
  return post<{ assignment: ChargerAssignment }>(
    `/api/chargers/${chargerId}/assignments`,
    body,
  );
}

export function unassignCharger(
  chargerId: number,
  body: { effective_to?: string } = {},
): Promise<{ assignment: ChargerAssignment }> {
  return post<{ assignment: ChargerAssignment }>(
    `/api/chargers/${chargerId}/unassign`,
    body,
  );
}

export function chargerAssignments(
  chargerId: number,
): Promise<{ assignments: ChargerAssignment[] }> {
  return get<{ assignments: ChargerAssignment[] }>(
    `/api/chargers/${chargerId}/assignments`,
  );
}

// --- Zaptec sync + charging data (admin, Epic 4) ---------------

export interface SyncRun {
  id: number;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string;
  window_from: string | null;
  window_to: string | null;
  items_seen: number;
  items_imported: number;
  error: string | null;
}

export interface ZaptecStatus {
  enabled: boolean;
  installation_id: string | null;
  last: Record<string, SyncRun | null>;
  recent: SyncRun[];
  failures: number;
}

export function zaptecStatus(): Promise<ZaptecStatus> {
  return get<ZaptecStatus>("/api/zaptec/status");
}

export function syncChargers(): Promise<Record<string, number>> {
  return post<Record<string, number>>("/api/zaptec/sync/chargers");
}

export function syncSessions(month: string): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>(
    `/api/zaptec/sync/sessions?month=${encodeURIComponent(month)}`,
  );
}

export interface ConsumptionResponse {
  month: string;
  total_kwh: string;
  unassigned_kwh: string;
  by_member: { member_id: number; energy_kwh: string }[];
}

export function getConsumption(month: string): Promise<ConsumptionResponse> {
  return get<ConsumptionResponse>(
    `/api/charging/consumption?month=${encodeURIComponent(month)}`,
  );
}

export interface UnassignedResponse {
  month: string;
  total_kwh: string;
  chargers: {
    charger_zaptec_id: string;
    charger_id: number | null;
    charger_name: string | null;
    sessions: number;
    energy_kwh: string;
  }[];
}

export function getUnassigned(month: string): Promise<UnassignedResponse> {
  return get<UnassignedResponse>(
    `/api/charging/unassigned?month=${encodeURIComponent(month)}`,
  );
}

export function reresolveCharging(
  month: string,
): Promise<{ month: string; sessions_changed: number }> {
  return post<{ month: string; sessions_changed: number }>(
    `/api/charging/reresolve?month=${encodeURIComponent(month)}`,
  );
}

// --- settlement engine (admin, Epic 6) ------------------------

export type SettlementStatus = "draft" | "posted";
export type AllocationMethod = "equal" | "consumption";

export interface Settlement {
  id: number;
  period_month: string;
  status: SettlementStatus;
  invoice_kwh: string | null;
  invoice_total_nok: string | null;
  grid_kwh: string | null;
  attachment_filename: string | null;
  attachment_path: string | null;
  note: string | null;
  usage_frozen_at: string | null;
  created_at: string;
  posted_at: string | null;
}

export interface InvoiceLine {
  id: number;
  settlement_id: number;
  description: string;
  category: string | null;
  allocation_method: AllocationMethod;
  amount_ore: number;
  amount_nok: string;
  sort_order: number;
}

export interface SettlementMemberSnapshot {
  member_id: number;
  member_reference: string;
  full_name: string;
  is_active: number;
  participates_equal: number;
  consumption_kwh: string;
  session_count: number;
  balance_before_ore: number;
}

export interface SettlementAttachment {
  id: number;
  filename: string;
  bytes: number;
  uploaded_at: string;
}

export interface SettlementCorrectionMember {
  id: number;
  correction_id: number;
  member_id: number;
  consumption_kwh_before: string;
  consumption_kwh_after: string;
  original_charge_ore: number;
  corrected_charge_ore: number;
  delta_ore: number;
  ledger_txn_id: number | null;
}

export interface SettlementCorrection {
  id: number;
  settlement_id: number;
  sequence: number;
  original_total_ore: number;
  corrected_total_ore: number;
  created_at: string;
  created_by_user_id: number | null;
  members: SettlementCorrectionMember[];
}

export interface SettlementDetail {
  settlement: Settlement;
  lines: InvoiceLine[];
  snapshot: SettlementMemberSnapshot[];
  attachments: SettlementAttachment[];
  corrections: SettlementCorrection[];
  correction_pending?: boolean;
}

export interface CorrectionAssessmentMember {
  member_id: number;
  member_reference: string;
  full_name: string;
  in_snapshot: boolean;
  consumption_kwh_before: string;
  consumption_kwh_after: string;
  charged_ore: number;
  charged_nok: string;
  corrected_charge_ore: number;
  corrected_charge_nok: string;
  delta_ore: number;
  delta_nok: string;
}

export interface CorrectionAssessment {
  settlement_id: number;
  period_month: string;
  status: string;
  has_changes: boolean;
  sequence_next: number;
  unresolved_late_flags: number;
  original_total_charged_ore: number;
  corrected_total_charged_ore: number;
  members: CorrectionAssessmentMember[];
}

export function assessCorrection(id: number): Promise<CorrectionAssessment> {
  return get<CorrectionAssessment>(`/api/settlement/${id}/correction`);
}

export function postCorrection(
  id: number,
): Promise<CorrectionAssessment & { correction_id: number; sequence: number; members_adjusted: number; emails_queued: number }> {
  return post(`/api/settlement/${id}/correction`);
}

export interface PreviewMemberRow {
  member_id: number;
  member_reference: string;
  full_name: string;
  consumption_kwh: string;
  session_count: number;
  balance_before_nok: string;
  charge_nok: string;
  charge_ore: number;
  balance_after_nok: string;
  balance_after_ore: number;
  lines: {
    invoice_line_id: number | null;
    description: string;
    kind: AllocationMethod;
    amount_nok: string;
  }[];
}

export interface SettlementPreview {
  settlement_id: number;
  period_month: string;
  status: string;
  invoice_kwh: string | null;
  grid_kwh: string | null;
  invoice_lines_total_nok: string;
  total_charged_nok: string;
  total_charged_ore: number;
  members: PreviewMemberRow[];
  lines: {
    line_id: number;
    description: string;
    kind: AllocationMethod;
    amount_ore: number;
    allocated_ore: number;
    recipients: number;
  }[];
  warnings: { code: string; [k: string]: unknown }[];
}

export function listSettlements(): Promise<{ settlements: Settlement[] }> {
  return get<{ settlements: Settlement[] }>("/api/settlement");
}

export function getSettlement(id: number): Promise<SettlementDetail> {
  return get<SettlementDetail>(`/api/settlement/${id}`);
}

export function createSettlementDraft(
  period_month: string,
): Promise<{ settlement: Settlement }> {
  return post<{ settlement: Settlement }>("/api/settlement/drafts", {
    period_month,
  });
}

export function setSettlementInvoice(
  id: number,
  body: { invoice_kwh?: string; note?: string },
): Promise<SettlementDetail> {
  return put<SettlementDetail>(`/api/settlement/${id}/invoice`, body);
}

export function addInvoiceLine(
  id: number,
  body: {
    description: string;
    allocation_method: AllocationMethod;
    amount: string;
    category?: string;
  },
): Promise<{ line: InvoiceLine }> {
  return post<{ line: InvoiceLine }>(`/api/settlement/${id}/lines`, body);
}

export function updateInvoiceLine(
  id: number,
  lineId: number,
  body: Partial<{
    description: string;
    allocation_method: AllocationMethod;
    amount: string;
    category: string | null;
  }>,
): Promise<SettlementDetail> {
  return patch<SettlementDetail>(`/api/settlement/${id}/lines/${lineId}`, body);
}

export function deleteInvoiceLine(
  id: number,
  lineId: number,
): Promise<SettlementDetail> {
  return del<SettlementDetail>(`/api/settlement/${id}/lines/${lineId}`);
}

export async function uploadSettlementAttachments(
  id: number,
  files: File[],
): Promise<SettlementDetail | undefined> {
  let detail: SettlementDetail | undefined;
  for (const file of files) {
    const form = new FormData();
    form.append("files", file);
    detail = await postForm<SettlementDetail>(
      `/api/settlement/${id}/attachments`,
      form,
    );
  }
  return detail;
}

export function deleteSettlementAttachment(
  id: number,
  attachmentId: number,
): Promise<SettlementDetail> {
  return del<SettlementDetail>(
    `/api/settlement/${id}/attachments/${attachmentId}`,
  );
}

export function freezeSettlement(id: number): Promise<SettlementDetail> {
  return post<SettlementDetail>(`/api/settlement/${id}/freeze`);
}

export function previewSettlement(id: number): Promise<SettlementPreview> {
  return get<SettlementPreview>(`/api/settlement/${id}/preview`);
}

export function postSettlement(
  id: number,
): Promise<SettlementPreview & { members_charged: number; emails_queued: number }> {
  return post<SettlementPreview & { members_charged: number; emails_queued: number }>(
    `/api/settlement/${id}/post`,
  );
}

export interface SettlementReportList {
  settlement_id: number;
  period_month: string;
  summary_url: string;
  members: { member_id: number; full_name: string; charge_nok: string; url: string }[];
}

export function settlementReports(id: number): Promise<SettlementReportList> {
  return get<SettlementReportList>(`/api/settlement/${id}/reports`);
}

// --- notifications + system (admin) ---------------------------

export interface EmailMessage {
  id: number;
  to_address: string;
  subject: string;
  template: string | null;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  next_attempt_at: string;
  created_at: string;
  sent_at: string | null;
}

export interface NotificationsResponse {
  stats: { queued: number; sent: number; failed: number; next_attempt_at: string | null };
  messages: EmailMessage[];
}

export function listNotifications(): Promise<NotificationsResponse> {
  return get<NotificationsResponse>("/api/notifications");
}

export function processNotifications(): Promise<Record<string, number>> {
  return post<Record<string, number>>("/api/notifications/process");
}

export interface SystemHealth {
  version: string;
  schema_version: number;
  zaptec: {
    enabled: boolean;
    installation_id: string | null;
    last: Record<string, SyncRun | null>;
    failed_runs: number;
  };
  email: { queued: number; sent: number; failed: number; next_attempt_at: string | null };
  low_balance?: { warned_total: number; members_below: number };
  corrections: { settlements_with_pending: number };
  access: { disabled: number };
  failed_jobs: number;
  ok: boolean;
}

export function systemHealth(): Promise<SystemHealth> {
  return get<SystemHealth>("/api/system/health");
}

// --- member: settlement history (US-904) ---------------------

export interface MySettlement {
  settlement_id: number;
  period_month: string;
  posted_at: string | null;
  consumption_kwh: string;
  charge_nok: string;
  balance_after_nok: string;
  report_url: string;
}

export function getMySettlements(): Promise<{ settlements: MySettlement[] }> {
  return get<{ settlements: MySettlement[] }>("/api/me/settlements");
}

// --- forecasting + low-balance (Epic 8, US-801..805) ---------

/**
 * Per-member forecast read-model. Mirrors `MemberForecastOut` on the backend:
 * a flat object that is always fully populated. When `available` is `false`
 * the numeric fields are zeroed and `reason` explains why
 * (`"insufficient_history"` | `"no_grid_kwh"`); all money fields are canonical
 * integer øre, `forecast_kwh` / `rate_ore_per_kwh` are Decimal strings.
 */
export interface MemberForecast {
  member_id: number;
  available: boolean;
  forecast_kwh: string;
  rate_ore_per_kwh: string;
  rate_source: "derived" | "override" | null;
  equal_share_ore: number;
  forecast_monthly_cost_ore: number;
  recommended_minimum_ore: number;
  balance_ore: number;
  recommended_topup_ore: number;
  low_balance: boolean;
  severity: "low" | "critical" | null;
  reason: string | null;
}

export interface MemberConsumption {
  member_id: number;
  month: string;
  consumption_kwh: string;
  session_count: number;
}

export interface ForecastSettings {
  rate_override_ore_per_kwh: number | null;
  buffer_months: number;
  notify_cooldown_days: number;
  lookback_settlements: number;
  updated_at: string | null;
  updated_by_user_id: number | null;
}

/**
 * Partial update of the forecast-settings singleton. Only present keys are
 * applied; an explicit `rate_override_ore_per_kwh: null` clears the override.
 */
export type ForecastSettingsUpdate = Partial<{
  rate_override_ore_per_kwh: number | null;
  buffer_months: number;
  notify_cooldown_days: number;
  lookback_settlements: number;
}>;

export interface LowBalanceScanResult {
  scanned: number;
  below: number;
  queued: number;
  suppressed: number;
}

export function getMyForecast(): Promise<MemberForecast> {
  return get<MemberForecast>("/api/me/forecast");
}

export function getMyConsumption(month?: string): Promise<MemberConsumption> {
  const qs = month ? `?month=${encodeURIComponent(month)}` : "";
  return get<MemberConsumption>(`/api/me/consumption${qs}`);
}

export function getForecastSettings(): Promise<ForecastSettings> {
  return get<ForecastSettings>("/api/forecast/settings");
}

export function updateForecastSettings(
  body: ForecastSettingsUpdate,
): Promise<ForecastSettings> {
  return put<ForecastSettings>("/api/forecast/settings", body);
}

export function getForecastMembers(): Promise<{ members: MemberForecast[] }> {
  return get<{ members: MemberForecast[] }>("/api/forecast/members");
}

export function runLowBalanceScan(): Promise<LowBalanceScanResult> {
  return post<LowBalanceScanResult>("/api/notifications/low-balance-scan");
}

// --- passwordless / reset (US-102 / US-103) -----------------

export function requestMagicLink(email: string): Promise<{ ok: boolean }> {
  return post<{ ok: boolean }>("/api/auth/magic-link", { email });
}

export function consumeMagicLink(token: string): Promise<LoginResponse> {
  return post<LoginResponse>("/api/auth/magic-link/consume", { token });
}

export function requestPasswordReset(email: string): Promise<{ ok: boolean }> {
  return post<{ ok: boolean }>("/api/auth/password-reset/request", { email });
}

export function consumePasswordReset(
  token: string,
  password: string,
): Promise<{ ok: boolean }> {
  return post<{ ok: boolean }>("/api/auth/password-reset/consume", {
    token,
    password,
  });
}
