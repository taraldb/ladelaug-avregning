import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import useSWR from "swr";
import { ROUTES } from "../routes";
import {
  ApiError,
  addInvoiceLine,
  assessCorrection,
  deleteInvoiceLine,
  updateInvoiceLine,
  freezeSettlement,
  getConsumption,
  getSettlement,
  getUnassigned,
  listMembers,
  postCorrection,
  postSettlement,
  previewSettlement,
  deleteSettlementAttachment,
  reresolveCharging,
  resendSettlementReports,
  setSettlementInvoice,
  settlementReports,
  shareSettlementDraft,
  unshareSettlementDraft,
  uploadSettlementAttachments,
  type AllocationMethod,
  type CorrectionAssessment,
  type SettlementAttachment,
  type SettlementDetail as SettlementDetailData,
  type SettlementPreview,
} from "../api/client";
import ConfirmModal from "../components/ConfirmModal";
import Money from "../components/Money";
import Table, { type Column } from "../components/Table";
import { formatNok, formatOre, normalizeDecimalInput } from "../lib/format";

const WARNING_LABELS: Record<string, string> = {
  negative_balances: "Noen medlemmer får negativ saldo",
  invoice_kwh_missing: "Fakturert kWh mangler",
  attachment_missing: "Faktura mangler",
  zero_consumption: "Ingen registrert forbruk – forbrukslinjer kan ikke fordeles",
  late_sessions: "Sene ladeøkter ikke behandlet",
  kwh_mismatch: "Fakturert kWh avviker mye fra målt",
  usage_stale: "Forbruket er endret etter frysing – frys på nytt",
  charge_total_mismatch:
    "Sum belastet er ikke lik sum fakturalinjer – en likt-fordelt linje har ingen deltakende medlemmer",
};
const BLOCKING = new Set(["zero_consumption", "usage_stale", "charge_total_mismatch"]);

export default function SettlementDetail() {
  const { id } = useParams();
  const sid = Number(id);
  const key = `/api/settlement/${sid}`;
  const { data, error, isLoading, mutate } = useSWR(key, () => getSettlement(sid));
  const [preview, setPreview] = useState<SettlementPreview | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [resendConfirm, setResendConfirm] = useState(false);
  const [resending, setResending] = useState(false);
  const reports = useSWR(
    data?.settlement.usage_frozen_at ? `${key}/reports` : null,
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

  async function doResend() {
    setResendConfirm(false);
    setBanner(null);
    setResending(true);
    try {
      const res = await resendSettlementReports(sid);
      setBanner(
        `${res.emails_queued} e-poster lagt i kø. De sendes når e-postkøen kjøres.`,
      );
    } catch (err) {
      setBanner(
        err instanceof ApiError ? err.message : "Kunne ikke legge e-postene i kø.",
      );
    } finally {
      setResending(false);
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
        attachments={data.attachments}
        onChange={mutate}
      />

      {isDraft && <ConsumptionPanel month={s.period_month} />}

      {isDraft && <UnassignedPanel month={s.period_month} onResolved={mutate} />}

      <div className="flex flex-wrap gap-2">
        {isDraft && (
          <button
            type="button"
            onClick={() =>
              void act(() => freezeSettlement(sid), "Forbruk fryst.").then(() =>
                reports.mutate(),
              )
            }
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
              data.attachments.length === 0 ||
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

      {isDraft && s.usage_frozen_at && (
        <div className="rounded-md border border-slate-800 p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold text-slate-200">Utkast til medlemmer</h2>
            {s.draft_shared_at ? (
              <span className="rounded-md bg-amber-500/20 px-2 py-1 text-xs font-semibold text-amber-300">
                Delt {s.draft_shared_at.slice(0, 16).replace("T", " ")}
              </span>
            ) : (
              <span className="rounded-md bg-slate-700/40 px-2 py-1 text-xs text-slate-400">
                Ikke delt
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Lar medlemmene se sin egen del av denne avregningen som et tydelig merket
            utkast, før du bokfører. Tallene oppdateres hvis du fryser på nytt.
          </p>
          <div className="mt-3">
            {s.draft_shared_at ? (
              <button
                type="button"
                onClick={() =>
                  void act(() => unshareSettlementDraft(sid), "Utkast trukket tilbake.")
                }
                className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
              >
                Trekk tilbake
              </button>
            ) : (
              <button
                type="button"
                onClick={() =>
                  void act(() => shareSettlementDraft(sid), "Utkast delt med medlemmene.")
                }
                className="rounded-md border border-amber-600/60 px-3 py-1.5 text-amber-200 hover:bg-amber-900/40"
              >
                Del utkast med medlemmer
              </button>
            )}
          </div>
        </div>
      )}

      {preview && <PreviewPanel preview={preview} />}

      {s.usage_frozen_at && reports.data && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-200">
              {isDraft ? "Rapporter (forhåndsvisning)" : "Rapporter"}
            </h2>
            {!isDraft && (
              <button
                type="button"
                disabled={resending}
                onClick={() => setResendConfirm(true)}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
              >
                Send rapport-e-post på nytt
              </button>
            )}
          </div>
          {isDraft && (
            <p className="text-xs text-slate-500">
              Bygget fra det fryste øyeblikksbildet. Endres hvis du fryser på nytt, og
              lagres endelig først ved bokføring.
            </p>
          )}
          <ul className="space-y-1 text-sm">
            <li className="flex items-center gap-3">
              <a
                className="text-emerald-400 hover:underline"
                href={reports.data.summary_url}
                target="_blank"
                rel="noreferrer"
              >
                Sammendrag
              </a>
              <a
                className="text-slate-400 hover:underline"
                href={`${reports.data.summary_url}.pdf`}
                target="_blank"
                rel="noreferrer"
              >
                PDF
              </a>
            </li>
            {reports.data.members.map((m) => (
              <li key={m.member_id} className="flex items-center gap-3">
                <a
                  className="text-emerald-400 hover:underline"
                  href={m.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {m.full_name} — {formatNok(m.charge_nok)}
                </a>
                <a
                  className="text-slate-400 hover:underline"
                  href={`${m.url}.pdf`}
                  target="_blank"
                  rel="noreferrer"
                >
                  PDF
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      {s.usage_frozen_at && reports.error && (
        <p className="text-xs text-slate-500">
          Rapportforhåndsvisning utilgjengelig: {(reports.error as ApiError).message}
        </p>
      )}

      {!isDraft && (
        <CorrectionPanel detail={data} onChange={() => void mutate()} />
      )}

      <ConfirmModal
        open={resendConfirm}
        title="Send rapport-e-post på nytt?"
        message="Legger én e-post i kø per medlem med aktiv portalkonto og e-postadresse. De sendes når e-postkøen kjøres neste gang (Systemhelse → «Send e-postkø»)."
        confirmLabel="Legg i kø"
        tone="normal"
        busy={resending}
        onConfirm={() => void doResend()}
        onClose={() => setResendConfirm(false)}
      />
    </section>
  );
}

function CorrectionPanel({
  detail,
  onChange,
}: {
  detail: SettlementDetailData;
  onChange: () => void | Promise<void>;
}) {
  const sid = detail.settlement.id;
  const [assessment, setAssessment] = useState<CorrectionAssessment | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function assess() {
    setMsg(null);
    setBusy(true);
    try {
      setAssessment(await assessCorrection(sid));
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Vurdering feilet.");
    } finally {
      setBusy(false);
    }
  }

  async function book() {
    setBusy(true);
    setConfirm(false);
    try {
      const res = await postCorrection(sid);
      setMsg(
        `Korrigering #${res.sequence} bokført: ${res.members_adjusted} medlemmer, ${res.emails_queued} e-poster i kø.`,
      );
      setAssessment(null);
      await onChange();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Bokføring feilet.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Korrigering</h2>
        {detail.correction_pending && (
          <span className="rounded-md bg-amber-500/20 px-2 py-1 text-xs font-semibold text-amber-300">
            Endret forbruk – korrigering tilgjengelig
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Regner om denne bokførte avregningen fra dagens importerte forbruk mot de
        fryste fakturalinjene. Original avregning røres ikke.
      </p>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void assess()}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
        >
          Vurder korrigering
        </button>
        {assessment?.has_changes && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setConfirm(true)}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            Bokfør korrigering
          </button>
        )}
      </div>

      {msg && <p className="mt-2 text-sm text-slate-300">{msg}</p>}

      {assessment && !assessment.has_changes && (
        <p className="mt-3 text-sm text-slate-400">
          Forbruket stemmer med den bokførte avregningen – ingenting å korrigere.
        </p>
      )}

      {assessment && assessment.has_changes && (
        <table className="mt-3 w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="py-1">Medlem</th>
              <th className="py-1 text-right">kWh før</th>
              <th className="py-1 text-right">kWh nå</th>
              <th className="py-1 text-right">Endring</th>
            </tr>
          </thead>
          <tbody>
            {assessment.members.map((m) => (
              <tr key={m.member_id} className="border-t border-slate-800">
                <td className="py-1 text-slate-200">
                  {m.member_reference} – {m.full_name}
                  {!m.in_snapshot && (
                    <span className="ml-1 text-xs text-amber-300">(ny)</span>
                  )}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {m.consumption_kwh_before}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {m.consumption_kwh_after}
                </td>
                <td className="py-1 text-right tabular-nums">
                  <Money
                    ore={m.delta_ore}
                    className={
                      m.delta_ore > 0 ? "text-emerald-400" : "text-rose-400"
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {detail.corrections.length > 0 && (
        <ol className="mt-3 space-y-1 text-xs text-slate-400">
          {detail.corrections.map((c) => (
            <li key={c.id} className="border-l-2 border-slate-700 pl-3">
              Korrigering #{c.sequence} · {c.members.length} medlemmer ·{" "}
              {formatOre(c.corrected_total_ore - c.original_total_ore)} netto
            </li>
          ))}
        </ol>
      )}

      <ConfirmModal
        open={confirm}
        title="Bokfør korrigering?"
        message="Dette skriver korrigeringstransaksjoner på medlemmenes saldo og varsler dem på e-post. Kan ikke angres."
        confirmLabel="Bokfør"
        tone="normal"
        busy={busy}
        onConfirm={() => void book()}
        onClose={() => setConfirm(false)}
      />
    </div>
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
      await setSettlementInvoice(settlementId, {
        invoice_kwh: normalizeDecimalInput(value),
      });
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

const lineInput =
  "rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100";
const METHOD_LABEL: Record<AllocationMethod, string> = {
  equal: "Likt",
  consumption: "Forbruk",
};

/** Segmented Likt / Forbruk control — a keyboard-and-click friendly replacement
 *  for the allocation-method dropdown. */
function MethodToggle({
  value,
  onChange,
}: {
  value: AllocationMethod;
  onChange: (v: AllocationMethod) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Fordeling"
      className="inline-flex rounded-md border border-slate-700 p-0.5"
    >
      {(["consumption", "equal"] as const).map((m) => (
        <button
          key={m}
          type="button"
          aria-label={METHOD_LABEL[m]}
          aria-pressed={value === m}
          onClick={() => onChange(m)}
          className={`rounded px-3 py-1 text-sm transition-colors ${
            value === m
              ? "bg-emerald-500 font-semibold text-slate-950"
              : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          {METHOD_LABEL[m]}
        </button>
      ))}
    </div>
  );
}

type InvoiceLineRow = Awaited<ReturnType<typeof getSettlement>>["lines"][number];

function EditLineForm({
  sid,
  line,
  onSaved,
  onCancel,
}: {
  sid: number;
  line: InvoiceLineRow;
  onSaved: () => void | Promise<unknown>;
  onCancel: () => void;
}) {
  const [description, setDescription] = useState(line.description);
  const [method, setMethod] = useState<AllocationMethod>(line.allocation_method);
  const [amount, setAmount] = useState(line.amount_nok);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setSaving(true);
    try {
      await updateInvoiceLine(sid, line.id, {
        description: description.trim(),
        allocation_method: method,
        amount: normalizeDecimalInput(amount),
      });
      await onSaved();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Kunne ikke lagre linjen.");
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={save}
      className="flex flex-wrap items-end gap-2 text-sm"
      aria-label={`Endre linje ${line.description}`}
    >
      <label>
        <span className="mb-1 block text-slate-400">Beskrivelse</span>
        <input
          required
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className={lineInput}
        />
      </label>
      <div>
        <span className="mb-1 block text-slate-400">Fordeling</span>
        <MethodToggle value={method} onChange={setMethod} />
      </div>
      <label>
        <span className="mb-1 block text-slate-400">Beløp (kr)</span>
        <input
          required
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={`w-28 ${lineInput}`}
        />
      </label>
      <button
        type="submit"
        disabled={saving}
        className="rounded-md bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
      >
        Lagre
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
      >
        Avbryt
      </button>
      {err && <p className="w-full text-xs text-rose-400">{err}</p>}
    </form>
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
  const [method, setMethod] = useState<AllocationMethod>("consumption");
  const [amount, setAmount] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const descriptionRef = useRef<HTMLInputElement>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await addInvoiceLine(sid, {
        description: description.trim(),
        allocation_method: method,
        amount: normalizeDecimalInput(amount),
      });
      setDescription("");
      setAmount("");
      setMethod("consumption");
      await onChange();
      // Ready for the next line without reaching for the mouse.
      descriptionRef.current?.focus();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Kunne ikke legge til linje.");
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-200">Fakturalinjer</h2>

      {detail.lines.length === 0 ? (
        <p className="text-sm text-slate-500">Ingen linjer</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="py-1">Beskrivelse</th>
              <th className="py-1">Fordeling</th>
              <th className="py-1 text-right">Beløp</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {detail.lines.map((l) =>
              editable && editingId === l.id ? (
                <tr key={l.id} className="border-t border-slate-800">
                  <td colSpan={4} className="py-2">
                    <EditLineForm
                      sid={sid}
                      line={l}
                      onCancel={() => setEditingId(null)}
                      onSaved={async () => {
                        setEditingId(null);
                        await onChange();
                      }}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={l.id} className="border-t border-slate-800">
                  <td className="py-1 text-slate-200">{l.description}</td>
                  <td className="py-1">{METHOD_LABEL[l.allocation_method]}</td>
                  <td className="py-1 text-right tabular-nums">
                    <Money value={l.amount_nok} />
                  </td>
                  <td className="py-1 text-right">
                    {editable && (
                      <span className="flex justify-end gap-3">
                        <button
                          type="button"
                          onClick={() => {
                            setErr(null);
                            setEditingId(l.id);
                          }}
                          className="text-xs text-emerald-400 hover:underline"
                        >
                          Endre
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void deleteInvoiceLine(sid, l.id).then(onChange)
                          }
                          className="text-xs text-rose-400 hover:underline"
                        >
                          Fjern
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}

      {editable && (
        <form onSubmit={add} className="mt-3 flex flex-wrap items-end gap-2 text-sm">
          <label>
            <span className="mb-1 block text-slate-400">Beskrivelse</span>
            <input
              ref={descriptionRef}
              required
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className={lineInput}
            />
          </label>
          <div>
            <span className="mb-1 block text-slate-400">Fordeling</span>
            <MethodToggle value={method} onChange={setMethod} />
          </div>
          <label>
            <span className="mb-1 block text-slate-400">Beløp (kr)</span>
            <input
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className={`w-28 ${lineInput}`}
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
  attachments,
  onChange,
}: {
  settlementId: number;
  attachments: SettlementAttachment[];
  onChange: () => void | Promise<unknown>;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<SettlementAttachment | null>(null);

  async function upload() {
    const files = Array.from(ref.current?.files ?? []);
    if (files.length === 0) return;
    setErr(null);
    setBusy(true);
    try {
      await uploadSettlementAttachments(settlementId, files);
      if (ref.current) ref.current.value = "";
      await onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Opplasting feilet.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm) return;
    setErr(null);
    setBusy(true);
    try {
      await deleteSettlementAttachment(settlementId, confirm.id);
      setConfirm(null);
      await onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Sletting feilet.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 p-4 text-sm">
      <h2 className="mb-2 font-semibold text-slate-200">Fakturavedlegg</h2>
      {attachments.length === 0 ? (
        <p className="text-slate-400">Ingen fil lastet opp.</p>
      ) : (
        <ul className="space-y-1">
          {attachments.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3">
              <a
                className="text-emerald-400 hover:underline"
                href={`/api/settlement/${settlementId}/attachments/${a.id}`}
                target="_blank"
                rel="noreferrer"
              >
                {a.filename}
              </a>
              <button
                type="button"
                onClick={() => setConfirm(a)}
                className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
              >
                Slett
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-2">
        <input
          ref={ref}
          type="file"
          multiple
          aria-label="Fakturavedlegg"
          className="text-slate-300"
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => void upload()}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800 disabled:opacity-60"
        >
          Last opp
        </button>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Kan legges til og slettes også etter bokføring.
      </p>
      {err && <p className="mt-1 text-xs text-rose-400">{err}</p>}

      <ConfirmModal
        open={confirm !== null}
        title="Slette fakturavedlegg?"
        message={
          <>
            Vil du slette «{confirm?.filename}»? Filen fjernes permanent.
          </>
        }
        confirmLabel="Slett vedlegg"
        busy={busy}
        onConfirm={() => void remove()}
        onClose={() => setConfirm(null)}
      />
    </div>
  );
}

function ConsumptionPanel({ month }: { month: string }) {
  const { data } = useSWR([`/api/charging/consumption`, month], () =>
    getConsumption(month),
  );
  const members = useSWR("/api/members", () => listMembers());
  if (!data) return null;

  const name = (id: number) =>
    members.data?.members.find((m) => m.id === id)?.full_name ?? `#${id}`;
  const unassigned = Number(data.unassigned_kwh);

  return (
    <div className="rounded-md border border-slate-700 bg-slate-900/40 p-3 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-200">
          Forbruk i {month} (foreløpig)
        </h2>
        <span className="text-slate-300">
          Totalt {data.total_kwh} kWh
          {unassigned > 0 && (
            <span className="text-amber-300"> · {data.unassigned_kwh} kWh ikke fordelt</span>
          )}
        </span>
      </div>
      {data.by_member.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-slate-300">
          {data.by_member.map((r) => (
            <li key={r.member_id} className="flex justify-between">
              <span>{name(r.member_id)}</span>
              <span>{r.energy_kwh} kWh</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Live tall fra importerte ladeøkter. Låses inn i avregningen ved «Frys forbruk».
      </p>
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
        Tildel laderne et medlem på <Link to={ROUTES.chargers} className="underline">Ladere</Link> med
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
  const totalsMismatch = preview.warnings.some(
    (w) => w.code === "charge_total_mismatch",
  );
  const columns: Column<SettlementPreview["members"][number]>[] = [
    { key: "ref", header: "Ref.", render: (m) => m.member_reference },
    { key: "name", header: "Navn", render: (m) => m.full_name },
    {
      key: "kwh",
      header: "kWh",
      className: "text-right tabular-nums",
      render: (m) => m.consumption_kwh,
    },
    {
      key: "before",
      header: "Saldo før",
      className: "text-right tabular-nums",
      render: (m) => <Money value={m.balance_before_nok} />,
    },
    {
      key: "charge",
      header: "Belastes",
      className: "text-right tabular-nums",
      render: (m) => <Money value={m.charge_nok} />,
    },
    {
      key: "after",
      header: "Saldo etter",
      className: "text-right tabular-nums",
      render: (m) => (
        <Money
          value={m.balance_after_nok}
          className={m.balance_after_ore < 0 ? "text-rose-400" : undefined}
        />
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
      <p
        className={`text-sm ${totalsMismatch ? "text-rose-300" : "text-slate-300"}`}
      >
        Sum belastet: <strong>{formatNok(preview.total_charged_nok)}</strong> · Sum fakturalinjer:{" "}
        {formatNok(preview.invoice_lines_total_nok)}
      </p>
      {totalsMismatch && (
        <p role="alert" className="text-sm text-rose-300">
          Sum belastet er ikke lik sum fakturalinjer. Avregningen kan ikke bokføres
          før differansen er rettet.
        </p>
      )}
    </div>
  );
}
