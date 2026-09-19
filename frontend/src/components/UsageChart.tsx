import { useState } from "react";
import useSWR from "swr";
import { getChargingUsage, type UsageHour } from "../api/client";
import {
  AXIS_TICK,
  CHART_COLORS,
  ChartCard,
  GRID_STROKE,
  TOOLTIP_PROPS,
} from "./chartTheme";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Grid-wide usage over a rolling window: average power (kWh delivered per hour
 * == kW average, left axis) as an area, with stacked bars (right axis) for how
 * many sessions were actively charging vs. merely plugged in that hour. Fed by
 * `GET /api/charging/usage`. Session state is derived from `charging_intervals`
 * — a session counts as charging in an hour it has an energy>0 interval point,
 * idle where it's occupied with none (Zaptec omits rows during idle stretches
 * rather than reporting zero-energy ones, so this is a real signal, not noise).
 *
 * Every window — 2d/7d/Måned — is whole calendar days (today included, even
 * mid-day), and pages back/forward through history one window width at a
 * time with the same ‹ range › control: today (or the current month) is the
 * default and the forward arrow disables once back there.
 */

const WINDOWS: { label: string; hours: number }[] = [
  { label: "2d", hours: 48 },
  { label: "7d", hours: 168 },
];

const MONTH_NAMES = [
  "januar", "februar", "mars", "april", "mai", "juni",
  "juli", "august", "september", "oktober", "november", "desember",
];

type Window = { kind: "hours"; hours: number } | { kind: "month" };

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const idx = y * 12 + (m - 1) + delta;
  return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, "0")}`;
}

function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const name = MONTH_NAMES[m - 1] ?? month;
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${y}`;
}

interface Row {
  hour: string;
  avgPowerKw: number;
  charging: number;
  idle: number;
}

function toRow(h: UsageHour): Row {
  return {
    hour: h.hour,
    avgPowerKw: Number(h.avg_power_kw) || 0,
    charging: h.charging_sessions,
    idle: h.idle_sessions,
  };
}

/** "DD.MM" — no year, matching the app's other compact axis ticks. */
function dayTick(d: Date): string {
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function hourTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.getHours() === 0 ? dayTick(d) : `${String(d.getHours()).padStart(2, "0")}:00`;
}

function hourLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("nb-NO", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The live window's exclusive end: midnight at the start of tomorrow — every
 * window is whole calendar days, today included in full even mid-day (same
 * idea as the current, still-incomplete month always showing all its days).
 * Used both to seed paging and to know when paging forward again reaches
 * today. */
function liveEnd(): Date {
  const d = new Date();
  d.setHours(24, 0, 0, 0);
  return d;
}

const kw = (v: number) => `${v.toLocaleString("nb-NO", { maximumFractionDigits: 2 })} kW`;

export default function UsageChart() {
  const [window, setWindow] = useState<Window>({ kind: "hours", hours: 168 });
  const [anchorEnd, setAnchorEnd] = useState<string | null>(null); // null = live (trailing from now)
  const [month, setMonth] = useState(thisMonth());

  const pickWindow = (w: Window) => {
    setWindow(w);
    setAnchorEnd(null);
    setMonth(thisMonth());
  };

  const key =
    window.kind === "month"
      ? (["/api/charging/usage", "month", month] as const)
      : (["/api/charging/usage", "hours", window.hours, anchorEnd ?? "live"] as const);
  const { data, error, isLoading } = useSWR(key, () =>
    getChargingUsage(
      window.kind === "month"
        ? { month }
        : { hours: window.hours, end: anchorEnd ?? undefined },
    ),
  );

  const goBack = () => {
    if (window.kind === "month") {
      setMonth((m) => shiftMonth(m, -1));
      return;
    }
    const end = anchorEnd ? new Date(anchorEnd) : liveEnd();
    setAnchorEnd(new Date(end.getTime() - window.hours * 3_600_000).toISOString());
  };

  const goForward = () => {
    if (window.kind === "month") {
      setMonth((m) => (m < thisMonth() ? shiftMonth(m, 1) : m));
      return;
    }
    if (anchorEnd == null) return;
    const next = new Date(new Date(anchorEnd).getTime() + window.hours * 3_600_000);
    setAnchorEnd(next.getTime() >= liveEnd().getTime() ? null : next.toISOString());
  };

  const forwardDisabled = window.kind === "month" ? month >= thisMonth() : anchorEnd == null;

  if (error) {
    return (
      <ChartCard title="Bruk over tid">
        <p className="text-sm text-rose-400">Kunne ikke laste bruksdata.</p>
      </ChartCard>
    );
  }

  const rows = (data?.hours ?? []).map(toRow);
  const peakPower = rows.reduce((m, r) => Math.max(m, r.avgPowerKw), 0);
  const peakSessions = rows.reduce((m, r) => Math.max(m, r.charging + r.idle), 0);

  const rangeLabel =
    window.kind === "month"
      ? monthLabel(month)
      : rows.length > 0
        ? `${dayTick(new Date(rows[0].hour))} – ${dayTick(new Date(rows[rows.length - 1].hour))}`
        : "–";

  // Beyond ~2 days, hourly ticks overlap into an unreadable smear — collapse
  // the axis to one tick per day instead (recharts' own tick-thinning picks
  // arbitrary hours rather than day boundaries, so this needs an explicit list).
  const dayTicksOnly = window.kind === "month" || window.hours > 48;
  const dayTicks = dayTicksOnly
    ? rows.filter((r) => new Date(r.hour).getHours() === 0).map((r) => r.hour)
    : undefined;

  return (
    <ChartCard
      title="Bruk over tid"
      hint={
        <span className="flex flex-wrap items-center gap-3">
          <span>
            {isLoading
              ? "Laster …"
              : `Snitteffekt per time (venstre akse) og antall økter (høyre akse) · maks ${kw(peakPower)} · maks ${peakSessions} samtidige økter.`}
          </span>
          <span
            role="group"
            aria-label="Tidsvindu"
            className="inline-flex rounded-md border border-slate-700 p-0.5"
          >
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                type="button"
                aria-pressed={window.kind === "hours" && window.hours === w.hours}
                onClick={() => pickWindow({ kind: "hours", hours: w.hours })}
                className={`rounded px-2 py-0.5 text-xs transition-colors ${
                  window.kind === "hours" && window.hours === w.hours
                    ? "bg-emerald-500 font-semibold text-slate-950"
                    : "text-slate-300 hover:bg-slate-800"
                }`}
              >
                {w.label}
              </button>
            ))}
            <button
              type="button"
              aria-pressed={window.kind === "month"}
              onClick={() => pickWindow({ kind: "month" })}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                window.kind === "month"
                  ? "bg-emerald-500 font-semibold text-slate-950"
                  : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              Måned
            </button>
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-slate-300">
            <button
              type="button"
              aria-label="Forrige periode"
              onClick={goBack}
              className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:bg-slate-800"
            >
              ‹
            </button>
            <span className="tabular-nums" data-testid="usage-range">
              {rangeLabel}
            </span>
            <button
              type="button"
              aria-label="Neste periode"
              onClick={goForward}
              disabled={forwardDisabled}
              className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
            >
              ›
            </button>
          </span>
        </span>
      }
    >
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis
            dataKey="hour"
            tickFormatter={hourTick}
            tick={AXIS_TICK}
            minTickGap={24}
            ticks={dayTicks}
          />
          <YAxis
            yAxisId="kw"
            tick={AXIS_TICK}
            width={44}
            label={{
              value: "kW",
              angle: -90,
              position: "insideLeft",
              fill: AXIS_TICK.fill,
              fontSize: 11,
            }}
          />
          <YAxis
            yAxisId="sessions"
            orientation="right"
            tick={AXIS_TICK}
            width={36}
            allowDecimals={false}
            label={{
              value: "Økter",
              angle: 90,
              position: "insideRight",
              fill: AXIS_TICK.fill,
              fontSize: 11,
            }}
          />
          <Tooltip
            {...TOOLTIP_PROPS}
            labelFormatter={(label) => hourLabel(String(label))}
            formatter={(value, name) => [
              name === "Snitteffekt" ? kw(Number(value)) : `${Number(value)} økter`,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area
            yAxisId="kw"
            dataKey="avgPowerKw"
            name="Snitteffekt"
            type="monotone"
            stroke={CHART_COLORS.power}
            fill={CHART_COLORS.power}
            fillOpacity={0.18}
            strokeWidth={2}
          />
          <Bar
            yAxisId="sessions"
            dataKey="charging"
            name="Lader aktivt"
            stackId="sessions"
            fill={CHART_COLORS.assigned}
          />
          <Bar
            yAxisId="sessions"
            dataKey="idle"
            name="Tilkoblet, ikke lading"
            stackId="sessions"
            fill={CHART_COLORS.unassigned}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
