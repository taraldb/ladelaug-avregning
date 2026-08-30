import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import {
  ApiError,
  getForecastMembers,
  getForecastSettings,
  listMembers,
  runLowBalanceScan,
  updateForecastSettings,
  type ForecastSettingsUpdate,
  type LowBalanceScanResult,
  type MemberForecast,
} from "../api/client";
import Table, { type Column } from "../components/Table";
import { formatDateTime, formatOre } from "../lib/format";

interface FormState {
  rate_override_ore_per_kwh: string;
  buffer_months: string;
  notify_cooldown_days: string;
  lookback_settlements: string;
}

function parseForm(f: FormState): ForecastSettingsUpdate {
  const rate = f.rate_override_ore_per_kwh.trim();
  const rateValue = rate === "" ? null : Number(rate);
  if (rateValue !== null && (!Number.isInteger(rateValue) || rateValue <= 0)) {
    throw new Error("Overstyrt sats må være et positivt heltall (øre/kWh).");
  }
  const buffer = Number(f.buffer_months);
  if (!Number.isFinite(buffer) || buffer <= 0) {
    throw new Error("Buffermåneder må være et tall større enn 0.");
  }
  const cooldown = Number(f.notify_cooldown_days);
  if (!Number.isInteger(cooldown) || cooldown < 0) {
    throw new Error("Karensdager må være et ikke-negativt heltall.");
  }
  const lookback = Number(f.lookback_settlements);
  if (!Number.isInteger(lookback) || lookback < 1) {
    throw new Error("Antall avregninger må være minst 1.");
  }
  return {
    rate_override_ore_per_kwh: rateValue,
    buffer_months: buffer,
    notify_cooldown_days: cooldown,
    lookback_settlements: lookback,
  };
}

const numberField =
  "w-40 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100";

export default function ForecastSettings() {
  const settings = useSWR("/api/forecast/settings", () => getForecastSettings());
  const members = useSWR("/api/forecast/members", () => getForecastMembers());
  const memberList = useSWR("/api/members", () => listMembers());

  const [form, setForm] = useState<FormState | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [scan, setScan] = useState<LowBalanceScanResult | null>(null);
  const [scanErr, setScanErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    if (settings.data && form === null) {
      setForm({
        rate_override_ore_per_kwh:
          settings.data.rate_override_ore_per_kwh == null
            ? ""
            : String(settings.data.rate_override_ore_per_kwh),
        buffer_months: String(settings.data.buffer_months),
        notify_cooldown_days: String(settings.data.notify_cooldown_days),
        lookback_settlements: String(settings.data.lookback_settlements),
      });
    }
  }, [settings.data, form]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaveMsg(null);
    setSaveErr(null);
    let body: ForecastSettingsUpdate;
    try {
      body = parseForm(form);
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : "Ugyldige verdier.");
      return;
    }
    setSaving(true);
    try {
      await updateForecastSettings(body);
      await Promise.all([settings.mutate(), members.mutate()]);
      setSaveMsg("Innstillinger lagret.");
    } catch (err) {
      setSaveErr(err instanceof ApiError ? err.message : "Kunne ikke lagre.");
    } finally {
      setSaving(false);
    }
  }

  async function doScan() {
    setScanErr(null);
    setScanning(true);
    try {
      const res = await runLowBalanceScan();
      setScan(res);
      await members.mutate();
    } catch (err) {
      setScanErr(err instanceof ApiError ? err.message : "Skanning feilet.");
    } finally {
      setScanning(false);
    }
  }

  const names = new Map(
    (memberList.data?.members ?? []).map((m) => [m.id, m]),
  );

  const columns: Column<MemberForecast>[] = [
    {
      key: "member",
      header: "Medlem",
      render: (r) => {
        const m = names.get(r.member_id);
        return m ? `${m.full_name} (${m.member_reference})` : `#${r.member_id}`;
      },
    },
    {
      key: "kwh",
      header: "Prognose kWh",
      render: (r) => (r.available ? `${r.forecast_kwh} kWh` : "–"),
    },
    {
      key: "cost",
      header: "Månedskostnad",
      render: (r) => (r.available ? formatOre(r.forecast_monthly_cost_ore) : "–"),
    },
    {
      key: "balance",
      header: "Saldo",
      className: "tabular-nums",
      render: (r) => (
        <span className={r.balance_ore < 0 ? "text-rose-400" : undefined}>
          {formatOre(r.balance_ore)}
        </span>
      ),
    },
    {
      key: "min",
      header: "Anbefalt minstesaldo",
      render: (r) => (r.available ? formatOre(r.recommended_minimum_ore) : "–"),
    },
    {
      key: "badge",
      header: "Varsel",
      render: (r) => {
        if (!r.available) {
          return <span className="text-xs text-slate-500">ingen prognose</span>;
        }
        if (!r.low_balance) {
          return <span className="text-xs text-emerald-400">ok</span>;
        }
        return (
          <span
            className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
              r.severity === "critical"
                ? "bg-rose-500/20 text-rose-300"
                : "bg-amber-500/20 text-amber-300"
            }`}
          >
            {r.severity === "critical" ? "kritisk" : "lav saldo"}
          </span>
        );
      },
    },
  ];

  return (
    <section className="space-y-6">
      <h1 className="text-lg font-semibold text-slate-100">Prognose</h1>

      {settings.error && (
        <p role="alert" className="text-sm text-rose-400">
          {(settings.error as ApiError).message}
        </p>
      )}

      <div className="rounded-lg border border-slate-800 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Innstillinger</h2>
        {form ? (
          <form onSubmit={save} className="space-y-3 text-sm">
            <label className="block">
              <span className="mb-1 block text-slate-400">
                Overstyrt sats (øre/kWh) – tom for å bruke utledet sats
              </span>
              <input
                inputMode="numeric"
                value={form.rate_override_ore_per_kwh}
                onChange={(e) =>
                  setForm({ ...form, rate_override_ore_per_kwh: e.target.value })
                }
                className={numberField}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-slate-400">Buffermåneder</span>
              <input
                inputMode="decimal"
                value={form.buffer_months}
                onChange={(e) =>
                  setForm({ ...form, buffer_months: e.target.value })
                }
                className={numberField}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-slate-400">
                Karensdager mellom varsler
              </span>
              <input
                inputMode="numeric"
                value={form.notify_cooldown_days}
                onChange={(e) =>
                  setForm({ ...form, notify_cooldown_days: e.target.value })
                }
                className={numberField}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-slate-400">
                Antall avregninger i snittet
              </span>
              <input
                inputMode="numeric"
                value={form.lookback_settlements}
                onChange={(e) =>
                  setForm({ ...form, lookback_settlements: e.target.value })
                }
                className={numberField}
              />
            </label>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={saving}
                className="rounded-md bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
              >
                Lagre
              </button>
              {saveMsg && <span className="text-emerald-400">{saveMsg}</span>}
              {saveErr && (
                <span role="alert" className="text-rose-400">
                  {saveErr}
                </span>
              )}
            </div>
            {settings.data?.updated_at && (
              <p className="text-xs text-slate-500">
                Sist endret {formatDateTime(settings.data.updated_at)}
                {settings.data.updated_by_user_id != null &&
                  ` av bruker #${settings.data.updated_by_user_id}`}
              </p>
            )}
          </form>
        ) : (
          <p className="text-sm text-slate-400">Laster …</p>
        )}
      </div>

      <div className="rounded-lg border border-slate-800 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">
          Lavsaldo-varsling
        </h2>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <button
            type="button"
            onClick={() => void doScan()}
            disabled={scanning}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            Kjør lavsaldo-varsling nå
          </button>
          {scan && (
            <span className="text-slate-300">
              {`${scan.scanned} skannet · ${scan.below} under minimum · ${scan.queued} lagt i kø · ${scan.suppressed} undertrykt`}
            </span>
          )}
          {scanErr && (
            <span role="alert" className="text-rose-400">
              {scanErr}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          E-postene sendes når køen tømmes (System → Send e-postkø).
        </p>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">
          Medlemsoversikt
        </h2>
        {members.error ? (
          <p role="alert" className="text-sm text-rose-400">
            {(members.error as ApiError).message}
          </p>
        ) : (
          <Table
            columns={columns}
            rows={members.data?.members ?? []}
            rowKey={(r) => r.member_id}
            empty="Ingen medlemmer"
          />
        )}
      </div>
    </section>
  );
}
