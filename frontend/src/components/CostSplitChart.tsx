import useSWR from "swr";
import { getChargingHistory, type ChargingHistoryMonth } from "../api/client";
import { formatNok } from "../lib/format";
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
 * How each posted month's supplier invoice split between faste kostnader (lines
 * split equally, drawn as the bottom bar segment) and forbrukskostnader (lines
 * allocated by kWh share, stacked on top) — in kroner on the left axis, with the
 * consumption share as a percentage line on the right axis. Reuses the
 * `GET /api/charging/history` payload (SWR dedupes with `ConsumptionHistoryChart`
 * / `GridRateChart`).
 */

const MONTHS = 12;

interface Row {
  month: string;
  consumption: number;
  fixed: number;
  total: number;
  consumptionPct: number;
  fixedPct: number;
}

/** A settled month only enters the chart once it carries an itemised split. */
function toRow(m: ChargingHistoryMonth): Row | null {
  if (m.consumption_cost_nok == null || m.fixed_cost_nok == null) return null;
  const consumption = Number(m.consumption_cost_nok) || 0;
  const fixed = Number(m.fixed_cost_nok) || 0;
  const total = consumption + fixed;
  return {
    month: m.month,
    consumption,
    fixed,
    total,
    consumptionPct: total ? (consumption / total) * 100 : 0,
    fixedPct: total ? (fixed / total) * 100 : 0,
  };
}

const kr = (v: number) => formatNok(String(v));
const pct = (v: number) =>
  `${v.toLocaleString("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;

const columns: Column<Row>[] = [
  { key: "month", header: "Måned", render: (r) => r.month },
  {
    key: "fixed",
    header: "Faste kostnader",
    className: "text-right tabular-nums",
    render: (r) => `${kr(r.fixed)} · ${pct(r.fixedPct)}`,
  },
  {
    key: "consumption",
    header: "Forbrukskostnader",
    className: "text-right tabular-nums",
    render: (r) => `${kr(r.consumption)} · ${pct(r.consumptionPct)}`,
  },
  {
    key: "total",
    header: "Sum faktura",
    className: "text-right tabular-nums",
    render: (r) => kr(r.total),
  },
];

export default function CostSplitChart() {
  const { data, error, isLoading } = useSWR("/api/charging/history", () =>
    getChargingHistory(MONTHS),
  );

  if (error) {
    return (
      <ChartCard title="Kostnadsfordeling">
        <p className="text-sm text-rose-400">Kunne ikke laste kostnadshistorikk.</p>
      </ChartCard>
    );
  }

  const rows = (data?.months ?? [])
    .map(toRow)
    .filter((r): r is Row => r !== null);
  const latest = rows.at(-1);

  return (
    <ChartCard
      title="Kostnadsfordeling"
      hint={
        isLoading
          ? "Laster …"
          : rows.length === 0
            ? "Ingen avregnede måneder med fakturalinjer ennå."
            : `Faste kostnader (delt likt) og forbrukskostnader (etter kWh) i kr per avregnet måned; linjen er forbruksandelen i % (høyre akse). Siste: ${kr(
                latest?.consumption ?? 0,
              )} forbruk (${pct(latest?.consumptionPct ?? 0)}) · ${kr(
                latest?.fixed ?? 0,
              )} fast (${pct(latest?.fixedPct ?? 0)}).`
      }
    >
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="month" tickFormatter={monthTick} tick={AXIS_TICK} />
          <YAxis
            yAxisId="kr"
            tick={AXIS_TICK}
            width={56}
            domain={[0, "auto"]}
            label={{
              value: "kr",
              angle: -90,
              position: "insideLeft",
              fill: AXIS_TICK.fill,
              fontSize: 11,
            }}
          />
          <YAxis
            yAxisId="pct"
            orientation="right"
            tick={AXIS_TICK}
            width={48}
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
            label={{
              value: "Forbruksandel %",
              angle: 90,
              position: "insideRight",
              fill: AXIS_TICK.fill,
              fontSize: 11,
            }}
          />
          <Tooltip
            {...TOOLTIP_PROPS}
            formatter={(value, name) =>
              name === "Forbruksandel"
                ? [pct(Number(value)), name]
                : [kr(Number(value)), name]
            }
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar
            yAxisId="kr"
            dataKey="fixed"
            name="Faste kostnader"
            stackId="cost"
            fill={CHART_COLORS.cost}
            maxBarSize={40}
          />
          <Bar
            yAxisId="kr"
            dataKey="consumption"
            name="Forbrukskostnader"
            stackId="cost"
            fill={CHART_COLORS.assigned}
            maxBarSize={40}
          />
          <Line
            yAxisId="pct"
            dataKey="consumptionPct"
            name="Forbruksandel"
            type="monotone"
            stroke={CHART_COLORS.balance}
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
            empty={isLoading ? "Laster …" : "Ingen kostnadsdata"}
          />
        </div>
      </details>
    </ChartCard>
  );
}
