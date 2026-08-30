import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  addInvoiceLine,
  deleteInvoiceLine,
  freezeSettlement,
  getSettlement,
  getUnassigned,
  postSettlement,
  previewSettlement,
  reresolveCharging,
  setSettlementInvoice,
  settlementReports,
  uploadSettlementAttachment,
  type AllocationMethod,
  type SettlementPreview,
} from "../api/client";
import Table, { type Column } from "../components/Table";
import { formatNok } from "../lib/format";

const WARNING_LABELS: Record<string, string> = {
  negative_balances: "Noen medlemmer får negativ saldo",
  invoice_kwh_missing: "Fakturert kWh mangler",
  attachment_missing: "Faktura mangler",
  zero_consumption: "Ingen registrert forbruk – forbrukslinjer kan ikke fordeles",
  late_sessions: "Sene ladeøkter ikke behandlet",
  kwh_mismatch: "Fakturert kWh avviker mye fra målt",
  usage_stale: "Forbruket er endret etter frysing – frys på nytt",
};
const BLOCKING = new Set(["zero_consumption", "usage_stale"]);

export default function SettlementDetail() {
  const { id } = useParams();
  const sid = Number(id);
  const key = `/api/settlement/${sid}`;
  const { data, error, isLoading, mutate } = useSWR(key, () => getSettlement(sid));
  const [preview, setPreview] = useState<SettlementPreview | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const reports = useSWR(
    data?.settlement.status === "posted" ? `${key}/reports` : null,
    () => settlementReports(sid),
  );

  if (isLoading) return <p className="text-sm text-slate-400">Laster …</p>;
  if (error || !data)
    return (
      <p role="alert" className="text-sm text-rose-400">
        Kunne ikke laste avregning: {(error as ApiError)?.message}
      </p>
    );

  const s = data.settlement;
  const isDraft = s.status === "draft";

  async function act<T>(fn: () => Promise<T>, ok?: string) {
    setBanner(null);
    try {
      await fn();
      await mutate();
      if (ok) setBanner(ok);
    } catch (err) {
      setBanner(err instanceof ApiError ? err.message : "Handlingen feilet.");
    }
  }

  async function runPreview() {
    setBanner(null);
    try {
      setPreview(await previewSettlement(sid));
    } catch (err) {
      setBanner(err instanceof ApiError ? err.message : "Forhåndsvisning feilet.");
    }
  }

  async function doPost() {
    setBanner(null);
    try {
      const res = await postSettlement(sid);
      setPreview(res);
      await mutate();
      await reports.mutate();
      setBanner(`Bokført. ${res.members_charged} medlemmer belastet, ${res.emails_queued} e-poster i kø.`);
    } catch (err) {
      setBanner(err instanceof ApiError ? err.message : "Bokføring feilet.");
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Avregning {s.period_month}</h1>
        <span
          className={`rounded-md px-2 py-1 text-xs font-semibold ${
            isDraft ? "bg-amber-500/20 text-amber-300" : "bg-emerald-500/20 text-emerald-300"
          }`}
        >
          {isDraft ? "Utkast" : "Bokført"}
        </span>
      </div>

      {banner && <p className="rounded-md bg-slate-800 px-3 py-2 text-sm text-slate-200">{banner}</p>}

      <InvoicePanel
        settlementId={sid}
        invoiceKwh={s.invoice_kwh}
        gridKwh={s.grid_kwh}
        invoiceTotal={s.invoice_total_nok}
        editable={isDraft}
        onSaved={mutate}
      />

      <LinesPanel detail={data} editable={isDraft} onChange={mutate} />

      <AttachmentPanel
        settlementId={sid}
        filename={s.attachment_filename}
        editable={isDraft}
        onUploaded={mutate}
      />

      {isDraft && <UnassignedPanel month={s.period_month} onResolved={mutate} />}

      <div className="flex flex-wrap gap-2">
        {isDraft && (
          <button
            type="button"
            onClick={() => void act(() => freezeSettlement(sid), "Forbruk fryst.")}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
          >
            {s.usage_frozen_at ? "Frys på nytt" : "Frys forbruk"}
          </button>
        )}
        <button
          type="button"
          onClick={() => void runPreview()}
          disabled={!s.usage_frozen_at}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
        >
          Forhåndsvis
        </button>
        {isDraft && (
          <button
            type="button"
            onClick={() => void doPost()}
            disabled={
              !s.usage_frozen_at ||
              !s.invoice_kwh ||
              !s.attachment_filename ||
              data.lines.length === 0 ||
              (preview?.warnings.some((w) => BLOCKING.has(w.code)) ?? false)
            }
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            Bokfør
          </button>
        )}
      </div>

      {s.usage_frozen_at && (
        <p className="text-xs text-slate-500">
          Forbruk fryst {s.usage_frozen_at}. Øyeblikksbilde: {data.snapshot.length} medlemmer.
        </p>
      )}

      {preview && <PreviewPanel preview={preview} />}

      {s.status === "posted" && reports.data && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-200">Rapporter</h2>
          <ul className="space-y-1 text-sm">
            <li>
              <a className="text-emerald-400 hover:underline" href={reports.data.summary_url} target="_blank" rel="noreferrer">
                Sammendrag
              </a>
            </li>
            {reports.data.members.map((m) => (
              <li key={m.member_id}>
                <a className="text-emerald-400 hover:underline" href={m.url} target="_blank" rel="noreferrer">
                  {m.full_name} — {formatNok(m.charge_nok)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function InvoicePanel({
  settlementId,
  invoiceKwh,
  gridKwh,
  invoiceTotal,
  editable,
  onSaved,
}: {
  settlementId: number;
  invoiceKwh: string | null;
  gridKwh: string | null;
  invoiceTotal: string | null;
  editable: boolean;
  onSaved: () => void | Promise<unknown>;
}) {
  const [value, setValue] = useState(invoiceKwh ?? "");
  const [err, setErr] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await setSettlementInvoice(settlementId, { invoice_kwh: value });
      await onSaved();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Kunne ikke lagre.");
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-200">Faktura</h2>
      <form onSubmit={save} className="flex flex-wrap items-end gap-3 text-sm">
        <label>
          <span className="mb-1 block text-slate-400">Fakturert kWh</span>
          <input
            value={value}
            disabled={!editable}
            onChange={(e) => setValue(e.target.value)}
            className="w-32 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100 disabled:opacity-60"
          />
        </label>
        {editable && (
          <button
            type="submit"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
          >
            Lagre
          </button>
        )}
        <span className="text-slate-400">Målt (Zaptec): {gridKwh ?? "–"} kWh</span>
        <span className="text-slate-400">
          Sum fakturalinjer: {invoiceTotal ? formatNok(invoiceTotal) : "–"}
        </span>
      </form>
      {err && <p className="mt-1 text-xs text-rose-400">{err}</p>}
    </div>
  );
}

function LinesPanel({
  detail,
  editable,
  onChange,
}: {
  detail: Awaited<ReturnType<typeof getSettlement>>;
  editable: boolean;
  onChange: () => void | Promise<unknown>;
}) {
  const sid = detail.settlement.id;
  const [description, setDescription] = useState("");
  const [method, setMethod] = useState<AllocationMethod>("equal");
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await addInvoiceLine(sid, {
        description: description.trim(),
        allocation_method: method,
        amount,
      });
      setDescription("");
      setAmount("");
      await onChange();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Kunne ikke legge til linje.");
    }
  }

  const columns: Column<(typeof detail.lines)[number]>[] = [
    { key: "d", header: "Beskrivelse", render: (l) => l.description },
    {
      key: "m",
      header: "Fordeling",
      render: (l) => (l.allocation_method === "equal" ? "Likt" : "Forbruk"),
    },
    { key: "a", header: "Beløp", render: (l) => formatNok(l.amount_nok) },
    {
      key: "x",
      header: "",
      render: (l) =>
        editable ? (
          <button
            type="button"
            onClick={() => void deleteInvoiceLine(sid, l.id).then(onChange)}
            className="text-xs text-rose-400 hover:underline"
          >
            Fjern
          </button>
        ) : null,
    },
  ];

  return (
    <div className="rounded-lg border border-slate-800 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-200">Fakturalinjer</h2>
      <Table
        columns={columns}
        rows={detail.lines}
        rowKey={(l) => l.id}
        empty="Ingen linjer"
      />
      {editable && (
        <form onSubmit={add} className="mt-3 flex flex-wrap items-end gap-2 text-sm">
          <label>
            <span className="mb-1 block text-slate-400">Beskrivelse</span>
            <input
              required
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            />
          </label>
          <label>
            <span className="mb-1 block text-slate-400">Fordeling</span>
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value as AllocationMethod)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            >
              <option value="equal">Likt</option>
              <option value="consumption">Forbruk</option>
            </select>
          </label>
          <label>
            <span className="mb-1 block text-slate-400">Beløp (kr)</span>
            <input
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-28 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            />
          </label>
          <button
            type="submit"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
          >
            Legg til
          </button>
        </form>
      )}
      {err && <p className="mt-1 text-xs text-rose-400">{err}</p>}
    </div>
  );
}

function AttachmentPanel({
  settlementId,
  filename,
  editable,
  onUploaded,
}: {
  settlementId: number;
  filename: string | null;
  editable: boolean;
  onUploaded: () => void | Promise<unknown>;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState<string | null>(null);

  async function upload() {
    const file = ref.current?.files?.[0];
    if (!file) return;
    setErr(null);
    try {
      await uploadSettlementAttachment(settlementId, file);
      await onUploaded();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Opplasting feilet.");
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 p-4 text-sm">
      <h2 className="mb-2 font-semibold text-slate-200">Fakturavedlegg</h2>
      <p className="text-slate-400">
        {filename ? `Lastet opp: ${filename}` : "Ingen fil lastet opp."}
      </p>
      {editable && (
        <div className="mt-2 flex items-center gap-2">
          <input ref={ref} type="file" aria-label="Fakturavedlegg" className="text-slate-300" />
          <button
            type="button"
            onClick={() => void upload()}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
          >
            Last opp
          </button>
        </div>
      )}
      {err && <p className="mt-1 text-xs text-rose-400">{err}</p>}
    </div>
  );
}

function UnassignedPanel({
  month,
  onResolved,
}: {
  month: string;
  onResolved: () => void | Promise<unknown>;
}) {
  const { data, mutate } = useSWR([`/api/charging/unassigned`, month], () =>
    getUnassigned(month),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!data || Number(data.total_kwh) === 0) return null;

  async function reresolve() {
    setErr(null);
    setBusy(true);
    try {
      await reresolveCharging(month);
      await Promise.all([mutate(), onResolved()]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Kunne ikke kjøre ny fordeling.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-amber-700/60 bg-amber-950/40 p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <p className="font-medium text-amber-200">
          {data.total_kwh} kWh i {month} er ikke fordelt på noe medlem – dette blokkerer
          frysing.
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={() => void reresolve()}
          className="shrink-0 rounded-md border border-amber-600 px-3 py-1 text-xs text-amber-100 hover:bg-amber-900/60 disabled:opacity-50"
        >
          Kjør ny fordeling
        </button>
      </div>
      <ul className="mt-2 space-y-0.5 text-amber-100/80">
        {data.chargers.map((u) => (
          <li key={u.charger_zaptec_id}>
            {u.charger_name ?? u.charger_zaptec_id}: {u.energy_kwh} kWh ({u.sessions} økt
            {u.sessions === 1 ? "" : "er"})
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-amber-100/70">
        Tildel laderne et medlem på <Link to="/chargers" className="underline">Ladere</Link> med
        gyldig fra-dato i {month}, og kjør ny fordeling.
      </p>
      {err && (
        <p role="alert" className="mt-1 text-xs text-rose-400">
          {err}
        </p>
      )}
    </div>
  );
}

function PreviewPanel({ preview }: { preview: SettlementPreview }) {
  const columns: Column<SettlementPreview["members"][number]>[] = [
    { key: "ref", header: "Ref.", render: (m) => m.member_reference },
    { key: "name", header: "Navn", render: (m) => m.full_name },
    { key: "kwh", header: "kWh", render: (m) => m.consumption_kwh },
    { key: "before", header: "Saldo før", render: (m) => formatNok(m.balance_before_nok) },
    { key: "charge", header: "Belastes", render: (m) => formatNok(m.charge_nok) },
    {
      key: "after",
      header: "Saldo etter",
      render: (m) => (
        <span className={m.balance_after_ore < 0 ? "text-rose-400" : undefined}>
          {formatNok(m.balance_after_nok)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-200">Forhåndsvisning</h2>
      {preview.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
          {preview.warnings.map((w) => (
            <li key={w.code}>{WARNING_LABELS[w.code] ?? w.code}</li>
          ))}
        </ul>
      )}
      <Table
        columns={columns}
        rows={preview.members}
        rowKey={(m) => m.member_id}
        empty="Ingen medlemmer i avregningen"
      />
      <p className="text-sm text-slate-300">
        Sum belastet: <strong>{formatNok(preview.total_charged_nok)}</strong> · Sum fakturalinjer:{" "}
        {formatNok(preview.invoice_lines_total_nok)}
      </p>
    </div>
  );
}
