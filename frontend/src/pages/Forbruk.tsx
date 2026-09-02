import ConsumptionByMemberChart from "../components/ConsumptionByMemberChart";
import ConsumptionHistoryChart from "../components/ConsumptionHistoryChart";
import GridRateChart from "../components/GridRateChart";
import SessionHistory from "../components/SessionHistory";

/**
 * Admin "Forbruk" — consumption trends and charging-session history in one place.
 * All four sections are independent (each fetches its own data); the two
 * history charts share the `GET /api/charging/history` payload via SWR.
 */
export default function Forbruk() {
  return (
    <section className="space-y-8">
      <h1 className="text-lg font-semibold text-slate-100">Forbruk</h1>

      <div className="grid gap-8 lg:grid-cols-2">
        <ConsumptionHistoryChart />
        <GridRateChart />
      </div>

      <ConsumptionByMemberChart />

      <SessionHistory />
    </section>
  );
}
