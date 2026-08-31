import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError, requestMagicLink, requestPasswordReset } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ROUTES } from "../routes";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function sendLink(kind: "magic" | "reset") {
    setError(null);
    setNotice(null);
    if (!email.trim()) {
      setError("Skriv inn e-postadressen din først.");
      return;
    }
    try {
      if (kind === "magic") await requestMagicLink(email.trim());
      else await requestPasswordReset(email.trim());
      setNotice(
        "Hvis adressen finnes hos oss, har vi sendt en e-post med en lenke.",
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Noe gikk galt.");
    }
  }

  if (user) {
    // The site root decides where each role lands.
    return <Navigate to={ROUTES.home} replace />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(ROUTES.home, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Noe gikk galt. Prøv igjen.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h1 className="text-lg font-semibold text-slate-100">Ladelaug avregning</h1>
        <p className="mt-1 text-sm text-slate-400">Logg inn for å fortsette.</p>

        <form className="mt-5 space-y-4" onSubmit={onSubmit}>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-300">E-post</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-300">Passord</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none"
            />
          </label>

          {error && (
            <p
              role="alert"
              className="rounded-md border border-rose-800 bg-rose-950/50 px-3 py-2 text-sm text-rose-300"
            >
              {error}
            </p>
          )}
          {notice && (
            <p
              role="status"
              className="rounded-md border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm text-slate-200"
            >
              {notice}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-emerald-500 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            {submitting ? "Logger inn …" : "Logg inn"}
          </button>
        </form>

        <div className="mt-4 flex justify-between text-xs text-slate-400">
          <button type="button" onClick={() => void sendLink("magic")} className="hover:text-slate-200">
            Send innloggingslenke
          </button>
          <button type="button" onClick={() => void sendLink("reset")} className="hover:text-slate-200">
            Glemt passord?
          </button>
        </div>
      </div>
    </div>
  );
}
