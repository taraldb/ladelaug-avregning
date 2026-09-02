import { useState } from "react";
import ConsumptionByMemberChart from "../components/ConsumptionByMemberChart";
import ConsumptionHistoryChart from "../components/ConsumptionHistoryChart";
import CostSplitChart from "../components/CostSplitChart";
import GridRateChart from "../components/GridRateChart";
import SessionHistory from "../components/SessionHistory";

type View = "overview" | "per-member";

const VIEW_LABEL: Record<View, string> = {
  overview: "Oversikt",
  "per-member": "Per medlem",
};

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/**
 * Admin "Forbruk" — a segmented control swaps between the aggregated view
 * (consumption / cost trends for the whole grid) and the per-member view
 * (this month's split by member + the raw charging-session log).
 */
export default function Forbruk() {
  const [view, setView] = useState<View>("overview");
  const [month, setMonth] = useState(thisMonth());

  return (
    <section className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Forbruk</h1>
        <div
          role="group"
          aria-label="Forbruk"
          className="inline-flex rounded-md border border-slate-700 p-0.5"
        >
          {(["overview", "per-member"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                view === v
                  ? "bg-emerald-500 font-semibold text-slate-950"
                  : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {VIEW_LABEL[v]}
            </button>
          ))}
        </div>
      </div>

      {view === "overview" ? (
        <>
          <ConsumptionHistoryChart />

          <div className="grid gap-8 lg:grid-cols-2">
            <CostSplitChart />
            <GridRateChart />
          </div>
        </>
      ) : (
        <>
          <label className="flex w-fit items-center gap-1.5 text-sm text-slate-300">
            <span>Måned</span>
            <input
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            />
          </label>

          <ConsumptionByMemberChart month={month} onMonthChange={setMonth} />

          <SessionHistory month={month} onMonthChange={setMonth} />
        </>
      )}
    </section>
  );
}
