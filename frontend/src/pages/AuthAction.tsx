import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, consumeMagicLink, consumePasswordReset } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** Handles the two token-in-URL flows:
 *  - `/auth/magic-link?token=…`  → consume, then land signed in
 *  - `/auth/reset?token=…`       → show a new-password form
 */
export default function AuthAction({ mode }: { mode: "magic-link" | "reset" }) {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (mode !== "magic-link" || !token) return;
    let cancelled = false;
    (async () => {
      try {
        await consumeMagicLink(token);
        await refresh();
        if (!cancelled) navigate("/", { replace: true });
      } catch (err) {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : "Lenken er ugyldig.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, token, navigate, refresh]);

  if (user && mode === "magic-link") return <Navigate to="/" replace />;

  async function submitReset(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await consumePasswordReset(token, password);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Kunne ikke tilbakestille passord.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm space-y-4 rounded-lg border border-slate-800 bg-slate-900/60 p-6 text-sm text-slate-200">
        {mode === "magic-link" ? (
          <p role="status">{error ?? "Logger inn …"}</p>
        ) : done ? (
          <>
            <p role="status">Passordet er endret. Du kan logge inn nå.</p>
            <button
              type="button"
              onClick={() => navigate("/login", { replace: true })}
              className="rounded-md bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950"
            >
              Til innlogging
            </button>
          </>
        ) : (
          <form onSubmit={submitReset} className="space-y-3">
            <h1 className="text-base font-semibold">Velg nytt passord</h1>
            <label className="block">
              <span className="mb-1 block text-slate-400">Nytt passord (min. 10 tegn)</span>
              <input
                type="password"
                required
                minLength={10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100"
              />
            </label>
            {error && <p className="text-rose-400">{error}</p>}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-md bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950 disabled:opacity-60"
            >
              Lagre passord
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
