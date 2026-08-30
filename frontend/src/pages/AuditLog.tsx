import { useState } from "react";
import useSWR from "swr";
import { listAuditEvents, type AuditEvent } from "../api/client";
import Table, { type Column } from "../components/Table";
import { formatDateTime } from "../lib/format";

const PAGE_SIZE = 50;

const ENTITY_TYPES = ["", "member", "ledger_transaction", "user", "session"];

const columns: Column<AuditEvent>[] = [
  { key: "when", header: "Tidspunkt", render: (e) => formatDateTime(e.occurred_at) },
  { key: "actor", header: "Aktør", render: (e) => e.actor_label },
  { key: "type", header: "Hendelse", render: (e) => e.event_type },
  {
    key: "entity",
    header: "Objekt",
    render: (e) => (e.entity_id ? `${e.entity_type} #${e.entity_id}` : e.entity_type),
  },
  { key: "summary", header: "Sammendrag", render: (e) => e.summary },
];

export default function AuditLog() {
  const [eventType, setEventType] = useState("");
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(0);

  const { data, isLoading, mutate } = useSWR(
    ["audit", eventType, entityType, page] as const,
    () =>
      listAuditEvents({
        eventType: eventType || null,
        entityType: entityType || null,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  );

  const events = data?.events ?? [];
  const total = data?.total ?? 0;
  const counts = data?.counts ?? {};
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Revisjonslogg</h1>
        <button
          type="button"
          onClick={() => void mutate()}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
        >
          Oppdater
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Hendelsestype</span>
          <input
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value);
              setPage(0);
            }}
            placeholder="f.eks. ledger.payment_recorded"
            className="w-72 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Objekttype</span>
          <select
            value={entityType}
            onChange={(e) => {
              setEntityType(e.target.value);
              setPage(0);
            }}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          >
            {ENTITY_TYPES.map((t) => (
              <option key={t || "all"} value={t}>
                {t || "Alle"}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Table
        columns={columns}
        rows={events}
        rowKey={(e) => e.id}
        empty={isLoading ? "Laster …" : "Ingen hendelser"}
      />

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-400">
        <span>
          {total} hendelser
          {Object.keys(counts).length > 0 && (
            <span className="ml-2 text-slate-500">
              (
              {Object.entries(counts)
                .map(([k, v]) => `${k}: ${v}`)
                .join(", ")}
              )
            </span>
          )}
        </span>
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
    </section>
  );
}
