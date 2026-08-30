import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  createMember,
  listMembers,
  type Member,
} from "../api/client";
import DateField from "../components/DateField";
import Modal from "../components/Modal";
import Table, { type Column } from "../components/Table";
import { formatDate } from "../lib/format";

const columns: Column<Member>[] = [
  { key: "ref", header: "Referanse", render: (m) => m.member_reference },
  { key: "name", header: "Navn", render: (m) => m.full_name },
  { key: "email", header: "E-post", render: (m) => m.email ?? "–" },
  {
    key: "join",
    header: "Innmeldt",
    render: (m) => formatDate(m.join_date),
  },
  {
    key: "status",
    header: "Status",
    render: (m) => (m.status === "active" ? "Aktiv" : m.status === "inactive" ? "Inaktiv" : "–"),
  },
  {
    key: "participates",
    header: "Deltar",
    render: (m) =>
      m.participates == null ? "–" : m.participates ? "Ja" : "Nei",
  },
];

export default function Members() {
  const { data, error, isLoading, mutate } = useSWR("/api/members", () =>
    listMembers(),
  );
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Medlemmer</h1>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
        >
          Nytt medlem
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-400">
          Kunne ikke laste medlemmer: {(error as ApiError).message}
        </p>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-400">Laster …</p>
      ) : (
        <Table
          columns={columns}
          rows={data?.members ?? []}
          rowKey={(m) => m.id}
          onRowClick={(m) => navigate(`/members/${m.id}`)}
          empty="Ingen medlemmer ennå"
        />
      )}

      <NewMemberModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={async () => {
          await mutate();
          setOpen(false);
        }}
      />
    </section>
  );
}

function NewMemberModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}) {
  const [reference, setReference] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [joinDate, setJoinDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function reset() {
    setReference("");
    setFullName("");
    setEmail("");
    setJoinDate(new Date().toISOString().slice(0, 10));
    setError(null);
    setSubmitting(false);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await createMember({
        member_reference: reference.trim(),
        full_name: fullName.trim(),
        email: email.trim() || undefined,
        join_date: joinDate,
      });
      reset();
      await onCreated();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Kunne ikke opprette medlem.",
      );
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Nytt medlem"
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
            form="new-member-form"
            disabled={submitting}
            className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            Opprett
          </button>
        </>
      }
    >
      <form id="new-member-form" className="space-y-3" onSubmit={onSubmit}>
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
          <span className="mb-1 block font-medium text-slate-300">Fullt navn</span>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            E-post (valgfritt)
          </span>
          <input
            type="text"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
          />
        </label>
        <DateField label="Innmeldingsdato" value={joinDate} onChange={setJoinDate} required />

        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
