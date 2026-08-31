import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import { ApiError, listMembers, recordPayment } from "../api/client";
import { normalizeDecimalInput } from "../lib/format";
import DateField from "./DateField";
import Modal from "./Modal";

const today = () => new Date().toISOString().slice(0, 10);

const inputClass =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none";

/**
 * Record an incoming payment. When `memberId` is given the member is fixed
 * (launched from a member's page); otherwise a member picker is shown so the
 * modal can be opened from anywhere. The value date defaults to today.
 */
export default function RecordPaymentModal({
  open,
  memberId,
  onClose,
  onDone,
}: {
  open: boolean;
  memberId?: number;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const needsPicker = memberId == null;
  const { data: membersData } = useSWR(
    open && needsPicker ? "/api/members" : null,
    () => listMembers(),
  );
  const members = membersData?.members ?? [];

  const [memberChoice, setMemberChoice] = useState("");
  const [amount, setAmount] = useState("");
  const [valueDate, setValueDate] = useState(today);
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setMemberChoice("");
    setAmount("");
    setValueDate(today());
    setReference("");
    setError(null);
    setSaving(false);
  }

  // Refresh the prefilled date each time the modal is opened.
  useEffect(() => {
    if (open) setValueDate(today());
  }, [open]);

  function close() {
    reset();
    onClose();
  }

  const targetId = memberId ?? (memberChoice ? Number(memberChoice) : undefined);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!targetId) {
      setError("Velg et medlem.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await recordPayment(targetId, {
        amount: normalizeDecimalInput(amount),
        value_date: valueDate || undefined,
        reference: reference.trim() || undefined,
      });
      reset();
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke registrere.");
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Registrer innbetaling"
      onClose={close}
      footer={
        <>
          <button
            type="button"
            onClick={close}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Avbryt
          </button>
          <button
            type="submit"
            form="record-payment-form"
            disabled={saving || amount.trim() === "" || (needsPicker && !memberChoice)}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            Registrer
          </button>
        </>
      }
    >
      <form id="record-payment-form" className="space-y-3" onSubmit={onSubmit}>
        {needsPicker && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-300">Medlem</span>
            <select
              required
              value={memberChoice}
              onChange={(e) => setMemberChoice(e.target.value)}
              className={inputClass}
            >
              <option value="">Velg medlem …</option>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.member_reference} – {m.full_name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Beløp (kr)</span>
          <input
            inputMode="decimal"
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="1500.00"
            className={inputClass}
          />
        </label>
        <DateField
          label="Valørdato"
          value={valueDate}
          onChange={setValueDate}
          hint="Standard: i dag"
        />
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
