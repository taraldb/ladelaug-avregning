import useSWR from "swr";
import { getChargingHistory } from "../api/client";
import { formatNok } from "../lib/format";
import {
  AXIS_TICK,
  CHART_COLORS,
  ChartCard,
  GRID_STROKE,
  TOOLTIP_PROPS,
  monthTick,
} from "./chartTheme";
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
 * Electricity cost per settled month: the fakturert totalbeløp as bars (kr, left
 * axis) and the effective price `invoice_total_nok / invoice_kwh` as a line
 * (kr/kWh, right axis). Months without a posted settlement have no value and
 * both series gap there. Reuses the `GET /api/charging/history` payload (SWR
 * dedupes with `ConsumptionHistoryChart`).
 */

const MONTHS = 12;

const perKwh = (v: number | null) =>
  v == null
    ? "–"
    : `kr ${v.toLocaleString("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;

export default function GridRateChart() {
  const { data, error, isLoading } = useSWR("/api/charging/history", () =>
    getChargingHistory(MONTHS),
  );

  if (error) {
    return (
      <ChartCard title="Strømkostnad og pris">
        <p className="text-sm text-rose-400">Kunne ikke laste prishistorikk.</p>
      </ChartCard>
    );
  }

  const rows = (data?.months ?? []).map((m) => ({
    month: m.month,
    total: m.invoice_total_nok == null ? null : Number(m.invoice_total_nok),
    rate: m.cost_per_kwh_nok == null ? null : Number(m.cost_per_kwh_nok),
  }));
  const settled = rows.filter((r) => r.rate != null);
  const latest = settled.at(-1);

  return (
    <ChartCard
      title="Strømkostnad og pris"
      hint={
        isLoading
          ? "Laster …"
          : settled.length === 0
            ? "Ingen avregnede måneder ennå."
            : `Fakturert beløp (stolper) og pris per kWh (linje), per avregnet måned. Siste: ${
                latest?.total != null ? formatNok(String(latest.total)) : "–"
              } · ${perKwh(latest?.rate ?? null)}/kWh.`
      }
    >
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="month" tickFormatter={monthTick} tick={AXIS_TICK} />
          <YAxis
            yAxisId="nok"
            tick={AXIS_TICK}
            width={56}
            label={{
              value: "kr",
              angle: -90,
              position: "insideLeft",
              fill: AXIS_TICK.fill,
              fontSize: 11,
            }}
          />
          <YAxis
            yAxisId="rate"
            orientation="right"
            tick={AXIS_TICK}
            width={56}
            domain={[0, "auto"]}
            label={{
              value: "kr/kWh",
              angle: 90,
              position: "insideRight",
              fill: AXIS_TICK.fill,
              fontSize: 11,
            }}
          />
          <Tooltip
            {...TOOLTIP_PROPS}
            formatter={(value, name) =>
              name === "Pris per kWh"
                ? [`${perKwh(Number(value))}/kWh`, name]
                : [formatNok(String(Number(value))), name]
            }
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar
            yAxisId="nok"
            dataKey="total"
            name="Fakturert beløp"
            fill={CHART_COLORS.assigned}
            maxBarSize={28}
          />
          <Line
            yAxisId="rate"
            dataKey="rate"
            name="Pris per kWh"
            type="monotone"
            stroke={CHART_COLORS.cost}
            strokeWidth={2}
            connectNulls={false}
            dot={{ r: 3 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
