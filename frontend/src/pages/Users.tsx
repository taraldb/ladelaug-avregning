import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  createUser,
  listMembers,
  listUsers,
  setUserDisabled,
  setUserPassword,
  updateUser,
  type Member,
  type User,
} from "../api/client";
import Modal from "../components/Modal";
import Table, { type Column } from "../components/Table";

const inputClass =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none";
const primaryBtn =
  "rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60";
const secondaryBtn =
  "rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800";

function memberLabel(m: Member | undefined): string {
  return m ? `${m.member_reference} – ${m.full_name}` : "–";
}

export default function Users() {
  const users = useSWR("/api/users", () => listUsers());
  const members = useSWR("/api/members", () => listMembers());
  const [open, setOpen] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [pwUser, setPwUser] = useState<User | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const memberById = new Map(
    (members.data?.members ?? []).map((m) => [m.id, m]),
  );

  async function toggleDisabled(u: User) {
    setError(null);
    setBusyId(u.id);
    try {
      await setUserDisabled(u.id, !u.disabled);
      await users.mutate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke oppdatere.");
    } finally {
      setBusyId(null);
    }
  }

  const columns: Column<User>[] = [
    { key: "email", header: "E-post", render: (u) => u.email },
    {
      key: "role",
      header: "Rolle",
      render: (u) => (u.role === "admin" ? "Administrator" : "Medlem"),
    },
    {
      key: "member",
      header: "Medlem",
      render: (u) =>
        u.member_id == null ? "–" : memberLabel(memberById.get(u.member_id)),
    },
    {
      key: "status",
      header: "Status",
      render: (u) =>
        u.disabled ? (
          <span className="text-rose-400">Deaktivert</span>
        ) : (
          <span className="text-emerald-400">Aktiv</span>
        ),
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (u) => (
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setEditUser(u)}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            Endre
          </button>
          <button
            type="button"
            onClick={() => setPwUser(u)}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            Nytt passord
          </button>
          <button
            type="button"
            disabled={busyId === u.id}
            onClick={() => void toggleDisabled(u)}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-60"
          >
            {u.disabled ? "Aktiver" : "Deaktiver"}
          </button>
        </div>
      ),
    },
  ];

  return (
    <section className="space-y-4">
      <Link to="/system" className="text-xs text-emerald-400 hover:underline">
        ← System
      </Link>
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Brukere</h1>
        <button type="button" onClick={() => setOpen(true)} className={primaryBtn}>
          Ny bruker
        </button>
      </div>

      {(error || users.error) && (
        <p role="alert" className="text-sm text-rose-400">
          {error ??
            `Kunne ikke laste brukere: ${(users.error as ApiError).message}`}
        </p>
      )}

      <Table
        columns={columns}
        rows={users.data?.users ?? []}
        rowKey={(u) => u.id}
        empty={users.isLoading ? "Laster …" : "Ingen brukere"}
      />

      <NewUserModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={async () => {
          await users.mutate();
          setOpen(false);
        }}
      />
      <EditUserModal
        user={editUser}
        onClose={() => setEditUser(null)}
        onSaved={async () => {
          await users.mutate();
          setEditUser(null);
        }}
      />
      <SetPasswordModal
        user={pwUser}
        onClose={() => setPwUser(null)}
        onDone={() => setPwUser(null)}
      />
    </section>
  );
}

export function NewUserModal({
  open,
  onClose,
  onCreated,
  lockedMember,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  /** When set, the form creates a member login for exactly this member. */
  lockedMember?: { id: number; label: string };
}) {
  const users = useSWR(open ? "/api/users" : null, () => listUsers());
  const members = useSWR(
    open && !lockedMember ? "/api/members" : null,
    () => listMembers(),
  );

  const [role, setRole] = useState<"admin" | "member">("member");
  const [email, setEmail] = useState("");
  const [memberId, setMemberId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const effectiveRole = lockedMember ? "member" : role;

  function reset() {
    setRole("member");
    setEmail("");
    setMemberId("");
    setPassword("");
    setError(null);
    setSaving(false);
  }

  function close() {
    reset();
    onClose();
  }

  const linkedMemberIds = new Set(
    (users.data?.users ?? [])
      .map((u) => u.member_id)
      .filter((v): v is number => v != null),
  );
  const availableMembers = (members.data?.members ?? []).filter(
    (m) => !linkedMemberIds.has(m.id),
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await createUser({
        email: email.trim(),
        password: password.trim() || null,
        role: effectiveRole,
        member_id:
          effectiveRole === "member"
            ? (lockedMember?.id ?? Number(memberId))
            : undefined,
      });
      reset();
      await onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke opprette bruker.");
      setSaving(false);
    }
  }

  const canSubmit =
    email.trim() !== "" &&
    (effectiveRole === "admin" || lockedMember != null || memberId !== "");

  return (
    <Modal
      open={open}
      title="Ny bruker"
      onClose={close}
      footer={
        <>
          <button type="button" onClick={close} className={secondaryBtn}>
            Avbryt
          </button>
          <button
            type="submit"
            form="new-user-form"
            disabled={saving || !canSubmit}
            className={primaryBtn}
          >
            Opprett
          </button>
        </>
      }
    >
      <form id="new-user-form" className="space-y-3" onSubmit={onSubmit}>
        {lockedMember ? (
          <p className="text-sm text-slate-400">
            Pålogging for medlem <span className="text-slate-200">{lockedMember.label}</span>.
          </p>
        ) : (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-300">Rolle</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "member")}
              className={inputClass}
            >
              <option value="member">Medlem</option>
              <option value="admin">Administrator</option>
            </select>
          </label>
        )}

        {effectiveRole === "member" && !lockedMember && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-300">Medlem</span>
            <select
              required
              value={memberId}
              onChange={(e) => setMemberId(e.target.value)}
              className={inputClass}
            >
              <option value="">Velg medlem …</option>
              {availableMembers.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.member_reference} – {m.full_name}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">E-post</span>
          <input
            type="text"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Passord (valgfritt)
          </span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Tomt = brukeren aktiverer selv via innloggingslenke / «Glemt passord?».
            Minst 10 tegn hvis satt.
          </span>
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

export function EditUserModal({
  user,
  onClose,
  onSaved,
}: {
  user: User | null;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const open = user != null;
  const users = useSWR(open ? "/api/users" : null, () => listUsers());
  const members = useSWR(open ? "/api/members" : null, () => listMembers());

  const [role, setRole] = useState<"admin" | "member">("member");
  const [email, setEmail] = useState("");
  const [memberId, setMemberId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    setRole(user.role);
    setEmail(user.email);
    setMemberId(user.member_id == null ? "" : String(user.member_id));
    setError(null);
    setSaving(false);
  }, [user]);

  function close() {
    setError(null);
    setSaving(false);
    onClose();
  }

  // Members already tied to a different login are not selectable; the user's
  // own current member stays in the list.
  const linkedElsewhere = new Set(
    (users.data?.users ?? [])
      .filter((u) => u.id !== user?.id)
      .map((u) => u.member_id)
      .filter((v): v is number => v != null),
  );
  const availableMembers = (members.data?.members ?? []).filter(
    (m) => !linkedElsewhere.has(m.id),
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    setError(null);
    setSaving(true);
    try {
      await updateUser(user.id, {
        email: email.trim(),
        role,
        member_id: role === "member" ? Number(memberId) : null,
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke lagre bruker.");
      setSaving(false);
    }
  }

  const canSubmit =
    email.trim() !== "" && (role === "admin" || memberId !== "");

  return (
    <Modal
      open={open}
      title={user ? `Endre bruker – ${user.email}` : "Endre bruker"}
      onClose={close}
      footer={
        <>
          <button type="button" onClick={close} className={secondaryBtn}>
            Avbryt
          </button>
          <button
            type="submit"
            form="edit-user-form"
            disabled={saving || !canSubmit}
            className={primaryBtn}
          >
            Lagre
          </button>
        </>
      }
    >
      <form id="edit-user-form" className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">Rolle</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as "admin" | "member")}
            className={inputClass}
          >
            <option value="member">Medlem</option>
            <option value="admin">Administrator</option>
          </select>
        </label>

        {role === "member" && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-300">Medlem</span>
            <select
              required
              value={memberId}
              onChange={(e) => setMemberId(e.target.value)}
              className={inputClass}
            >
              <option value="">Velg medlem …</option>
              {availableMembers.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.member_reference} – {m.full_name}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">E-post</span>
          <input
            type="text"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
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

export function SetPasswordModal({
  user,
  onClose,
  onDone,
}: {
  user: User | null;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function close() {
    setPassword("");
    setError(null);
    setSaving(false);
    onClose();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    setError(null);
    setSaving(true);
    try {
      await setUserPassword(user.id, password);
      setPassword("");
      setSaving(false);
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kunne ikke sette passord.");
      setSaving(false);
    }
  }

  return (
    <Modal
      open={user != null}
      title={user ? `Nytt passord – ${user.email}` : "Nytt passord"}
      onClose={close}
      footer={
        <>
          <button type="button" onClick={close} className={secondaryBtn}>
            Avbryt
          </button>
          <button
            type="submit"
            form="set-password-form"
            disabled={saving || password.length < 10}
            className={primaryBtn}
          >
            Lagre
          </button>
        </>
      }
    >
      <form id="set-password-form" className="space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-300">
            Nytt passord (minst 10 tegn)
          </span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
