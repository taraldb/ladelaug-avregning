import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  getChargingSessions,
  listChargers,
  listMembers,
  type ChargingSessionRow,
} from "../api/client";
import { formatDateTime, formatDuration } from "../lib/format";
import {
  AXIS_TICK,
  CHART_COLORS,
  ChartCard,
  GRID_STROKE,
  TOOLTIP_PROPS,
} from "./chartTheme";
import SessionDetailModal from "./SessionDetailModal";
import Table, { type Column } from "./Table";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Browsable charging-session history for one month: a session-size distribution
 * sparkline over the whole month, then a filterable, paginated table. Fed by the
 * existing `GET /api/charging/sessions` (raw rows); member and charger names are
 * joined client-side.
 *
 * Month is normally picked here. Pass a `month` prop to drive it from a shared
 * picker instead — the built-in month input is then hidden (the member filter
 * stays local).
 */

const PAGE_SIZE = 25;
const SPARK_CAP = 500; // `list_sessions` caps `limit` at 500

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

const SPLIT_LABEL: Record<ChargingSessionRow["split_method"], string> = {
  none: "Hel økt",
  interval: "Delt (intervall)",
  duration: "Delt (varighet)",
};

const BUCKETS: { label: string; lo: number; hi: number }[] = [
  { label: "0–2", lo: 0, hi: 2 },
  { label: "2–5", lo: 2, hi: 5 },
  { label: "5–10", lo: 5, hi: 10 },
  { label: "10–20", lo: 10, hi: 20 },
  { label: "20–40", lo: 20, hi: 40 },
  { label: "40+", lo: 40, hi: Infinity },
];

function SessionSizeSparkline({ month }: { month: string }) {
  const { data } = useSWR(["/api/charging/sessions/spark", month] as const, () =>
    getChargingSessions(month, { limit: SPARK_CAP }),
  );

  const dist = useMemo(() => {
    const counts = BUCKETS.map((b) => ({ label: b.label, count: 0 }));
    for (const s of data?.sessions ?? []) {
      const kwh = Number(s.energy_kwh) || 0;
      const i = BUCKETS.findIndex((b) => kwh >= b.lo && kwh < b.hi);
      if (i >= 0) counts[i].count += 1;
    }
    return counts;
  }, [data]);

  const total = data?.total ?? 0;
  if (!data || total === 0) return null;

  return (
    <div className="mb-3">
      <p className="mb-1 text-xs text-slate-400">
        Fordeling etter øktstørrelse (kWh){" "}
        {total > SPARK_CAP && `· første ${SPARK_CAP} av ${total}`}
      </p>
      <ResponsiveContainer width="100%" height={64}>
        <BarChart data={dist} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis hide />
          <Tooltip
            {...TOOLTIP_PROPS}
            formatter={(value) => [`${Number(value)} økter`, ""]}
            cursor={{ fill: "#1e293b55" }}
          />
          <Bar dataKey="count" fill={CHART_COLORS.assigned} radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function SessionHistory({
  month: monthProp,
  onMonthChange,
}: {
  month?: string;
  onMonthChange?: (month: string) => void;
} = {}) {
  const [monthState, setMonthState] = useState(thisMonth());
  const controlled = monthProp != null;
  const month = controlled ? monthProp : monthState;
  const setMonth = onMonthChange ?? setMonthState;
  const [memberId, setMemberId] = useState("");
  const [page, setPage] = useState(0);
  const [openSession, setOpenSession] = useState<ChargingSessionRow | null>(null);

  // A month change from any source resets pagination.
  useEffect(() => setPage(0), [month]);

  const { data: membersData } = useSWR("/api/members", () => listMembers());
  const { data: chargersData } = useSWR("/api/chargers", () => listChargers());
  const members = membersData?.members ?? [];

  const memberName = new Map(members.map((m) => [m.id, m.full_name]));
  const chargerName = new Map(
    (chargersData?.chargers ?? []).map((c) => [c.id, c.name]),
  );

  const memberLabel = (s: ChargingSessionRow) =>
    s.member_id != null
      ? (memberName.get(s.member_id) ?? `#${s.member_id}`)
      : (s.user_full_name ?? "Ikke tilordnet");
  const chargerLabel = (s: ChargingSessionRow) =>
    (s.charger_id != null && chargerName.get(s.charger_id)) ||
    s.charger_zaptec_id;

  const { data, isLoading } = useSWR(
    ["/api/charging/sessions", month, memberId, page] as const,
    () =>
      getChargingSessions(month, {
        memberId: memberId ? Number(memberId) : null,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  );

  const rows = data?.sessions ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns: Column<ChargingSessionRow>[] = [
    { key: "start", card: "title", header: "Start", render: (s) => formatDateTime(s.started_at) },
    { key: "member", header: "Medlem", render: memberLabel },
    { key: "charger", header: "Lader", render: chargerLabel },
    {
      key: "kwh",
      header: "kWh",
      className: "text-right tabular-nums",
      render: (s) => s.energy_kwh,
    },
    {
      key: "duration",
      header: "Varighet",
      className: "text-right tabular-nums",
      render: (s) => formatDuration(s.started_at, s.ended_at),
    },
    {
      key: "split",
      header: "Deling",
      render: (s) => SPLIT_LABEL[s.split_method] ?? s.split_method,
    },
  ];

  return (
    <ChartCard
      title="Ladeøkter"
      hint={
        <span className="flex flex-wrap items-center gap-3">
          {!controlled && (
            <label className="flex items-center gap-1.5">
              <span>Måned</span>
              <input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
              />
            </label>
          )}
          <label className="flex items-center gap-1.5">
            <span>Medlem</span>
            <select
              value={memberId}
              onChange={(e) => {
                setMemberId(e.target.value);
                setPage(0);
              }}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            >
              <option value="">Alle</option>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.member_reference} – {m.full_name}
                </option>
              ))}
            </select>
          </label>
        </span>
      }
    >
      <SessionSizeSparkline month={month} />

      <p className="mb-1 text-xs text-slate-500">
        Klikk en rad for energi- og månedsfordeling inne i økten.
      </p>
      <Table
        columns={columns}
        rows={rows}
        rowKey={(s) => s.id}
        onRowClick={setOpenSession}
        empty={isLoading ? "Laster …" : `Ingen ladeøkter i ${month}`}
      />

      {openSession && (
        <SessionDetailModal
          session={openSession}
          memberName={memberLabel(openSession)}
          chargerName={chargerLabel(openSession)}
          onClose={() => setOpenSession(null)}
        />
      )}

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-400">
        <span>{total} ladeøkter</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-md border border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Forrige
          </button>
          <span>
            Side {page + 1} av {pageCount}
          </span>
          <button
            type="button"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Neste
          </button>
        </div>
      </div>
    </ChartCard>
  );
}
