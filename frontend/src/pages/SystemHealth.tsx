import { useState } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import {
  ApiError,
  listJobs,
  listNotifications,
  processNotifications,
  requeueNotification,
  runJob,
  syncSessions,
  systemHealth,
  updateJob,
  type JobSchedule,
} from "../api/client";
import StatTile from "../components/StatTile";
import { formatDateTime } from "../lib/format";

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

const JOB_LABELS: Record<string, string> = {
  drain_mail: "Send e-postkø",
  low_balance_scan: "Lavsaldo-varsling",
  zaptec_sync_sessions: "Zaptec-import (ladeøkter)",
};

function JobsCard() {
  const jobs = useSWR("/api/system/jobs", () => listJobs());
  const [cronDraft, setCronDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setErr(null);
    try {
      await fn();
      await jobs.mutate();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Handlingen feilet.");
    } finally {
      setBusy(null);
    }
  }

  const rows = jobs.data?.jobs ?? [];

  return (
    <div className="rounded-lg border border-slate-800 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-200">Bakgrunnsjobber</h2>
      <p className="mb-3 text-xs text-slate-500">
        Kjøres av serveren selv når planleggeren er på (config: <code>scheduler.enabled</code>).
        Bomma kjøringer tas ikke igjen – neste kjøring gjør jobben uansett.
      </p>
      {jobs.error && (
        <p role="alert" className="text-sm text-rose-400">
          {(jobs.error as ApiError).message}
        </p>
      )}
      {err && (
        <p role="alert" className="text-sm text-rose-400">
          {err}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-400">
            <tr>
              <th className="py-1 pr-3">Jobb</th>
              <th className="py-1 pr-3">På</th>
              <th className="py-1 pr-3">Cron (UTC)</th>
              <th className="py-1 pr-3">Sist</th>
              <th className="py-1 pr-3">Neste</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {rows.map((job: JobSchedule) => {
              const draft = cronDraft[job.name] ?? job.cron;
              const cronDirty = draft !== job.cron;
              return (
                <tr key={job.name} className="border-t border-slate-800 align-top">
                  <td className="py-2 pr-3 text-slate-200">
                    {JOB_LABELS[job.name] ?? job.name}
                    {job.last_status === "error" && job.last_error && (
                      <span
                        className="ml-1 text-rose-400"
                        title={job.last_error}
                      >
                        ⚠
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <input
                      type="checkbox"
                      aria-label={`${JOB_LABELS[job.name] ?? job.name} på`}
                      checked={job.enabled}
                      disabled={busy === job.name}
                      onChange={(e) =>
                        void act(job.name, () =>
                          updateJob(job.name, { enabled: e.target.checked }),
                        )
                      }
                    />
                  </td>
                  <td className="py-2 pr-3">
                    <input
                      value={draft}
                      onChange={(e) =>
                        setCronDraft({ ...cronDraft, [job.name]: e.target.value })
                      }
                      className="w-32 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100"
                    />
                    {cronDirty && (
                      <button
                        type="button"
                        disabled={busy === job.name}
                        onClick={() =>
                          void act(job.name, async () => {
                            await updateJob(job.name, { cron: draft });
                            setCronDraft((d) => {
                              const next = { ...d };
                              delete next[job.name];
                              return next;
                            });
                          })
                        }
                        className="ml-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                      >
                        Lagre
                      </button>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-400">
                    {job.last_run_at ? (
                      <span
                        className={
                          job.last_status === "error" ? "text-rose-400" : undefined
                        }
                      >
                        {formatDateTime(job.last_run_at)} · {job.last_status}
                      </span>
                    ) : (
                      "–"
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-400">
                    {job.enabled && job.next_run_at
                      ? formatDateTime(job.next_run_at)
                      : "–"}
                  </td>
                  <td className="py-2">
                    <button
                      type="button"
                      disabled={busy === job.name}
                      onClick={() =>
                        void act(job.name, () => runJob(job.name))
                      }
                      className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                    >
                      Kjør nå
                    </button>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && !jobs.error && (
              <tr>
                <td colSpan={6} className="py-2 text-slate-500">
                  Laster …
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
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
          <StatTile
            label="Korrigeringer venter"
            value={h.corrections.settlements_with_pending}
            sub="bokførte avregninger med endret forbruk"
            tone={h.corrections.settlements_with_pending > 0 ? "negative" : "neutral"}
          />
          <StatTile
            label="Ladetilgang stengt"
            value={h.access.disabled}
            sub="medlemmer"
            tone={h.access.disabled > 0 ? "negative" : "neutral"}
          />
        </div>
      )}

      <JobsCard />

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
              {m.status === "failed" && (
                <button
                  type="button"
                  onClick={() =>
                    void run(() => requeueNotification(m.id), "Legg e-post i kø igjen")
                  }
                  className="ml-2 rounded border border-slate-700 px-1.5 py-0.5 text-xs text-slate-200 hover:bg-slate-800"
                >
                  Legg i kø igjen
                </button>
              )}
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
