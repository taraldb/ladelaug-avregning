import { useState } from "react";
import useSWR from "swr";
import { getTopHours } from "../api/client";
import { ChartCard } from "./chartTheme";
import Table, { type Column } from "./Table";

/**
 * The 10 busiest hours in a picked calendar month — a quick read on when peak
 * demand actually falls (e.g. "everyone plugs in around 18:00"). Fed by
 * `GET /api/charging/peak-hours`; hours with no charging at all never appear,
 * so a quiet month can show fewer than 10 rows. The month picker lives right
 * here next to the table.
 */

const LIMIT = 10;

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

interface Row {
  rank: number;
  hour: string;
  avg_power_kw: string;
  charging_sessions: number;
  idle_sessions: number;
}

/** ISO hour string -> "DD.MM kl. HH" in the hour's own local offset. */
function peakLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  return `${dd}.${mm} kl. ${hh}`;
}

const kw = (v: string) =>
  `${Number(v).toLocaleString("nb-NO", { maximumFractionDigits: 2 })} kW`;

const columns: Column<Row>[] = [
  { key: "rank", header: "#", className: "w-8 text-slate-500", render: (r) => r.rank },
  { key: "hour", header: "Time", render: (r) => peakLabel(r.hour) },
  {
    key: "power",
    header: "Snitteffekt",
    className: "text-right tabular-nums",
    render: (r) => kw(r.avg_power_kw),
  },
  {
    key: "sessions",
    header: "Samtidige økter",
    className: "text-right tabular-nums",
    render: (r) => r.charging_sessions + r.idle_sessions,
  },
];

export default function PeakHoursList() {
  const [month, setMonth] = useState(thisMonth());
  const { data, error, isLoading } = useSWR(
    ["/api/charging/peak-hours", month] as const,
    () => getTopHours(month, LIMIT),
  );

  if (error) {
    return (
      <ChartCard title="Travleste timer">
        <p className="text-sm text-rose-400">Kunne ikke laste toppdata.</p>
      </ChartCard>
    );
  }

  const rows: Row[] = (data?.hours ?? []).map((h, i) => ({ rank: i + 1, ...h }));

  return (
    <ChartCard
      title="Travleste timer"
      hint={
        <span className="flex flex-wrap items-center gap-3">
          <span>
            Topp {LIMIT} timer med høyest snitteffekt i valgt måned.
          </span>
          <label className="flex items-center gap-1.5 text-xs text-slate-300">
            <span className="sr-only">Måned</span>
            <input
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-xs text-slate-100"
            />
          </label>
        </span>
      }
    >
      <Table
        columns={columns}
        rows={rows}
        rowKey={(r) => r.hour}
        empty={isLoading ? "Laster …" : "Ingen lading denne måneden"}
      />
    </ChartCard>
  );
}
