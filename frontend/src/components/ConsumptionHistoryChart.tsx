import useSWR from "swr";
import { getChargingHistory, type ChargingHistoryMonth } from "../api/client";
import {
  AXIS_TICK,
  CHART_COLORS,
  ChartCard,
  GRID_STROKE,
  TOOLTIP_PROPS,
  monthTick,
} from "./chartTheme";
import Table, { type Column } from "./Table";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Grid consumption over a rolling ~12-month window: stacked bars for kWh
 * attributed to a member (emerald) vs. metered-but-unattributed (amber), with the
 * supplier's invoiced kWh drawn as a dashed line so metering-vs-invoice drift is
 * visible on settled months. Fed by `GET /api/charging/history`.
 */

const MONTHS = 12;

interface Row {
  month: string;
  assigned: number;
  unassigned: number;
  grid: number;
  invoice: number | null;
  settled: boolean;
  sessions: number;
}

function toRow(m: ChargingHistoryMonth): Row {
  return {
    month: m.month,
    assigned: Number(m.assigned_kwh) || 0,
    unassigned: Number(m.unassigned_kwh) || 0,
    grid: Number(m.grid_kwh) || 0,
    invoice: m.invoice_kwh == null ? null : Number(m.invoice_kwh),
    settled: m.settled,
    sessions: m.session_count,
  };
}

const kwh = (v: number) => `${v.toLocaleString("nb-NO", { maximumFractionDigits: 2 })} kWh`;

const columns: Column<Row>[] = [
  { key: "month", header: "Måned", render: (r) => r.month },
  {
    key: "assigned",
    header: "Tilordnet",
    className: "text-right tabular-nums",
    render: (r) => kwh(r.assigned),
  },
  {
    key: "unassigned",
    header: "Ikke tilordnet",
    className: "text-right tabular-nums",
    render: (r) => kwh(r.unassigned),
  },
  {
    key: "grid",
    header: "Målt total",
    className: "text-right tabular-nums",
    render: (r) => kwh(r.grid),
  },
  {
    key: "invoice",
    header: "Faktura",
    className: "text-right tabular-nums",
    render: (r) => (r.invoice == null ? "–" : kwh(r.invoice)),
  },
  {
    key: "sessions",
    header: "Ladeøkter",
    className: "text-right tabular-nums",
    render: (r) => r.sessions,
  },
];

export default function ConsumptionHistoryChart() {
  const { data, error, isLoading } = useSWR("/api/charging/history", () =>
    getChargingHistory(MONTHS),
  );

  if (error) {
    return (
      <ChartCard title="Nettforbruk over tid">
        <p className="text-sm text-rose-400">Kunne ikke laste forbrukshistorikk.</p>
      </ChartCard>
    );
  }

  const rows = (data?.months ?? []).map(toRow);
  const total = rows.reduce((s, r) => s + r.grid, 0);

  return (
    <ChartCard
      title="Nettforbruk over tid"
      hint={
        isLoading
          ? "Laster …"
          : `Siste ${rows.length} måneder · ${kwh(total)} målt totalt. Stolpene er forbruk tilordnet / ikke tilordnet et medlem; stiplet linje er fakturert kWh.`
      }
    >
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="month" tickFormatter={monthTick} tick={AXIS_TICK} />
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
            formatter={(value, name) => [kwh(Number(value)), name]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar
            dataKey="assigned"
            name="Tilordnet medlem"
            stackId="kwh"
            fill={CHART_COLORS.assigned}
          />
          <Bar
            dataKey="unassigned"
            name="Ikke tilordnet medlem"
            stackId="kwh"
            fill={CHART_COLORS.unassigned}
          />
          <Line
            dataKey="invoice"
            name="Fakturert kWh"
            type="monotone"
            stroke={CHART_COLORS.reference}
            strokeDasharray="4 3"
            strokeWidth={2}
            connectNulls={false}
            dot={{ r: 3 }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
          Vis tall
        </summary>
        <div className="mt-2">
          <Table
            columns={columns}
            rows={[...rows].reverse()}
            rowKey={(r) => r.month}
            empty={isLoading ? "Laster …" : "Ingen forbruksdata"}
          />
        </div>
      </details>
    </ChartCard>
  );
}
