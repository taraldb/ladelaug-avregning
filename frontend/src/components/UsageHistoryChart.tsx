import { useState } from "react";
import type { MemberHistoryMonth } from "../api/client";
import { formatNok } from "../lib/format";
import Money from "./Money";
import Table, { type Column } from "./Table";

/**
 * The member dashboard's rolling history in one combined chart: grouped bars for
 * metered kWh and (once the month is settled) the kr charge, with the month-end
 * balance drawn as a line on top — all sharing one month axis. Hovering a month
 * shows a tooltip with the exact numbers. Hand-rolled SVG, no chart library.
 * The table underneath (newest first) is the accessible source of truth; the SVG
 * is decorative (`aria-hidden`).
 */

const PAD_X = 30;
const STEP = 56; // horizontal spacing per month
const BASELINE = 94; // bar baseline / bottom of the balance range
const BAR_H = 76; // max bar height, user units
const LINE_TOP = 12; // top of the balance range
const LABEL_Y = 110;
const VB_H = 118;

function monthShort(month: string): string {
  return month.slice(5); // "2026-07" -> "07"
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / mag) * mag;
}

const columns: Column<MemberHistoryMonth>[] = [
  { key: "month", header: "Måned", render: (m) => m.month },
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

export default function UsageHistoryChart({
  months,
}: {
  months: MemberHistoryMonth[];
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (months.length === 0) {
    return <p className="text-sm text-slate-400">Ingen forbruksdata ennå.</p>;
  }

  const width = PAD_X * 2 + months.length * STEP;
  const kwhMax = niceMax(Math.max(...months.map((m) => Number(m.consumption_kwh) || 0)));
  const krMax = niceMax(
    Math.max(...months.map((m) => (m.settled ? (m.charge_ore ?? 0) / 100 : 0))),
  );

  const balances = months.map((m) => m.balance_end_ore / 100);
  const bLo = Math.min(...balances, 0);
  const bHi = Math.max(...balances, 0);
  const bSpan = bHi - bLo || 1;
  const balY = (v: number) => BASELINE - ((v - bLo) / bSpan) * (BASELINE - LINE_TOP);
  const colX = (i: number) => PAD_X + i * STEP + STEP / 2;
  const linePoints = months.map((_, i) => `${colX(i)},${balY(balances[i])}`).join(" ");

  const totalKwh = months
    .reduce((sum, m) => sum + (Number(m.consumption_kwh) || 0), 0)
    .toFixed(2);

  const tip = hover != null ? months[hover] : null;
  const tipLeft = hover != null ? Math.min(88, Math.max(12, (colX(hover) / width) * 100)) : 0;
  const tableRows = [...months].reverse(); // newest month on top

  return (
    <figure className="space-y-3">
      <figcaption className="text-xs text-slate-400">
        Siste {months.length} måneder · {totalKwh} kWh totalt. Hold pekeren over en
        måned for detaljer.
      </figcaption>

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500" />
            Forbruk (kWh)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-sky-400" />
            Kostnad (kr)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-[2px] w-3 bg-amber-300" />
            Saldo
          </span>
        </div>

        <div className="relative">
          <svg
            viewBox={`0 0 ${width} ${VB_H}`}
            className="block w-full"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
          >
            <line
              x1={PAD_X - 8}
              y1={BASELINE}
              x2={width - PAD_X + 8}
              y2={BASELINE}
              className="stroke-slate-700"
              strokeWidth={1}
            />
            {bLo < 0 && bHi > 0 && (
              <line
                x1={PAD_X - 8}
                y1={balY(0)}
                x2={width - PAD_X + 8}
                y2={balY(0)}
                className="stroke-slate-700"
                strokeDasharray="3 3"
                strokeWidth={1}
              />
            )}

            {months.map((m, i) => {
              const cx = colX(i);
              const kwh = Number(m.consumption_kwh) || 0;
              const kr = m.settled ? (m.charge_ore ?? 0) / 100 : 0;
              const kwhH = kwhMax > 0 ? (kwh / kwhMax) * BAR_H : 0;
              const krH = krMax > 0 ? (kr / krMax) * BAR_H : 0;
              return (
                <g key={m.month}>
                  {hover === i && (
                    <rect
                      x={cx - STEP / 2}
                      y={0}
                      width={STEP}
                      height={BASELINE}
                      className="fill-slate-100/5"
                    />
                  )}
                  <rect
                    x={cx - 14}
                    y={BASELINE - kwhH}
                    width={12}
                    height={kwhH}
                    className="fill-emerald-500"
                  />
                  {m.settled && (
                    <rect
                      x={cx + 2}
                      y={BASELINE - krH}
                      width={12}
                      height={krH}
                      className="fill-sky-400"
                    />
                  )}
                  <text
                    x={cx}
                    y={LABEL_Y}
                    textAnchor="middle"
                    className="fill-slate-400"
                    style={{ fontSize: 10 }}
                  >
                    {monthShort(m.month)}
                  </text>
                </g>
              );
            })}

            {months.length > 1 && (
              <polyline
                points={linePoints}
                fill="none"
                className="stroke-amber-300"
                strokeWidth={2}
                strokeLinejoin="round"
              />
            )}
            {months.map((m, i) => (
              <circle
                key={m.month}
                cx={colX(i)}
                cy={balY(balances[i])}
                r={hover === i ? 4 : 3}
                className={m.balance_end_ore < 0 ? "fill-rose-400" : "fill-amber-300"}
              />
            ))}

            {/* transparent hit targets, last so they win pointer events */}
            {months.map((m, i) => (
              <rect
                key={m.month}
                data-month={m.month}
                x={colX(i) - STEP / 2}
                y={0}
                width={STEP}
                height={LABEL_Y}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover((h) => (h === i ? null : h))}
              />
            ))}
          </svg>

          {tip && (
            <div
              className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-md border border-slate-700 bg-slate-950/95 px-3 py-2 text-xs shadow-lg"
              style={{ left: `${tipLeft}%` }}
            >
              <div className="font-semibold text-slate-100">{tip.month}</div>
              <div className="mt-1 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-slate-300">
                <span className="text-slate-400">Forbruk</span>
                <span className="tabular-nums">
                  {tip.consumption_kwh} kWh · {tip.session_count} økter
                </span>
                <span className="text-slate-400">Kostnad</span>
                <span className="tabular-nums">
                  {tip.settled && tip.charge_nok != null
                    ? formatNok(tip.charge_nok)
                    : "ikke avregnet"}
                </span>
                <span className="text-slate-400">Saldo</span>
                <span className="tabular-nums">{formatNok(tip.balance_end_nok)}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <Table columns={columns} rows={tableRows} rowKey={(m) => m.month} />
    </figure>
  );
}
