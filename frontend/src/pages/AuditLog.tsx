import { useState } from "react";
import useSWR from "swr";
import {
  auditEventsCsvUrl,
  getAuditEvent,
  listAuditEvents,
  type AuditEvent,
} from "../api/client";
import Table, { type Column } from "../components/Table";
import { formatDateTime } from "../lib/format";
import { btnRow, btnSecondary, inputClass } from "../lib/ui";

const PAGE_SIZE = 50;

const ENTITY_TYPES = ["", "member", "ledger_transaction", "user", "session", "settlement"];

const columns: Column<AuditEvent>[] = [
  { key: "when", header: "Tidspunkt", render: (e) => formatDateTime(e.occurred_at) },
  { key: "actor", header: "Aktør", render: (e) => e.actor_label },
  { key: "type", header: "Hendelse", render: (e) => e.event_type },
  {
    key: "entity",
    header: "Objekt",
    render: (e) => (e.entity_id ? `${e.entity_type} #${e.entity_id}` : e.entity_type),
  },
  { key: "summary", card: "title", header: "Sammendrag", render: (e) => e.summary },
];

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null || value === "") return null;
  return (
    <div className="flex gap-2">
      <span className="w-32 shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 break-words text-slate-200">{value}</span>
    </div>
  );
}

function EventDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, isLoading } = useSWR(["audit-event", id] as const, () => getAuditEvent(id));
  const e = data?.event;

  return (
    <section className="space-y-3 border-l-2 border-emerald-500/40 bg-slate-900/40 p-4 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-100">Hendelse #{id}</h2>
        <button
          type="button"
          onClick={onClose}
          className={btnRow}
        >
          Lukk
        </button>
      </div>
      {isLoading || !e ? (
        <p className="text-slate-500">Laster …</p>
      ) : (
        <div className="space-y-1.5">
          <DetailRow label="Tidspunkt" value={formatDateTime(e.occurred_at)} />
          <DetailRow label="Aktør" value={e.actor_label} />
          <DetailRow label="Rolle" value={e.actor_role} />
          <DetailRow label="Hendelse" value={e.event_type} />
          <DetailRow
            label="Objekt"
            value={e.entity_id ? `${e.entity_type} #${e.entity_id}` : e.entity_type}
          />
          <DetailRow label="Sammendrag" value={e.summary} />
          <DetailRow label="IP" value={e.ip} />
          <DetailRow label="User-agent" value={e.user_agent} />
          {e.detail != null && (
            <div className="pt-1">
              <span className="text-slate-500">Detaljer</span>
              <pre className="mt-1 overflow-x-auto rounded-md bg-slate-950 p-3 text-xs text-slate-200">
                {JSON.stringify(e.detail, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default function AuditLog() {
  const [eventType, setEventType] = useState("");
  const [entityType, setEntityType] = useState("");
  const [actor, setActor] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const filter = {
    eventType: eventType || null,
    entityType: entityType || null,
    actor: actor || null,
    occurredFrom: from || null,
    // make the end date inclusive of the whole day
    occurredTo: to ? `${to}T23:59:59` : null,
  };

  const { data, isLoading, mutate } = useSWR(
    ["audit", eventType, entityType, actor, from, to, page] as const,
    () => listAuditEvents({ ...filter, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
  );

  const events = data?.events ?? [];
  const total = data?.total ?? 0;
  const counts = data?.counts ?? {};
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function resetPage<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(0);
    };
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Revisjonslogg</h1>
        <div className="flex w-full gap-2 sm:w-auto [&>*]:flex-1 sm:[&>*]:flex-none">
          <a
            href={auditEventsCsvUrl(filter)}
            className={btnSecondary}
          >
            Eksporter CSV
          </a>
          <button
            type="button"
            onClick={() => void mutate()}
            className={btnSecondary}
          >
            Oppdater
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:flex lg:flex-wrap">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Hendelsestype</span>
          <input
            value={eventType}
            onChange={(e) => resetPage(setEventType)(e.target.value)}
            placeholder="f.eks. ledger.payment_recorded"
            className={`${inputClass} sm:w-64`}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Objekttype</span>
          <select
            value={entityType}
            onChange={(e) => resetPage(setEntityType)(e.target.value)}
            className={inputClass}
          >
            {ENTITY_TYPES.map((t) => (
              <option key={t || "all"} value={t}>
                {t || "Alle"}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Aktør</span>
          <input
            value={actor}
            onChange={(e) => resetPage(setActor)(e.target.value)}
            placeholder="e-post"
            className={`${inputClass} sm:w-52`}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Fra dato</span>
          <input
            type="date"
            value={from}
            onChange={(e) => resetPage(setFrom)(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Til dato</span>
          <input
            type="date"
            value={to}
            onChange={(e) => resetPage(setTo)(e.target.value)}
            className={inputClass}
          />
        </label>
      </div>

      <Table
        columns={columns}
        rows={events}
        rowKey={(e) => e.id}
        onRowClick={(e) =>
          setSelectedId((cur) => (cur === e.id ? null : e.id))
        }
        isExpanded={(e) => e.id === selectedId}
        renderExpanded={(e) => (
          <EventDetail id={e.id} onClose={() => setSelectedId(null)} />
        )}
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
