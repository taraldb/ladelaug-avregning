import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  changeParticipation,
  changeStatus,
  getBalance,
  getLedger,
  getMember,
  participationHistory,
  recordAdjustment,
  reversePayment,
  setUserDisabled,
  statusHistory,
  updateMember,
  listUsers,
  type LedgerTxn,
  type Member,
  type MemberStatus,
} from "../api/client";
import DateField from "../components/DateField";
import Modal from "../components/Modal";
import RecordPaymentModal from "../components/RecordPaymentModal";
import StatTile from "../components/StatTile";
import Table, { type Column } from "../components/Table";
import { formatDate, formatDateTime, formatNok, txnTypeLabel } from "../lib/format";
import { NewUserModal, SetPasswordModal } from "./Users";

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
    </section>
  );
}

const PAGE_SIZE = 20;

function LedgerSection({ memberId }: { memberId: number }) {
  const [page, setPage] = useState(0);
  const [modal, setModal] = useState<"payment" | "adjustment" | null>(null);

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
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (t) =>
        t.txn_type === "payment" && !reversedIds.has(t.id) ? (
          <button
            type="button"
            onClick={() => onReverse(t.id)}
            disabled={reversingId === t.id}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-60"
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
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
          >
            Registrer innbetaling
          </button>
          <button
            type="button"
            onClick={() => setModal("adjustment")}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
          >
            Manuell justering
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
    </Card>
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
        amount: amount.trim(),
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
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Avbryt
          </button>
          <button
            type="submit"
            form="adjustment-form"
            disabled={saving || !canSubmit}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Referanse (valgfritt)
          </span>
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
    <Link to="/members" className="text-xs text-emerald-400 hover:underline">
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
          <dd className="text-slate-100">{member.member_reference}</dd>
          <dt className="text-slate-400">Navn</dt>
          <dd className="text-slate-100">{member.full_name}</dd>
          <dt className="text-slate-400">E-post</dt>
          <dd className="text-slate-100">{member.email ?? "–"}</dd>
          <dt className="text-slate-400">Innmeldt</dt>
          <dd className="text-slate-100">{formatDate(member.join_date)}</dd>
        </dl>
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Navn</span>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">E-post</span>
          <input
            type="text"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
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
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            Lagre
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
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
            <dd className="text-slate-100">{login.email}</dd>
            <dt className="text-slate-400">Status</dt>
            <dd className={login.disabled ? "text-rose-400" : "text-emerald-400"}>
              {login.disabled ? "Deaktivert" : "Aktiv"}
            </dd>
          </dl>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPwOpen(true)}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            >
              Nytt passord
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void toggle()}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
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
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
          className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
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
          className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
        >
          Oppdater deltakelse
        </button>
      </form>
    </Card>
  );
}
