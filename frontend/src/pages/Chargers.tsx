import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import {
  ApiError,
  assignCharger,
  createCharger,
  deleteCharger,
  listChargers,
  listMembers,
  syncChargers,
  unassignCharger,
  updateCharger,
  zaptecStatus,
  type Charger,
} from "../api/client";
import Modal from "../components/Modal";
import Table, { type Column } from "../components/Table";

export default function Chargers() {
  const chargers = useSWR("/api/chargers", () => listChargers());
  const members = useSWR("/api/members", () => listMembers());
  const zaptec = useSWR("/api/zaptec/status", () => zaptecStatus());
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Charger | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function doDelete(c: Charger) {
    if (
      !window.confirm(
        `Slette laderen «${c.name}»? Tildelingshistorikken for laderen fjernes også.`,
      )
    )
      return;
    setMsg(null);
    try {
      await deleteCharger(c.id);
      await chargers.mutate();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Kunne ikke slette laderen.");
    }
  }

  const memberName = (id: number | null) =>
    id == null
      ? "–"
      : (members.data?.members.find((m) => m.id === id)?.full_name ?? `#${id}`);

  async function doSync() {
    setMsg(null);
    try {
      const r = await syncChargers();
      setMsg(`Synk fullført: ${r.chargers_created} nye, ${r.chargers_updated} oppdatert.`);
      await chargers.mutate();
      await zaptec.mutate();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Synk feilet.");
    }
  }

  const columns: Column<Charger>[] = [
    { key: "name", header: "Navn", render: (c) => c.name },
    { key: "serial", header: "Serienr.", render: (c) => c.serial_no ?? "–" },
    {
      key: "zaptec",
      header: "Zaptec",
      render: (c) => (c.zaptec_id ? "Ja" : "Manuell"),
    },
    { key: "member", header: "Tildelt", render: (c) => memberName(c.assigned_member_id) },
    {
      key: "actions",
      header: "",
      render: (c) => (
        <div className="flex items-center gap-3">
          <AssignCell
            charger={c}
            members={members.data?.members ?? []}
            onChange={async () => {
              await chargers.mutate();
            }}
          />
          <button
            type="button"
            onClick={() => setEditing(c)}
            className="text-xs text-slate-300 hover:text-slate-100"
          >
            Rediger
          </button>
          {c.deletable && (
            <button
              type="button"
              onClick={() => void doDelete(c)}
              className="text-xs text-rose-400 hover:text-rose-300"
            >
              Slett
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Ladere</h1>
        <div className="flex gap-2">
          {zaptec.data?.enabled && (
            <button
              type="button"
              onClick={() => void doSync()}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            >
              Synk fra Zaptec
            </button>
          )}
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
          >
            Ny lader
          </button>
        </div>
      </div>

      {msg && <p className="text-sm text-slate-300">{msg}</p>}
      {chargers.error && (
        <p role="alert" className="text-sm text-rose-400">
          Kunne ikke laste ladere: {(chargers.error as ApiError).message}
        </p>
      )}

      <Table
        columns={columns}
        rows={chargers.data?.chargers ?? []}
        rowKey={(c) => c.id}
        empty="Ingen ladere ennå"
      />

      <NewChargerModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={async () => {
          await chargers.mutate();
          setOpen(false);
        }}
      />

      <EditChargerModal
        charger={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          await chargers.mutate();
          setEditing(null);
        }}
      />
    </section>
  );
}

function AssignCell({
  charger,
  members,
  onChange,
}: {
  charger: Charger;
  members: { id: number; full_name: string }[];
  onChange: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function assign(memberId: number) {
    setErr(null);
    setBusy(true);
    try {
      await assignCharger(charger.id, { member_id: memberId });
      await onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Feil");
    } finally {
      setBusy(false);
    }
  }

  async function unassign() {
    setErr(null);
    setBusy(true);
    try {
      await unassignCharger(charger.id);
      await onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Feil");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label={`Tildel ${charger.name}`}
        disabled={busy}
        value={charger.assigned_member_id ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "") void unassign();
          else void assign(Number(v));
        }}
        className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
      >
        <option value="">— ikke tildelt —</option>
        {members.map((m) => (
          <option key={m.id} value={m.id}>
            {m.full_name}
          </option>
        ))}
      </select>
      {err && <span className="text-xs text-rose-400">{err}</span>}
    </div>
  );
}

function NewChargerModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [serial, setSerial] = useState("");
  const [zaptecId, setZaptecId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await createCharger({
        name: name.trim(),
        serial_no: serial.trim() || undefined,
        zaptec_id: zaptecId.trim() || undefined,
      });
      setName("");
      setSerial("");
      setZaptecId("");
      await onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke opprette lader.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Ny lader"
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Avbryt
          </button>
          <button
            type="submit"
            form="new-charger-form"
            disabled={submitting}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            Opprett
          </button>
        </>
      }
    >
      <form id="new-charger-form" className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Navn</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Serienummer</span>
          <input
            value={serial}
            onChange={(e) => setSerial(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Zaptec-ID (valgfritt)
          </span>
          <input
            value={zaptecId}
            onChange={(e) => setZaptecId(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
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

function EditChargerModal({
  charger,
  onClose,
  onSaved,
}: {
  charger: Charger | null;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [serial, setSerial] = useState("");
  const [deviceType, setDeviceType] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!charger) return;
    setName(charger.name);
    setSerial(charger.serial_no ?? "");
    setDeviceType(charger.device_type ?? "");
    setIsActive(charger.is_active);
    setError(null);
  }, [charger]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!charger) return;
    setError(null);
    setSubmitting(true);
    try {
      await updateCharger(charger.id, {
        name: name.trim(),
        serial_no: serial.trim() || null,
        device_type: deviceType.trim() || null,
        is_active: isActive,
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke lagre laderen.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={charger !== null}
      title={`Rediger ${charger?.name ?? ""}`}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Avbryt
          </button>
          <button
            type="submit"
            form="edit-charger-form"
            disabled={submitting}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            Lagre
          </button>
        </>
      }
    >
      <form id="edit-charger-form" className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Navn</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Serienummer</span>
          <input
            value={serial}
            onChange={(e) => setSerial(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Ladertype</span>
          <input
            value={deviceType}
            onChange={(e) => setDeviceType(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
          />
          Aktiv
        </label>
        {charger?.zaptec_id && (
          <p className="text-xs text-slate-400">
            Navn og serienummer overskrives ved neste synk fra Zaptec.
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
