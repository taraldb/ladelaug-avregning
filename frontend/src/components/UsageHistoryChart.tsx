import type { MemberHistoryMonth } from "../api/client";
import { useChartHeight, useIsNarrow } from "../hooks/useMediaQuery";
import { formatNok } from "../lib/format";
import {
  AXIS_TICK,
  CHART_COLORS,
  GRID_STROKE,
  TOOLTIP_PROPS,
  monthTick,
} from "./chartTheme";
import Money from "./Money";
import Table, { type Column } from "./Table";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * The member dashboard's rolling history: grouped bars for metered kWh (left
 * axis) and, once the month is settled, the kr charge (right axis), with the
 * month-end ledger balance as a line on the kr axis. Recharts `ComposedChart`;
 * the `<Table>` underneath (newest first) is the accessible source of truth, so
 * the chart itself is `aria-hidden`.
 */

interface Row {
  month: string;
  kwh: number;
  sessions: number;
  charge: number | null;
  chargeLabel: string;
  balance: number;
  balanceNok: string;
  negative: boolean;
}

function toRow(m: MemberHistoryMonth): Row {
  return {
    month: m.month,
    kwh: Number(m.consumption_kwh) || 0,
    sessions: m.session_count,
    charge: m.settled && m.charge_ore != null ? m.charge_ore / 100 : null,
    chargeLabel:
      m.settled && m.charge_nok != null ? formatNok(m.charge_nok) : "ikke avregnet",
    balance: m.balance_end_ore / 100,
    balanceNok: formatNok(m.balance_end_nok),
    negative: m.balance_end_ore < 0,
  };
}

const columns: Column<MemberHistoryMonth>[] = [
  { key: "month", card: "title", header: "Måned", render: (m) => m.month },
  {
    key: "kwh",
    header: "kWh",
    className: "text-right tabular-nums",
    render: (m) => m.consumption_kwh,
  },
  {
    key: "sessions",
    header: "Ladeøkter",
    className: "text-right tabular-nums",
    render: (m) => m.session_count,
  },
  {
    key: "charge",
    header: "Kostnad",
    className: "text-right tabular-nums",
    render: (m) =>
      m.settled && m.charge_nok != null ? <Money value={m.charge_nok} /> : "–",
  },
  {
    key: "balance",
    header: "Saldo",
    className: "text-right tabular-nums",
    render: (m) => (
      <Money
        value={m.balance_end_nok}
        className={m.balance_end_ore < 0 ? "text-rose-400" : "text-slate-200"}
      />
    ),
  },
];

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: Row;
}

function BalanceDot({ cx, cy, payload }: DotProps) {
  if (cx == null || cy == null || !payload) return null;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={3}
      fill={payload.negative ? CHART_COLORS.negative : CHART_COLORS.balance}
    />
  );
}

interface TipProps {
  active?: boolean;
  payload?: { payload: Row }[];
}

function ChartTooltip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div
      style={TOOLTIP_PROPS.contentStyle}
      className="px-3 py-2 text-xs shadow-lg"
    >
      <div className="font-semibold text-slate-100">{r.month}</div>
      <div className="mt-1 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-slate-300">
        <span className="text-slate-400">Forbruk</span>
        <span className="tabular-nums">
          {r.kwh.toFixed(2)} kWh · {r.sessions} økter
        </span>
        <span className="text-slate-400">Kostnad</span>
        <span className="tabular-nums">{r.chargeLabel}</span>
        <span className="text-slate-400">Saldo</span>
        <span className="tabular-nums">{r.balanceNok}</span>
      </div>
    </div>
  );
}

/** A month is "active" once the member has consumption, sessions, or a charge in
 * it. The API hands back a fixed rolling window (12 months); we only render from
 * the first active month to the last, so a member with a short history isn't
 * padded with empty leading months. Interior gaps are kept — they are real. */
function isActive(m: MemberHistoryMonth): boolean {
  return (
    Number(m.consumption_kwh) > 0 ||
    m.session_count > 0 ||
    m.settled ||
    (m.charge_ore ?? 0) !== 0
  );
}

function trimToData(months: MemberHistoryMonth[]): MemberHistoryMonth[] {
  const first = months.findIndex(isActive);
  if (first === -1) return [];
  let last = months.length - 1;
  while (last > first && !isActive(months[last])) last -= 1;
  return months.slice(first, last + 1);
}

export default function UsageHistoryChart({
  months,
}: {
  months: MemberHistoryMonth[];
}) {
  const narrow = useIsNarrow();
  const chartHeight = useChartHeight(220, 180);
  const visible = trimToData(months);
  if (visible.length === 0) {
    return <p className="text-sm text-slate-400">Ingen forbruksdata ennå.</p>;
  }

  const rows = visible.map(toRow);
  const totalKwh = rows.reduce((sum, r) => sum + r.kwh, 0).toFixed(2);
  const tableRows = [...visible].reverse(); // newest month on top

  return (
    <figure className="space-y-3">
      <figcaption className="text-xs text-slate-400">
        Siste {rows.length} måneder · {totalKwh} kWh totalt. Hold pekeren over en
        måned for detaljer.
      </figcaption>

      <div
        className="rounded-lg border border-slate-800 bg-slate-900/40 p-3"
        aria-hidden="true"
      >
        <ResponsiveContainer width="100%" height={chartHeight}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID_STROKE} vertical={false} />
            <XAxis
            dataKey="month"
            tickFormatter={monthTick}
            tick={AXIS_TICK}
            interval={narrow ? "preserveStartEnd" : 0}
            minTickGap={narrow ? 24 : 5}
          />
            <YAxis
              yAxisId="kwh"
              tick={AXIS_TICK}
              width={40}
              label={{
                value: "kWh",
                angle: -90,
                position: "insideLeft",
                fill: AXIS_TICK.fill,
                fontSize: 11,
              }}
            />
            <YAxis
              yAxisId="nok"
              orientation="right"
              tick={AXIS_TICK}
              width={52}
              label={{
                value: "kr",
                angle: 90,
                position: "insideRight",
                fill: AXIS_TICK.fill,
                fontSize: 11,
              }}
            />
            <ReferenceLine yAxisId="nok" y={0} stroke={GRID_STROKE} />
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar
              yAxisId="kwh"
              dataKey="kwh"
              name="Forbruk (kWh)"
              fill={CHART_COLORS.assigned}
              maxBarSize={22}
            />
            <Bar
              yAxisId="nok"
              dataKey="charge"
              name="Kostnad (kr)"
              fill={CHART_COLORS.cost}
              maxBarSize={22}
            />
            <Line
              yAxisId="nok"
              dataKey="balance"
              name="Saldo"
              type="monotone"
              stroke={CHART_COLORS.balance}
              strokeWidth={2}
              dot={<BalanceDot />}
              activeDot={{ r: 4 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <Table columns={columns} rows={tableRows} rowKey={(m) => m.month} />
    </figure>
  );
}
