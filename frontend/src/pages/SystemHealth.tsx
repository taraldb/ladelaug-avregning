import { useState } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  listNotifications,
  processNotifications,
  syncSessions,
  systemHealth,
} from "../api/client";
import StatTile from "../components/StatTile";

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export default function SystemHealth() {
  const health = useSWR("/api/system/health", () => systemHealth());
  const notifications = useSWR("/api/notifications", () => listNotifications());
  const [month, setMonth] = useState(thisMonth());
  const [msg, setMsg] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>, label: string) {
    setMsg(null);
    try {
      await fn();
      await Promise.all([health.mutate(), notifications.mutate()]);
      setMsg(`${label} fullført.`);
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : `${label} feilet.`);
    }
  }

  const h = health.data;

  return (
    <section className="space-y-6">
      <h1 className="text-lg font-semibold">Systemhelse</h1>
      {health.error && (
        <p role="alert" className="text-sm text-rose-400">
          {(health.error as ApiError).message}
        </p>
      )}
      {msg && <p className="text-sm text-slate-300">{msg}</p>}

      {h && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Status" value={h.ok ? "OK" : "Avvik"} tone={h.ok ? "positive" : "negative"} />
          <StatTile label="Versjon" value={h.version} sub={`skjema v${h.schema_version}`} />
          <StatTile
            label="E-post i kø"
            value={h.email.queued}
            sub={`${h.email.sent} sendt / ${h.email.failed} feilet`}
            tone={h.email.failed > 0 ? "negative" : "neutral"}
          />
          <StatTile
            label="Zaptec"
            value={h.zaptec.enabled ? "På" : "Av"}
            sub={`${h.zaptec.failed_runs} feilede synk`}
            tone={h.zaptec.failed_runs > 0 ? "negative" : "neutral"}
          />
        </div>
      )}

      <div className="rounded-lg border border-slate-800 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Konfigurasjon</h2>
        <div className="flex flex-wrap gap-2 text-sm">
          <Link
            to="/users"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
          >
            Brukerkontoer
          </Link>
          <Link
            to="/chargers"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
          >
            Ladere
          </Link>
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Handlinger</h2>
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <label>
            <span className="mb-1 block text-slate-400">Importer ladeøkter for</span>
            <input
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            />
          </label>
          <button
            type="button"
            disabled={!h?.zaptec.enabled}
            onClick={() => void run(() => syncSessions(month), "Import av ladeøkter")}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            Importer ladeøkter
          </button>
          <button
            type="button"
            onClick={() => void run(() => processNotifications(), "Sending av e-post")}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800"
          >
            Send e-postkø
          </button>
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Siste e-poster</h2>
        <ul className="space-y-1 text-sm text-slate-300">
          {(notifications.data?.messages ?? []).slice(0, 10).map((m) => (
            <li key={m.id}>
              <span className="text-slate-500">{m.status}</span> · {m.to_address} · {m.subject}
              {m.last_error && <span className="text-rose-400"> — {m.last_error}</span>}
            </li>
          ))}
          {(notifications.data?.messages.length ?? 0) === 0 && (
            <li className="text-slate-500">Ingen e-poster ennå.</li>
          )}
        </ul>
      </div>
    </section>
  );
}
