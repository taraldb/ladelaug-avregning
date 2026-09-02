import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { ROUTES } from "../routes";
import {
  ApiError,
  createSettlementDraft,
  listSettlements,
  type Settlement,
} from "../api/client";
import Money from "../components/Money";
import Table, { type Column } from "../components/Table";

function Chip({
  tone,
  children,
}: {
  tone: "emerald" | "amber" | "slate";
  children: ReactNode;
}) {
  const cls = {
    emerald: "bg-emerald-500/20 text-emerald-300",
    amber: "bg-amber-500/20 text-amber-300",
    slate: "bg-slate-700/40 text-slate-300",
  }[tone];
  return (
    <span
      className={`inline-block rounded-md px-2 py-0.5 text-xs font-semibold ${cls}`}
    >
      {children}
    </span>
  );
}

/** The status of a settlement, with a shared draft called out separately from
 *  an ordinary (unshared) one. */
function StatusChip({ s }: { s: Settlement }) {
  if (s.status === "posted") return <Chip tone="emerald">Bokført</Chip>;
  if (s.draft_shared) return <Chip tone="amber">Utkast · delt</Chip>;
  return <Chip tone="slate">Utkast</Chip>;
}

/** Zero or more chips for the "changes since this settlement was built" cases:
 *  a posted settlement whose usage drifted (correction available), a frozen
 *  draft whose usage drifted (re-freeze needed), and how many corrections have
 *  already been booked. */
function FlagChips({ s }: { s: Settlement }) {
  const chips: ReactNode[] = [];
  if (s.correction_pending)
    chips.push(
      <Chip key="pending" tone="amber">
        Endret forbruk – korrigering tilgjengelig
      </Chip>,
    );
  if (s.consumption_changed)
    chips.push(
      <Chip key="stale" tone="amber">
        Forbruk endret – frys på nytt
      </Chip>,
    );
  if (s.correction_count > 0)
    chips.push(
      <Chip key="corrected" tone="slate">
        Korrigert{s.correction_count > 1 ? ` ×${s.correction_count}` : ""}
      </Chip>,
    );
  if (chips.length === 0) return <span className="text-slate-600">–</span>;
  return <div className="flex flex-wrap gap-1">{chips}</div>;
}

const columns: Column<Settlement>[] = [
  { key: "month", header: "Måned", render: (s) => s.period_month },
  {
    key: "status",
    header: "Status",
    render: (s) => <StatusChip s={s} />,
  },
  {
    key: "flags",
    header: "Merknad",
    render: (s) => <FlagChips s={s} />,
  },
  {
    key: "invoice",
    header: "Fakturasum",
    className: "text-right tabular-nums",
    render: (s) =>
      s.invoice_total_nok ? <Money value={s.invoice_total_nok} /> : "–",
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
