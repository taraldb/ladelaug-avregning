import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import useSWR from "swr";
import { ROUTES } from "../routes";
import {
  ApiError,
  changeParticipation,
  changeStatus,
  departureCheck,
  getBalance,
  getLedger,
  getMember,
  getMemberAccess,
  participationHistory,
  processDeparture,
  recordAdjustment,
  recordMemberAccess,
  recordRefund,
  reversePayment,
  setUserDisabled,
  statusHistory,
  updateMember,
  listUsers,
  type AccessAction,
  type DepartureCheck,
  type LedgerTxn,
  type Member,
  type MemberStatus,
} from "../api/client";
import DateField from "../components/DateField";
import Modal from "../components/Modal";
import Money from "../components/Money";
import RecordPaymentModal from "../components/RecordPaymentModal";
import StatTile from "../components/StatTile";
import Table, { type Column } from "../components/Table";
import {
  formatDate,
  formatDateTime,
  formatNok,
  formatOre,
  normalizeDecimalInput,
  txnTypeLabel,
} from "../lib/format";
import { NewUserModal, SetPasswordModal } from "./Users";
import { btnPrimary, btnRow, btnSecondary, inputClass } from "../lib/ui";

export default function MemberDetail() {
  const { id } = useParams<{ id: string }>();
  const memberId = Number(id);

  const memberKey = Number.isFinite(memberId) ? `/api/members/${memberId}` : null;
  const {
    data: member,
    error,
    isLoading,
    mutate: mutateMember,
  } = useSWR(memberKey, () => getMember(memberId));

  if (!Number.isFinite(memberId)) {
    return <p className="text-sm text-rose-400">Ugyldig medlems-ID.</p>;
  }
  if (error) {
    const message =
      error instanceof ApiError && error.status === 404
        ? "Fant ikke medlemmet."
        : (error as ApiError).message;
    return (
      <div className="space-y-3">
        <BackLink />
        <p role="alert" className="text-sm text-rose-400">
          {message}
        </p>
      </div>
    );
  }
  if (isLoading || !member) {
    return <p className="text-sm text-slate-400">Laster …</p>;
  }

  return (
    <section className="space-y-8">
      <div className="space-y-1">
        <BackLink />
        <h1 className="text-lg font-semibold text-slate-100">{member.full_name}</h1>
        <p className="text-sm text-slate-400">{member.member_reference}</p>
      </div>

      <ProfileCard member={member} onSaved={async () => void (await mutateMember())} />
      <LoginSection member={member} />
      <StatusSection
        memberId={memberId}
        onChanged={async () => void (await mutateMember())}
      />
      <ParticipationSection
        memberId={memberId}
        onChanged={async () => void (await mutateMember())}
      />
      <LedgerSection memberId={memberId} />
      <AccessSection memberId={memberId} />
      <DepartureSection
        memberId={memberId}
        onChanged={async () => void (await mutateMember())}
      />
    </section>
  );
}

const ACCESS_LABEL: Record<AccessAction, string> = {
  warned: "Varslet",
  disabled: "Stengt",
  restored: "Gjenåpnet",
};

function AccessSection({ memberId }: { memberId: number }) {
  const key = `/api/members/${memberId}/access`;
  const { data, mutate } = useSWR(key, () => getMemberAccess(memberId));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<AccessAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(action: AccessAction) {
    setError(null);
    setBusy(action);
    try {
      const res = await recordMemberAccess(memberId, {
        action,
        reason: reason.trim() || undefined,
      });
      setReason("");
      await mutate(res, { revalidate: false });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Handlingen feilet.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="Ladetilgang">
      <p className="text-xs text-slate-500">
        Registrerer status og varsler medlemmet på e-post. Stenging må gjøres i
        Zaptec-portalen — dette er ikke en teknisk sperre.
      </p>
      <p className="mt-2 text-sm text-slate-300">
        Nåværende status:{" "}
        <span className="text-slate-100">
          {data?.status ? ACCESS_LABEL[data.status] : "Ingen registrert"}
        </span>
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="block text-sm">
          <span className="mb-1 block text-slate-400">Årsak (valgfritt)</span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <button
          type="button"
          disabled={busy != null}
          onClick={() => void act("warned")}
          className="rounded-md border border-amber-600/60 px-3 py-1.5 text-sm text-amber-300 hover:bg-amber-500/10 disabled:opacity-60"
        >
          Send varsel
        </button>
        <button
          type="button"
          disabled={busy != null}
          onClick={() => void act("disabled")}
          className="rounded-md border border-rose-600/60 px-3 py-1.5 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-60"
        >
          Steng
        </button>
        <button
          type="button"
          disabled={busy != null}
          onClick={() => void act("restored")}
          className="rounded-md border border-emerald-600/60 px-3 py-1.5 text-sm text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-60"
        >
          Gjenåpne
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose-400">
          {error}
        </p>
      )}
      {data && data.history.length > 0 && (
        <ol className="mt-3 space-y-1 text-xs text-slate-400">
          {data.history.map((e) => (
            <li key={e.id} className="border-l-2 border-slate-700 pl-3">
              {ACCESS_LABEL[e.action]} · {formatDateTime(e.created_at)}
              {e.reason ? ` · ${e.reason}` : ""}
              {e.email_message_id ? " · e-post sendt" : ""}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function DepartureSection({
  memberId,
  onChanged,
}: {
  memberId: number;
  onChanged: () => void | Promise<void>;
}) {
  const [effectiveDate, setEffectiveDate] = useState("");
  const [check, setCheck] = useState<DepartureCheck | null>(null);
  const [refund, setRefund] = useState(false);
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function runCheck() {
    setError(null);
    setDone(null);
    setBusy(true);
    try {
      setCheck(await departureCheck(memberId, effectiveDate || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sjekk feilet.");
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!check) return;
    setError(null);
    setBusy(true);
    try {
      const res = await processDeparture(memberId, {
        effective_date: check.effective_date,
        refund,
        refund_reference: reference.trim() || undefined,
      });
      setDone(
        `Utmeldt ${res.effective_date}. ${res.assignments_closed.length} ladere frigjort` +
          (res.refund_txn_id ? `, ${formatOre(res.refunded_ore)} refundert.` : "."),
      );
      setCheck(null);
      await onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Utmelding feilet.");
    } finally {
      setBusy(false);
    }
  }

  const refundBlocked = refund && (check?.unsettled_months.length ?? 0) > 0;

  return (
    <Card title="Utmelding">
      <div className="flex flex-wrap items-end gap-2">
        <label className="block text-sm">
          <span className="mb-1 block text-slate-400">Utmeldingsdato</span>
          <input
            type="date"
            value={effectiveDate}
            onChange={(e) => setEffectiveDate(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={() => void runCheck()}
          className={btnSecondary}
        >
          Sjekk utmelding
        </button>
      </div>

      {check && (
        <div className="mt-3 space-y-2 text-sm text-slate-300">
          <p>
            Åpne ladertilknytninger:{" "}
            <span className="text-slate-100">
              {check.open_assignments.length === 0
                ? "ingen"
                : check.open_assignments.map((a) => a.charger_name).join(", ")}
            </span>
          </p>
          <p>
            Måneder uten bokført avregning:{" "}
            <span className={check.unsettled_months.length ? "text-amber-300" : "text-slate-100"}>
              {check.unsettled_months.length === 0
                ? "ingen"
                : check.unsettled_months.join(", ")}
            </span>
          </p>
          <p>
            Saldo: <span className="text-slate-100">{formatNok(check.balance_nok)}</span>
          </p>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={refund}
              onChange={(e) => setRefund(e.target.checked)}
            />
            Refunder resterende saldo ved utmelding
          </label>
          {refund && (
            <label className="block">
              <span className="mb-1 block text-slate-400">Referanse (valgfritt)</span>
              <input
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
              />
            </label>
          )}
          {refundBlocked && (
            <p className="text-xs text-amber-300">
              Refusjon er sperret så lenge det finnes uavregnede måneder.
            </p>
          )}
          <button
            type="button"
            disabled={busy || refundBlocked}
            onClick={() => void run()}
            className="rounded-md bg-rose-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-rose-400 disabled:opacity-60"
          >
            Meld ut
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-sm text-rose-400">
          {error}
        </p>
      )}
      {done && <p className="mt-2 text-sm text-emerald-300">{done}</p>}
    </Card>
  );
}

const PAGE_SIZE = 20;

function LedgerSection({ memberId }: { memberId: number }) {
  const [page, setPage] = useState(0);
  const [modal, setModal] = useState<"payment" | "adjustment" | "refund" | null>(
    null,
  );

  const balance = useSWR(`/api/members/${memberId}/balance`, () =>
    getBalance(memberId),
  );
  const ledger = useSWR(
    `/api/members/${memberId}/ledger?page=${page}`,
    () => getLedger(memberId, { limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
  );

  async function refresh() {
    await Promise.all([balance.mutate(), ledger.mutate()]);
  }

  const [reversingId, setReversingId] = useState<number | null>(null);
  const [reverseError, setReverseError] = useState<string | null>(null);

  async function onReverse(txnId: number) {
    setReverseError(null);
    setReversingId(txnId);
    try {
      await reversePayment(txnId);
      await refresh();
    } catch (err) {
      setReverseError(
        err instanceof ApiError ? err.message : "Kunne ikke reversere.",
      );
    } finally {
      setReversingId(null);
    }
  }

  const txns = ledger.data?.transactions ?? [];
  const total = ledger.data?.total ?? 0;
  const reversedIds = new Set(
    txns
      .map((t) => t.reverses_transaction_id)
      .filter((v): v is number => v != null),
  );

  const columns: Column<LedgerTxn>[] = [
    { key: "date", card: "title", header: "Valørdato", render: (t) => formatDate(t.value_date) },
    { key: "type", header: "Type", render: (t) => txnTypeLabel(t.txn_type) },
    {
      key: "amount",
      header: "Beløp",
      className: "text-right tabular-nums",
      render: (t) => (
        <Money
          value={t.amount_nok}
          className={t.amount_ore < 0 ? "text-rose-400" : "text-emerald-400"}
        />
      ),
    },
    {
      key: "detail",
      header: "Detaljer",
      render: (t) => t.reason ?? t.reference ?? "–",
    },
    {
      key: "actions", card: "footer",
      header: "",
      className: "text-right",
      render: (t) =>
        t.txn_type === "payment" && !reversedIds.has(t.id) ? (
          <button
            type="button"
            onClick={() => onReverse(t.id)}
            disabled={reversingId === t.id}
            className={btnRow}
          >
            Reverser
          </button>
        ) : null,
    },
  ];

  return (
    <Card title="Saldo og transaksjoner">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <StatTile
          label="Saldo"
          value={
            balance.data ? formatNok(balance.data.balance_nok) : "…"
          }
          tone={
            balance.data && balance.data.balance_ore < 0 ? "negative" : "positive"
          }
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setModal("payment")}
            className={btnPrimary}
          >
            Registrer innbetaling
          </button>
          <button
            type="button"
            onClick={() => setModal("adjustment")}
            className={btnSecondary}
          >
            Manuell justering
          </button>
          <button
            type="button"
            onClick={() => setModal("refund")}
            className={btnSecondary}
          >
            Refusjon
          </button>
        </div>
      </div>

      {reverseError && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {reverseError}
        </p>
      )}

      <div className="mt-4">
        <Table
          columns={columns}
          rows={txns}
          rowKey={(t) => t.id}
          empty="Ingen transaksjoner"
        />
      </div>

      {total > PAGE_SIZE && (
        <div className="mt-3 flex items-center justify-between text-sm text-slate-400">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-md border border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Forrige
          </button>
          <span>
            Side {page + 1} av {Math.ceil(total / PAGE_SIZE)}
          </span>
          <button
            type="button"
            disabled={(page + 1) * PAGE_SIZE >= total}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Neste
          </button>
        </div>
      )}

      <RecordPaymentModal
        open={modal === "payment"}
        memberId={memberId}
        onClose={() => setModal(null)}
        onDone={async () => {
          await refresh();
          setModal(null);
        }}
      />
      <AdjustmentModal
        open={modal === "adjustment"}
        memberId={memberId}
        onClose={() => setModal(null)}
        onDone={async () => {
          await refresh();
          setModal(null);
        }}
      />
      <RefundModal
        open={modal === "refund"}
        memberId={memberId}
        onClose={() => setModal(null)}
        onDone={async () => {
          await refresh();
          setModal(null);
        }}
      />
    </Card>
  );
}

function RefundModal({
  open,
  memberId,
  onClose,
  onDone,
}: {
  open: boolean;
  memberId: number;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [reference, setReference] = useState("");
  const [allowNegative, setAllowNegative] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setAmount("");
    setReference("");
    setAllowNegative(false);
    setError(null);
    setSaving(false);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await recordRefund(memberId, {
        amount: normalizeDecimalInput(amount),
        reference: reference.trim() || undefined,
        allow_negative: allowNegative,
      });
      reset();
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke refundere.");
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Refusjon"
      onClose={() => {
        reset();
        onClose();
      }}
      footer={
        <>
          <button
            type="button"
            onClick={() => {
              reset();
              onClose();
            }}
            className={btnSecondary}
          >
            Avbryt
          </button>
          <button
            type="submit"
            form="refund-form"
            disabled={saving || amount.trim() === ""}
            className={btnPrimary}
          >
            Bokfør refusjon
          </button>
        </>
      }
    >
      <form id="refund-form" className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Beløp (kr)</span>
          <input
            inputMode="decimal"
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="500.00"
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Regnskapsreferanse (valgfritt)
          </span>
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={allowNegative}
            onChange={(e) => setAllowNegative(e.target.checked)}
          />
          Tillat negativ saldo
        </label>
        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}

function AdjustmentModal({
  open,
  memberId,
  onClose,
  onDone,
}: {
  open: boolean;
  memberId: number;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [direction, setDirection] = useState<"credit" | "debit">("credit");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setDirection("credit");
    setAmount("");
    setReason("");
    setReference("");
    setError(null);
    setSaving(false);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await recordAdjustment(memberId, {
        direction,
        amount: normalizeDecimalInput(amount),
        reason: reason.trim(),
        reference: reference.trim() || undefined,
      });
      reset();
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke justere.");
      setSaving(false);
    }
  }

  const canSubmit = amount.trim() !== "" && reason.trim() !== "";

  return (
    <Modal
      open={open}
      title="Manuell justering"
      onClose={() => {
        reset();
        onClose();
      }}
      footer={
        <>
          <button
            type="button"
            onClick={() => {
              reset();
              onClose();
            }}
            className={btnSecondary}
          >
            Avbryt
          </button>
          <button
            type="submit"
            form="adjustment-form"
            disabled={saving || !canSubmit}
            className={btnPrimary}
          >
            Bokfør justering
          </button>
        </>
      }
    >
      <form id="adjustment-form" className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Retning</span>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as "credit" | "debit")}
            className={inputClass}
          >
            <option value="credit">Kredit (øker saldo)</option>
            <option value="debit">Debet (reduserer saldo)</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Beløp (kr)
          </span>
          <input
            inputMode="decimal"
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="50.00"
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Begrunnelse (påkrevd)
          </span>
          <input
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Referanse (valgfritt)
          </span>
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            className={inputClass}
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}

function BackLink() {
  return (
    <Link to={ROUTES.members} className="text-xs text-emerald-400 hover:underline">
      ← Tilbake til medlemmer
    </Link>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function ProfileCard({
  member,
  onSaved,
}: {
  member: Member;
  onSaved: () => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [reference, setReference] = useState(member.member_reference);
  const [fullName, setFullName] = useState(member.full_name);
  const [email, setEmail] = useState(member.email ?? "");
  const [joinDate, setJoinDate] = useState(member.join_date);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function startEdit() {
    setReference(member.member_reference);
    setFullName(member.full_name);
    setEmail(member.email ?? "");
    setJoinDate(member.join_date);
    setError(null);
    setEditing(true);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await updateMember(member.id, {
        member_reference: reference.trim(),
        full_name: fullName.trim(),
        email: email.trim(),
        join_date: joinDate,
      });
      setEditing(false);
      await onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke lagre.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <Card title="Profil">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-slate-400">Referanse</dt>
          <dd className="break-words text-slate-100">{member.member_reference}</dd>
          <dt className="text-slate-400">Navn</dt>
          <dd className="break-words text-slate-100">{member.full_name}</dd>
          <dt className="text-slate-400">Reserve-e-post</dt>
          <dd className="break-words text-slate-100">{member.email ?? "–"}</dd>
          <dt className="text-slate-400">Innmeldt</dt>
          <dd className="break-words text-slate-100">{formatDate(member.join_date)}</dd>
        </dl>
        <p className="mt-2 text-xs text-slate-500">
          Reserve-e-post brukes kun for varsler til medlemmer uten aktiv pålogging.
          Har medlemmet en pålogging, sendes all e-post dit.
        </p>
        <button
          type="button"
          onClick={startEdit}
          className="mt-4 rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
        >
          Rediger
        </button>
      </Card>
    );
  }

  return (
    <Card title="Profil">
      <form className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Referanse</span>
          <input
            required
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Navn</span>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Reserve-e-post</span>
          <input
            type="text"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Brukes kun for varsler til medlemmer uten aktiv pålogging.
          </span>
        </label>
        <DateField label="Innmeldt" value={joinDate} onChange={setJoinDate} required />

        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={saving}
            className={btnPrimary}
          >
            Lagre
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className={btnSecondary}
          >
            Avbryt
          </button>
        </div>
      </form>
    </Card>
  );
}

function LoginSection({ member }: { member: Member }) {
  const { data, mutate } = useSWR("/api/users", () => listUsers());
  const login = data?.users.find((u) => u.member_id === member.id) ?? null;
  const [createOpen, setCreateOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (!login) return;
    setError(null);
    setBusy(true);
    try {
      await setUserDisabled(login.id, !login.disabled);
      await mutate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke oppdatere.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Pålogging">
      {login ? (
        <div className="space-y-3 text-sm">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <dt className="text-slate-400">E-post</dt>
            <dd className="break-words text-slate-100">{login.email}</dd>
            <dt className="text-slate-400">Status</dt>
            <dd className={login.disabled ? "text-rose-400" : "text-emerald-400"}>
              {login.disabled ? "Deaktivert" : "Aktiv"}
            </dd>
          </dl>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPwOpen(true)}
              className={btnSecondary}
            >
              Nytt passord
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void toggle()}
              className={btnSecondary}
            >
              {login.disabled ? "Aktiver" : "Deaktiver"}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-slate-400">Medlemmet har ingen pålogging.</p>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className={btnPrimary}
          >
            Opprett pålogging
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {error}
        </p>
      )}

      <NewUserModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={async () => {
          await mutate();
          setCreateOpen(false);
        }}
        lockedMember={{
          id: member.id,
          label: `${member.member_reference} – ${member.full_name}`,
        }}
      />
      <SetPasswordModal
        user={pwOpen ? login : null}
        onClose={() => setPwOpen(false)}
        onDone={() => setPwOpen(false)}
      />
    </Card>
  );
}

function StatusSection({
  memberId,
  onChanged,
}: {
  memberId: number;
  onChanged: () => void | Promise<void>;
}) {
  const { data, mutate } = useSWR(`/api/members/${memberId}/status-history`, () =>
    statusHistory(memberId),
  );
  const [status, setStatus] = useState<MemberStatus>("inactive");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const periods = data?.periods ?? [];

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await changeStatus(memberId, {
        status,
        effective_from: effectiveFrom || undefined,
        note: note.trim() || undefined,
      });
      setNote("");
      setEffectiveFrom("");
      await Promise.all([mutate(), onChanged()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke endre status.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Status">
      <ol className="space-y-2 text-sm">
        {periods.length === 0 && <li className="text-slate-500">Ingen historikk.</li>}
        {periods.map((p) => (
          <li
            key={p.id}
            className="flex flex-wrap items-baseline gap-x-2 border-l-2 border-slate-700 pl-3"
          >
            <span className="font-medium text-slate-100">
              {p.status === "active" ? "Aktiv" : "Inaktiv"}
            </span>
            <span className="text-slate-400">
              {formatDate(p.effective_from)} –{" "}
              {p.effective_to ? formatDate(p.effective_to) : "løpende"}
            </span>
            {p.note && <span className="text-slate-500">· {p.note}</span>}
          </li>
        ))}
      </ol>

      <form className="mt-4 space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Ny status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as MemberStatus)}
            className={inputClass}
          >
            <option value="active">Aktiv</option>
            <option value="inactive">Inaktiv</option>
          </select>
        </label>
        <DateField
          label="Gjelder fra"
          value={effectiveFrom}
          onChange={setEffectiveFrom}
          hint="Tomt = i dag"
        />
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Notat</span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className={inputClass}
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className={btnPrimary}
        >
          Endre status
        </button>
      </form>
    </Card>
  );
}

function ParticipationSection({
  memberId,
  onChanged,
}: {
  memberId: number;
  onChanged: () => void | Promise<void>;
}) {
  const { data, mutate } = useSWR(
    `/api/members/${memberId}/participation-history`,
    () => participationHistory(memberId),
  );
  const [participates, setParticipates] = useState(true);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const periods = data?.periods ?? [];

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await changeParticipation(memberId, {
        participates,
        effective_from: effectiveFrom || undefined,
        reason: reason.trim() || undefined,
      });
      setReason("");
      setEffectiveFrom("");
      await Promise.all([mutate(), onChanged()]);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Kunne ikke endre deltakelse.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Deltakelse i avregning">
      <ol className="space-y-2 text-sm">
        {periods.length === 0 && (
          <li className="text-slate-500">Ingen eksplisitt historikk.</li>
        )}
        {periods.map((p) => (
          <li
            key={p.id}
            className="flex flex-wrap items-baseline gap-x-2 border-l-2 border-slate-700 pl-3"
          >
            <span className="font-medium text-slate-100">
              {p.participates ? "Deltar" : "Deltar ikke"}
            </span>
            <span className="text-slate-400">
              {formatDate(p.effective_from)} –{" "}
              {p.effective_to ? formatDate(p.effective_to) : "løpende"}
            </span>
            {p.reason && <span className="text-slate-500">· {p.reason}</span>}
            <span className="text-slate-600">
              ({formatDateTime(p.created_at)})
            </span>
          </li>
        ))}
      </ol>

      <form className="mt-4 space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Deltakelse</span>
          <select
            value={participates ? "yes" : "no"}
            onChange={(e) => setParticipates(e.target.value === "yes")}
            className={inputClass}
          >
            <option value="yes">Deltar</option>
            <option value="no">Deltar ikke</option>
          </select>
        </label>
        <DateField
          label="Gjelder fra"
          value={effectiveFrom}
          onChange={setEffectiveFrom}
          hint="Tomt = i dag"
        />
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Begrunnelse</span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={inputClass}
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className={btnPrimary}
        >
          Oppdater deltakelse
        </button>
      </form>
    </Card>
  );
}
