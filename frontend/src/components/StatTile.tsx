import type { ReactNode } from "react";

interface StatTileProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "positive" | "negative";
  className?: string;
}

const TONE: Record<NonNullable<StatTileProps["tone"]>, string> = {
  neutral: "text-slate-100",
  positive: "text-emerald-400",
  negative: "text-rose-400",
};

export default function StatTile({
  label,
  value,
  sub,
  tone = "neutral",
  className = "",
}: StatTileProps) {
  return (
    <div
      className={`rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 ${className}`}
    >
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${TONE[tone]}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}
