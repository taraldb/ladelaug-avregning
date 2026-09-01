import useSWR from "swr";
import {
  ApiError,
  getMyAccess,
  getMyBalance,
  getMyConsumption,
  getMyForecast,
  getMyHistory,
  getMyLedger,
  getMySettlements,
  getMyStatus,
  type LedgerTxn,
} from "../api/client";
import Money from "../components/Money";
import StatTile from "../components/StatTile";
import Table, { type Column } from "../components/Table";
import UsageHistoryChart from "../components/UsageHistoryChart";
import { formatDate, formatNok, formatOre, txnTypeLabel } from "../lib/format";

const columns: Column<LedgerTxn>[] = [
  { key: "date", header: "Valørdato", render: (t) => formatDate(t.value_date) },
  { key: "type", header: "Type", render: (t) => txnTypeLabel(t.txn_type) },
  {
    key: "amount",
    header: "Beløp",
    className: "text-right tabular-nums",
    render: (t) => (
      <Money
        value={t.amount_nok}
        className={t.amount_ore < 0 ? "text-rose-400" : "text-emerald-400"}
      />
    ),
  },
  {
    key: "detail",
    header: "Detaljer",
    render: (t) => t.reason ?? t.reference ?? "–",
  },
];

const isForbidden = (err: unknown) => err instanceof ApiError && err.status === 403;

export default function MyAccount() {
  const balance = useSWR("/api/me/balance", () => getMyBalance());
  const ledger = useSWR("/api/me/ledger", () => getMyLedger());
  const status = useSWR("/api/me/status", () => getMyStatus());
  const settlements = useSWR("/api/me/settlements", () => getMySettlements());
  const forecast = useSWR("/api/me/forecast", () => getMyForecast());
  const consumption = useSWR("/api/me/consumption", () => getMyConsumption());
  const history = useSWR("/api/me/history", () => getMyHistory(6));
  const access = useSWR("/api/me/access", () => getMyAccess());

  if (
    [balance.error, ledger.error, status.error, forecast.error].some(isForbidden)
  ) {
    return (
      <section className="space-y-3">
        <h1 className="text-lg font-semibold text-slate-100">Min konto</h1>
        <p className="text-sm text-slate-400">
          Denne kontoen er ikke knyttet til et medlem.
        </p>
      </section>
    );
  }

  const txns = ledger.data?.transactions ?? [];
  const fc = forecast.data;
  const showBanner = fc?.available && fc.low_balance;
  const acc = access.data;
  const accessBlocked = acc?.status === "warned" || acc?.status === "disabled";

  return (
    <section className="space-y-6">
      <h1 className="text-lg font-semibold text-slate-100">Min konto</h1>

      {accessBlocked && (
        <div
          role="alert"
          className={`rounded-lg border p-4 text-sm ${
            acc.status === "disabled"
              ? "border-rose-500/50 bg-rose-500/10 text-rose-200"
              : "border-amber-500/50 bg-amber-500/10 text-amber-200"
          }`}
        >
          <p className="font-semibold">
            {acc.status === "disabled" ? "Ladetilgang stengt" : "Varsel om ladetilgang"}
          </p>
          <p className="mt-1">
            {acc.status === "disabled"
              ? "Ladetilgangen din er merket som stengt. Ta kontakt med styret."
              : "Ladetilgangen din kan bli stengt. Ta kontakt med styret."}{" "}
            <a
              className="underline"
              href={acc.portal_url}
              target="_blank"
              rel="noreferrer"
            >
              Åpne Zaptec-portalen
            </a>
          </p>
        </div>
      )}

      {showBanner && (
        <div
          role="alert"
          className={`rounded-lg border p-4 text-sm ${
            fc.severity === "critical"
              ? "border-rose-500/50 bg-rose-500/10 text-rose-200"
              : "border-amber-500/50 bg-amber-500/10 text-amber-200"
          }`}
        >
          <p className="font-semibold">Lav saldo</p>
          <p className="mt-1">
            Anbefalt innbetaling nå:{" "}
            <strong>{formatOre(fc.recommended_topup_ore)}</strong>. Fyll på saldo
            for å dekke neste avregning.
          </p>
        </div>
      )}

      <StatTile
        label="Saldo"
        value={balance.data ? formatNok(balance.data.balance_nok) : "…"}
        tone={balance.data && balance.data.balance_ore < 0 ? "negative" : "positive"}
      />

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">
          Prognose neste måned
        </h2>
        {fc?.available ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Forventet forbruk" value={`${fc.forecast_kwh} kWh`} />
            <StatTile
              label="Estimert månedskostnad"
              value={formatOre(fc.forecast_monthly_cost_ore)}
            />
            <StatTile
              label="Anbefalt minstesaldo"
              value={formatOre(fc.recommended_minimum_ore)}
            />
            <StatTile
              label="Anbefalt innbetaling"
              value={formatOre(fc.recommended_topup_ore)}
              tone={fc.recommended_topup_ore > 0 ? "negative" : "positive"}
            />
          </div>
        ) : (
          <p className="text-sm text-slate-400">
            {forecast.isLoading
              ? "Laster …"
              : "Ikke nok historikk til å lage en prognose ennå."}
          </p>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">
          Forbruk og kostnad
        </h2>
        {consumption.data && (
          <p className="mb-3 text-sm text-slate-300">
            {`${consumption.data.month}: ${consumption.data.consumption_kwh} kWh over ${consumption.data.session_count} ladeøkter.`}
          </p>
        )}
        {history.data ? (
          <UsageHistoryChart months={history.data.months} />
        ) : (
          <p className="text-sm text-slate-400">Laster …</p>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">Min historikk</h2>
        <Table
          columns={columns}
          rows={txns}
          rowKey={(t) => t.id}
          empty="Ingen transaksjoner"
        />
      </div>

      {(settlements.data?.settlements.filter((s) => s.is_draft) ?? []).length > 0 && (
        <div
          role="region"
          aria-label="Utkast til avregning"
          className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-4"
        >
          <h2 className="mb-1 text-sm font-semibold text-amber-200">
            Utkast til avregning
          </h2>
          <p className="mb-3 text-sm text-amber-200/90">
            Dette er et <strong>utkast</strong>. Tallene er ikke endelige og kan endres
            før avregningen bokføres. Du blir varslet når den endelige avregningen er
            klar.
          </p>
          <ul className="space-y-1 text-sm text-amber-100">
            {settlements.data!.settlements
              .filter((s) => s.is_draft)
              .map((s) => (
                <li
                  key={s.settlement_id}
                  className="flex flex-wrap justify-between gap-2 border-b border-amber-500/20 py-1"
                >
                  <span>
                    <span className="mr-2 rounded bg-amber-500/30 px-1.5 py-0.5 text-xs font-semibold text-amber-100">
                      UTKAST
                    </span>
                    {s.period_month} · {s.consumption_kwh} kWh · foreløpig belastet{" "}
                    {formatNok(s.charge_nok)}
                  </span>
                  <span className="flex gap-3">
                    <a
                      className="text-amber-200 underline hover:text-amber-100"
                      href={s.report_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Se utkast
                    </a>
                    <a
                      className="text-amber-200 underline hover:text-amber-100"
                      href={`${s.report_url}.pdf`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      PDF
                    </a>
                  </span>
                </li>
              ))}
          </ul>
        </div>
      )}

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">Avregninger</h2>
        {(() => {
          const final = settlements.data?.settlements.filter((s) => !s.is_draft) ?? [];
          return final.length > 0 ? (
            <ul className="space-y-1 text-sm text-slate-300">
              {final.map((s) => (
                <li key={s.settlement_id} className="flex justify-between border-b border-slate-800 py-1">
                  <span>
                    {s.period_month} · {s.consumption_kwh} kWh · belastet {formatNok(s.charge_nok)}
                  </span>
                  <span className="flex gap-3">
                    <a
                      className="text-emerald-400 hover:underline"
                      href={s.report_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Rapport
                    </a>
                    <a
                      className="text-emerald-400 hover:underline"
                      href={`${s.report_url}.pdf`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      PDF
                    </a>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">Ingen avregninger ennå.</p>
          );
        })()}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-100">Min status</h2>
        {status.data ? (
          <div className="space-y-1 text-sm text-slate-300">
            <p>
              Status:{" "}
              <span className="text-slate-100">
                {status.data.status === "active"
                  ? "Aktiv"
                  : status.data.status === "inactive"
                    ? "Inaktiv"
                    : "–"}
              </span>
            </p>
            <p>
              Deltar i avregning:{" "}
              <span className="text-slate-100">
                {status.data.participates == null
                  ? "–"
                  : status.data.participates
                    ? "Ja"
                    : "Nei"}
              </span>
            </p>
            <ol className="mt-2 space-y-1">
              {status.data.history.map((p) => (
                <li
                  key={p.id}
                  className="border-l-2 border-slate-700 pl-3 text-slate-400"
                >
                  {p.status === "active" ? "Aktiv" : "Inaktiv"} ·{" "}
                  {formatDate(p.effective_from)} –{" "}
                  {p.effective_to ? formatDate(p.effective_to) : "løpende"}
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="text-sm text-slate-400">Laster …</p>
        )}
      </div>
    </section>
  );
}
