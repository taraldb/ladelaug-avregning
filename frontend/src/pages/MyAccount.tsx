import useSWR from "swr";
import {
  ApiError,
  getMyBalance,
  getMyLedger,
  getMyStatus,
  type LedgerTxn,
} from "../api/client";
import StatTile from "../components/StatTile";
import Table, { type Column } from "../components/Table";
import { formatDate, formatNok, txnTypeLabel } from "../lib/format";

const columns: Column<LedgerTxn>[] = [
  { key: "date", header: "Valørdato", render: (t) => formatDate(t.value_date) },
  { key: "type", header: "Type", render: (t) => txnTypeLabel(t.txn_type) },
  {
    key: "amount",
    header: "Beløp",
    className: "text-right tabular-nums",
    render: (t) => (
      <span className={t.amount_ore < 0 ? "text-rose-400" : "text-emerald-400"}>
        {formatNok(t.amount_nok)}
      </span>
    ),
  },
  {
    key: "detail",
    header: "Detaljer",
    render: (t) => t.reason ?? t.reference ?? "–",
  },
];

const isForbidden = (err: unknown) => err instanceof ApiError && err.status === 403;

export default function MyAccount() {
  const balance = useSWR("/api/me/balance", () => getMyBalance());
  const ledger = useSWR("/api/me/ledger", () => getMyLedger());
  const status = useSWR("/api/me/status", () => getMyStatus());

  if ([balance.error, ledger.error, status.error].some(isForbidden)) {
    return (
      <section className="space-y-3">
        <h1 className="text-lg font-semibold text-slate-100">Min konto</h1>
        <p className="text-sm text-slate-400">
          Denne kontoen er ikke knyttet til et medlem.
        </p>
      </section>
    );
  }

  const txns = ledger.data?.transactions ?? [];

  return (
    <section className="space-y-6">
      <h1 className="text-lg font-semibold text-slate-100">Min konto</h1>

      <StatTile
        label="Saldo"
        value={balance.data ? formatNok(balance.data.balance_nok) : "…"}
        tone={balance.data && balance.data.balance_ore < 0 ? "negative" : "positive"}
      />

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">Min historikk</h2>
        <Table
          columns={columns}
          rows={txns}
          rowKey={(t) => t.id}
          empty="Ingen transaksjoner"
        />
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">Min status</h2>
        {status.data ? (
          <div className="space-y-1 text-sm text-slate-300">
            <p>
              Status:{" "}
              <span className="text-slate-100">
                {status.data.status === "active"
                  ? "Aktiv"
                  : status.data.status === "inactive"
                    ? "Inaktiv"
                    : "–"}
              </span>
            </p>
            <p>
              Deltar i avregning:{" "}
              <span className="text-slate-100">
                {status.data.participates == null
                  ? "–"
                  : status.data.participates
                    ? "Ja"
                    : "Nei"}
              </span>
            </p>
            <ol className="mt-2 space-y-1">
              {status.data.history.map((p) => (
                <li
                  key={p.id}
                  className="border-l-2 border-slate-700 pl-3 text-slate-400"
                >
                  {p.status === "active" ? "Aktiv" : "Inaktiv"} ·{" "}
                  {formatDate(p.effective_from)} –{" "}
                  {p.effective_to ? formatDate(p.effective_to) : "løpende"}
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="text-sm text-slate-400">Laster …</p>
        )}
      </div>
    </section>
  );
}
