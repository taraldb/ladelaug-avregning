import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  changeMyPassword,
  getMyMember,
  updateMyProfile,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ROUTES } from "../routes";

const field =
  "w-full max-w-sm rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100";
const isForbidden = (err: unknown) => err instanceof ApiError && err.status === 403;

export default function MyProfile() {
  const member = useSWR("/api/me", () => getMyMember());
  const { user, refresh } = useAuth();
  const viewingAs = user?.view_as ?? null;

  const [form, setForm] = useState<{ full_name: string; email: string } | null>(
    null,
  );
  const [profileMsg, setProfileMsg] = useState<string | null>(null);
  const [profileErr, setProfileErr] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);

  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [savingPw, setSavingPw] = useState(false);

  useEffect(() => {
    if (member.data && form === null) {
      setForm({
        full_name: member.data.full_name,
        email: member.data.email ?? "",
      });
    }
  }, [member.data, form]);

  if (member.error && isForbidden(member.error)) {
    return (
      <section className="space-y-3">
        <h1 className="text-lg font-semibold text-slate-100">Min profil</h1>
        <p className="text-sm text-slate-400">
          Denne kontoen er ikke knyttet til et medlem.
        </p>
      </section>
    );
  }

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    if (!form || viewingAs) return;
    setProfileMsg(null);
    setProfileErr(null);
    const name = form.full_name.trim();
    if (!name) {
      setProfileErr("Navn kan ikke være tomt.");
      return;
    }
    setSavingProfile(true);
    try {
      await updateMyProfile({
        full_name: name,
        email: form.email.trim() || null,
      });
      await Promise.all([member.mutate(), refresh()]);
      setProfileMsg("Endringene er lagret.");
    } catch (err) {
      setProfileErr(err instanceof ApiError ? err.message : "Kunne ikke lagre.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function savePassword(e: FormEvent) {
    e.preventDefault();
    if (viewingAs) return;
    setPwMsg(null);
    setPwErr(null);
    if (pw.length < 10) {
      setPwErr("Passordet må ha minst 10 tegn.");
      return;
    }
    if (pw !== pw2) {
      setPwErr("Passordene er ikke like.");
      return;
    }
    setSavingPw(true);
    try {
      await changeMyPassword(pw);
      setPw("");
      setPw2("");
      setPwMsg("Passordet er endret. Andre enheter er logget ut.");
    } catch (err) {
      setPwErr(err instanceof ApiError ? err.message : "Kunne ikke endre passord.");
    } finally {
      setSavingPw(false);
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Min profil</h1>
        <Link
          to={ROUTES.home}
          className="text-sm text-emerald-400 hover:underline"
        >
          Til Min konto
        </Link>
      </div>

      {viewingAs && (
        <p
          role="alert"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100"
        >
          Du ser profilen til <strong>{viewingAs.member_name}</strong> —
          skrivebeskyttet. Endringer er deaktivert mens du ser portalen som et
          medlem.
        </p>
      )}

      <div className="rounded-lg border border-slate-800 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">
          Kontaktinformasjon
        </h2>
        {form ? (
          <form onSubmit={saveProfile} className="space-y-3 text-sm">
            <label className="block">
              <span className="mb-1 block text-slate-400">Navn</span>
              <input
                required
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                className={field}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-slate-400">Reserve-e-post</span>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className={field}
              />
            </label>
            <p className="text-xs text-slate-500">
              Avregninger og varsler sendes til påloggings-e-posten din. Reserve-e-posten
              brukes bare hvis påloggingen mangler eller er deaktivert. Andelsnummer og
              innmeldingsdato endres av styret.
            </p>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={savingProfile || !!viewingAs}
                className="rounded-md bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
              >
                Lagre
              </button>
              {profileMsg && <span className="text-emerald-400">{profileMsg}</span>}
              {profileErr && (
                <span role="alert" className="text-rose-400">
                  {profileErr}
                </span>
              )}
            </div>
          </form>
        ) : (
          <p className="text-sm text-slate-400">Laster …</p>
        )}
      </div>

      <div className="rounded-lg border border-slate-800 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Endre passord</h2>
        <form onSubmit={savePassword} className="space-y-3 text-sm">
          <label className="block">
            <span className="mb-1 block text-slate-400">
              Nytt passord (min. 10 tegn)
            </span>
            <input
              type="password"
              autoComplete="new-password"
              required
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              className={field}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-slate-400">Gjenta nytt passord</span>
            <input
              type="password"
              autoComplete="new-password"
              required
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
              className={field}
            />
          </label>
          <p className="text-xs text-slate-500">
            Når du bytter passord, blir du logget ut på alle andre enheter.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={savingPw || !!viewingAs}
              className="rounded-md bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              Endre passord
            </button>
            {pwMsg && <span className="text-emerald-400">{pwMsg}</span>}
            {pwErr && (
              <span role="alert" className="text-rose-400">
                {pwErr}
              </span>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}
