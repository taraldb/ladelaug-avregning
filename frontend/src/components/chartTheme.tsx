import type { ReactNode } from "react";

/**
 * Shared look for every chart (admin "Forbruk" + the member dashboard). Recharts
 * has no theme system and the app is dark, so every colour is passed explicitly.
 * emerald = kWh, sky = kr, amber = running balance.
 */
export const CHART_COLORS = {
  assigned: "#10b981", // emerald-500 — consumption (attributed / metered kWh)
  unassigned: "#fbbf24", // amber-400 — metered but not yet attributed
  cost: "#38bdf8", // sky-400 — kr / kr-per-kWh
  balance: "#fcd34d", // amber-300 — running ledger balance line
  negative: "#fb7185", // rose-400 — balance below zero
  reference: "#94a3b8", // slate-400 — invoice / axis / grid
  power: "#a78bfa", // violet-400 — average power (kW)
} as const;

export const AXIS_TICK = { fill: "#94a3b8", fontSize: 11 } as const;
export const GRID_STROKE = "#1e293b"; // slate-800

/** Dark-themed Recharts `<Tooltip>` props. */
export const TOOLTIP_PROPS = {
  contentStyle: {
    background: "#020617", // slate-950
    border: "1px solid #334155", // slate-700
    borderRadius: 6,
    fontSize: 12,
  },
  labelStyle: { color: "#f1f5f9" }, // slate-100
  itemStyle: { color: "#cbd5e1" }, // slate-300
} as const;

/** "2026-07" -> "07". Compact month tick for a rolling ~12-month axis. */
export function monthTick(month: string): string {
  return month.slice(5);
}

/**
 * A titled card wrapping one chart, matching `UsageHistoryChart`'s frame. `hint`
 * renders as the small caption under the title.
 */
export function ChartCard({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <figure className="space-y-2">
      <figcaption>
        <span className="text-sm font-semibold text-slate-100">{title}</span>
        {hint && <span className="mt-0.5 block text-xs text-slate-400">{hint}</span>}
      </figcaption>
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
        {children}
      </div>
    </figure>
  );
}
