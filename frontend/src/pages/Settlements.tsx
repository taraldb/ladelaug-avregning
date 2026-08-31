import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { ROUTES } from "../routes";
import {
  ApiError,
  createSettlementDraft,
  listSettlements,
  type Settlement,
} from "../api/client";
import Table, { type Column } from "../components/Table";
import { formatNok } from "../lib/format";

const columns: Column<Settlement>[] = [
  { key: "month", header: "Måned", render: (s) => s.period_month },
  {
    key: "status",
    header: "Status",
    render: (s) => (s.status === "posted" ? "Bokført" : "Utkast"),
  },
  {
    key: "invoice",
    header: "Fakturasum",
    render: (s) => (s.invoice_total_nok ? formatNok(s.invoice_total_nok) : "–"),
  },
  {
    key: "frozen",
    header: "Fryst",
    render: (s) => (s.usage_frozen_at ? "Ja" : "Nei"),
  },
];

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export default function Settlements() {
  const { data, error, isLoading, mutate } = useSWR("/api/settlement", () =>
    listSettlements(),
  );
  const navigate = useNavigate();
  const [month, setMonth] = useState(thisMonth());
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const { settlement } = await createSettlementDraft(month);
      await mutate();
      navigate(ROUTES.settlementDetail(settlement.id));
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Kunne ikke opprette avregning.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-semibold">Avregninger</h1>

      <form onSubmit={onCreate} className="flex items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-300">Ny avregning</span>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
          />
        </label>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
        >
          Opprett utkast
        </button>
      </form>
      {formError && (
        <p role="alert" className="text-sm text-rose-400">
          {formError}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-rose-400">
          Kunne ikke laste avregninger: {(error as ApiError).message}
        </p>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-400">Laster …</p>
      ) : (
        <Table
          columns={columns}
          rows={data?.settlements ?? []}
          rowKey={(s) => s.id}
          onRowClick={(s) => navigate(ROUTES.settlementDetail(s.id))}
          empty="Ingen avregninger ennå"
        />
      )}
    </section>
  );
}
