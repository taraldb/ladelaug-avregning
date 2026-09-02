import { useState } from "react";
import useSWR from "swr";
import { getConsumption, listMembers } from "../api/client";
import {
  AXIS_TICK,
  CHART_COLORS,
  ChartCard,
  GRID_STROKE,
  TOOLTIP_PROPS,
} from "./chartTheme";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Per-member metered kWh for one month, tallest first, with unattributed
 * consumption as its own bar. Month is picked with a native `<input type=month>`
 * (same pattern as `Settlements` / `SystemHealth`). Fed by
 * `GET /api/charging/consumption` + member names from `GET /api/members`.
 */

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

const UNASSIGNED = "__unassigned__";

const kwh = (v: number) => `${v.toLocaleString("nb-NO", { maximumFractionDigits: 2 })} kWh`;

export default function ConsumptionByMemberChart() {
  const [month, setMonth] = useState(thisMonth());

  const { data, error, isLoading } = useSWR(
    ["/api/charging/consumption", month] as const,
    () => getConsumption(month),
  );
  const { data: membersData } = useSWR("/api/members", () => listMembers());

  const names = new Map(
    (membersData?.members ?? []).map((m) => [m.id, m.full_name]),
  );

  const bars = [
    ...(data?.by_member ?? []).map((r) => ({
      id: String(r.member_id),
      name: names.get(r.member_id) ?? `#${r.member_id}`,
      kwh: Number(r.energy_kwh) || 0,
    })),
    ...(data && Number(data.unassigned_kwh) > 0
      ? [
          {
            id: UNASSIGNED,
            name: "Ikke tilordnet",
            kwh: Number(data.unassigned_kwh),
          },
        ]
      : []),
  ].sort((a, b) => b.kwh - a.kwh);

  const total = Number(data?.total_kwh ?? 0);

  return (
    <ChartCard
      title="Forbruk per medlem"
      hint={
        <span className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5">
            <span>Måned</span>
            <input
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            />
          </label>
          {!isLoading && !error && (
            <span>· {kwh(total)} målt totalt i {month}</span>
          )}
        </span>
      }
    >
      {error ? (
        <p className="text-sm text-rose-400">Kunne ikke laste forbruk for {month}.</p>
      ) : bars.length === 0 ? (
        <p className="text-sm text-slate-400">
          {isLoading ? "Laster …" : `Ingen registrert forbruk i ${month}.`}
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(140, bars.length * 34 + 40)}>
          <BarChart
            data={bars}
            layout="vertical"
            margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
          >
            <CartesianGrid stroke={GRID_STROKE} horizontal={false} />
            <XAxis type="number" tick={AXIS_TICK} tickFormatter={(v) => `${v}`} />
            <YAxis
              type="category"
              dataKey="name"
              tick={AXIS_TICK}
              width={120}
            />
            <Tooltip
              {...TOOLTIP_PROPS}
              formatter={(value) => [kwh(Number(value)), "Forbruk"]}
              cursor={{ fill: "#1e293b55" }}
            />
            <Bar dataKey="kwh" name="Forbruk" radius={[0, 3, 3, 0]}>
              {bars.map((b) => (
                <Cell
                  key={b.id}
                  fill={
                    b.id === UNASSIGNED
                      ? CHART_COLORS.unassigned
                      : CHART_COLORS.assigned
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}
