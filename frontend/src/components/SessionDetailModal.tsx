import useSWR from "swr";
import {
  getChargingSessionDetail,
  type ChargingSessionRow,
} from "../api/client";
import { formatDateTime, formatDuration } from "../lib/format";
import Modal from "./Modal";
import Table, { type Column } from "./Table";
import {
  AXIS_TICK,
  CHART_COLORS,
  GRID_STROKE,
  TOOLTIP_PROPS,
} from "./chartTheme";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Drill-down for one row of the "Ladeøkter" table: the 15-minute energy curve
 * inside the session (from `charging_intervals`), with a marker at every month
 * boundary, plus how the total was quantised to each calendar month (the
 * `charging_sessions` parts + their `split_method`). Fed by
 * `GET /api/charging/sessions/{zaptec_session_id}`.
 */

const SPLIT_LABEL: Record<ChargingSessionRow["split_method"], string> = {
  none: "hele i én måned",
  interval: "delt etter intervaller",
  duration: "delt etter varighet",
};

// One colour per calendar month the session touches, in touch order.
const MONTH_COLORS = [
  CHART_COLORS.assigned,
  CHART_COLORS.cost,
  CHART_COLORS.balance,
  CHART_COLORS.unassigned,
];

const kwh = (v: number | string) =>
  `${Number(v).toLocaleString("nb-NO", { maximumFractionDigits: 2 })} kWh`;

function clockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function SessionDetailModal({
  session,
  memberName,
  chargerName,
  onClose,
}: {
  session: ChargingSessionRow;
  memberName: string;
  chargerName: string;
  onClose: () => void;
}) {
  const { data, error, isLoading } = useSWR(
    ["/api/charging/sessions", session.zaptec_session_id] as const,
    () => getChargingSessionDetail(session.zaptec_session_id),
  );

  const parts = data?.parts ?? [];
  const intervals = data?.intervals ?? [];

  const monthOrder = parts.map((p) => p.period_month);
  const colorForMonth = (m: string) => {
    const i = monthOrder.indexOf(m);
    return MONTH_COLORS[(i < 0 ? 0 : i) % MONTH_COLORS.length];
  };

  const points = intervals.map((iv) => ({
    start: iv.interval_start,
    energy: Number(iv.energy_kwh) || 0,
    month: iv.period_month,
  }));

  // First interval of each month after the first — where to drop a boundary line.
  const boundaries: { start: string; month: string }[] = [];
  const seen = new Set<string>();
  for (const p of points) {
    if (!seen.has(p.month)) {
      seen.add(p.month);
      if (seen.size > 1) boundaries.push({ start: p.start, month: p.month });
    }
  }

  const total = parts.reduce((s, p) => s + (Number(p.energy_kwh) || 0), 0);

  const partColumns: Column<ChargingSessionRow>[] = [
    { key: "month", header: "Måned", render: (p) => p.period_month },
    {
      key: "energy",
      header: "kWh",
      className: "text-right tabular-nums",
      render: (p) => kwh(p.energy_kwh),
    },
    {
      key: "share",
      header: "Andel",
      className: "text-right tabular-nums",
      render: (p) =>
        total > 0
          ? `${(((Number(p.energy_kwh) || 0) / total) * 100).toLocaleString("nb-NO", {
              maximumFractionDigits: 1,
            })} %`
          : "–",
    },
    {
      key: "method",
      header: "Fordeling",
      render: (p) => SPLIT_LABEL[p.split_method] ?? p.split_method,
    },
  ];

  return (
    <Modal
      open
      wide
      title={`Ladeøkt ${session.period_month}`}
      onClose={onClose}
    >
      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400 sm:grid-cols-3">
        <div>
          <dt className="text-slate-500">Medlem</dt>
          <dd className="text-slate-200">{memberName}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Lader</dt>
          <dd className="text-slate-200">{chargerName}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Total</dt>
          <dd className="text-slate-200">{kwh(total || session.energy_kwh)}</dd>
        </div>
        <div className="col-span-2 sm:col-span-3">
          <dt className="text-slate-500">Tidsrom</dt>
          <dd className="text-slate-200">
            {formatDateTime(session.started_at)} – {formatDateTime(session.ended_at)}{" "}
            <span className="text-slate-500">
              ({formatDuration(session.started_at, session.ended_at)})
            </span>
          </dd>
        </div>
      </dl>

      {error ? (
        <p className="text-sm text-rose-400">Kunne ikke laste ladeøkten.</p>
      ) : isLoading ? (
        <p className="text-sm text-slate-400">Laster …</p>
      ) : (
        <>
          {points.length > 0 ? (
            <>
              <p className="mb-1 text-xs text-slate-400">
                Energi per 15-minutt{" "}
                {boundaries.length > 0 && "· stiplet linje = månedsskifte"}
              </p>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                  <XAxis
                    dataKey="start"
                    tick={AXIS_TICK}
                    tickFormatter={clockTime}
                    minTickGap={32}
                  />
                  <YAxis
                    tick={AXIS_TICK}
                    width={44}
                    label={{
                      value: "kWh",
                      angle: -90,
                      position: "insideLeft",
                      fill: AXIS_TICK.fill,
                      fontSize: 11,
                    }}
                  />
                  <Tooltip
                    {...TOOLTIP_PROPS}
                    labelFormatter={(v) => formatDateTime(String(v))}
                    formatter={(value, _n, item) => [
                      kwh(Number(value)),
                      (item?.payload as { month: string })?.month ?? "kWh",
                    ]}
                  />
                  {boundaries.map((b) => (
                    <ReferenceLine
                      key={b.start}
                      x={b.start}
                      stroke={CHART_COLORS.reference}
                      strokeDasharray="4 3"
                      label={{
                        value: b.month,
                        position: "top",
                        fill: AXIS_TICK.fill,
                        fontSize: 10,
                      }}
                    />
                  ))}
                  <Bar dataKey="energy" name="kWh" radius={[2, 2, 0, 0]}>
                    {points.map((p) => (
                      <Cell key={p.start} fill={colorForMonth(p.month)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </>
          ) : (
            <p className="rounded-md border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-400">
              Ingen intervalldata importert for denne økten – Zaptec-synken hentet
              den uten <code>EnergyDetails</code>. Fordelingen under er da regnet
              ut {parts.length > 1 ? "etter varighet" : "direkte"}.
            </p>
          )}

          <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Fordelt på måned
          </p>
          <Table
            columns={partColumns}
            rows={parts}
            rowKey={(p) => p.period_month}
            empty="Ingen data"
          />
        </>
      )}
    </Modal>
  );
}
