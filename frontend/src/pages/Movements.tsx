import { useState } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import { ROUTES } from "../routes";
import {
  listLedgerTransactions,
  listMembers,
  type LedgerTxnRow,
} from "../api/client";
import PlusIcon from "../components/PlusIcon";
import RecordPaymentModal from "../components/RecordPaymentModal";
import Table, { type Column } from "../components/Table";
import { formatDate, formatNok, txnTypeLabel } from "../lib/format";

const PAGE_SIZE = 50;

const TXN_TYPES = [
  "payment",
  "payment_reversal",
  "adjustment_credit",
  "adjustment_debit",
  "settlement_charge",
  "settlement_reversal",
];

const columns: Column<LedgerTxnRow>[] = [
  { key: "date", header: "Valørdato", render: (t) => formatDate(t.value_date) },
  {
    key: "member",
    header: "Medlem",
    render: (t) => (
      <Link
        to={ROUTES.memberDetail(t.member_id)}
        className="text-emerald-400 hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        {t.member_reference} – {t.member_name}
      </Link>
    ),
  },
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

export default function Movements() {
  const [memberId, setMemberId] = useState("");
  const [txnType, setTxnType] = useState("");
  const [page, setPage] = useState(0);
  const [payOpen, setPayOpen] = useState(false);

  const { data: membersData } = useSWR("/api/members", () => listMembers());
  const members = membersData?.members ?? [];

  const { data, isLoading, mutate } = useSWR(
    ["/api/ledger-transactions", memberId, txnType, page] as const,
    () =>
      listLedgerTransactions({
        memberId: memberId ? Number(memberId) : null,
        txnType: txnType || null,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  );

  const rows = data?.transactions ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Bevegelser</h1>
        <button
          type="button"
          onClick={() => setPayOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
        >
          <PlusIcon /> Registrer innbetaling
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Medlem</span>
          <select
            value={memberId}
            onChange={(e) => {
              setMemberId(e.target.value);
              setPage(0);
            }}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          >
            <option value="">Alle</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.member_reference} – {m.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Type</span>
          <select
            value={txnType}
            onChange={(e) => {
              setTxnType(e.target.value);
              setPage(0);
            }}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          >
            <option value="">Alle</option>
            {TXN_TYPES.map((t) => (
              <option key={t} value={t}>
                {txnTypeLabel(t)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Table
        columns={columns}
        rows={rows}
        rowKey={(t) => t.id}
        empty={isLoading ? "Laster …" : "Ingen bevegelser"}
      />

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-400">
        <span>{total} bevegelser</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-md border border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Forrige
          </button>
          <span>
            Side {page + 1} av {pageCount}
          </span>
          <button
            type="button"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Neste
          </button>
        </div>
      </div>

      <RecordPaymentModal
        open={payOpen}
        onClose={() => setPayOpen(false)}
        onDone={async () => {
          await mutate();
          setPayOpen(false);
        }}
      />
    </section>
  );
}
