import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedAccessStatus,
  seedConsumption,
  seedForecast,
  seedLedgerTxn,
  seedLowBalanceForecast,
  seedMember,
  seedMyHistory,
  seedMySettlement,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("MyAccount (member portal)", () => {
  it("renders balance and ledger from /api/me/*", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId, status: "active", participates: true });
    seedLedgerTxn(memberId, {
      txn_type: "payment",
      amount_ore: 150000,
      amount_nok: "1500.00",
    });

    renderApp(<AppRouter />, { route: "/" });

    expect(await screen.findByText(/kr\s?1\s?500,00/)).toBeInTheDocument();
    expect(screen.getByText("Innbetaling")).toBeInTheDocument();
    expect(screen.getByText(/Deltar i avregning:/)).toHaveTextContent("Ja");
  });

  it("lists settlements with report and PDF links (invoices only inside the report)", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });
    const s = seedMySettlement({ period_month: "2026-07" });

    renderApp(<AppRouter />, { route: "/" });

    expect(await screen.findByText(/2026-07/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rapport" })).toHaveAttribute(
      "href",
      s.report_url,
    );
    expect(screen.getByRole("link", { name: "PDF" })).toBeInTheDocument();
    // the invoice itself is not surfaced here — only via the report page
    expect(screen.queryByRole("link", { name: /Faktura/ })).not.toBeInTheDocument();
  });

  it("renders the forecast and consumption cards, no banner when balance is fine", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });
    seedForecast(memberId, {
      forecast_kwh: "120.5",
      forecast_monthly_cost_ore: 47293,
      recommended_minimum_ore: 94586,
      recommended_topup_ore: 0,
    });
    seedConsumption(memberId, {
      month: "2026-08",
      consumption_kwh: "42.75",
      session_count: 6,
    });

    renderApp(<AppRouter />, { route: "/" });

    expect(
      await screen.findByRole("heading", { name: "Prognose neste måned" }),
    ).toBeInTheDocument();
    expect(screen.getByText("120.5 kWh")).toBeInTheDocument();
    expect(screen.getByText(/kr\s?472,93/)).toBeInTheDocument();
    expect(screen.getByText(/kr\s?945,86/)).toBeInTheDocument();
    expect(
      screen.getByText("2026-08: 42.75 kWh over 6 ladeøkter."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders the usage/cost history table newest-first with a hover tooltip", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });
    seedMyHistory(memberId, [
      { month: "2026-06", consumption_kwh: "30.00", session_count: 3 },
      {
        month: "2026-07",
        consumption_kwh: "50.00",
        session_count: 4,
        settled: true,
        charge_nok: "123.45",
        charge_ore: 12345,
        balance_end_nok: "250.00",
        balance_end_ore: 25000,
      },
      { month: "2026-08", consumption_kwh: "10.00", session_count: 1 },
    ]);

    const { container } = renderApp(<AppRouter />, { route: "/" });

    const settled = (await screen.findByText("2026-07")).closest("tr")!;
    expect(within(settled).getByText(/kr\s?123,45/)).toBeInTheDocument();

    const unsettled = screen.getByText("2026-08").closest("tr")!;
    expect(within(unsettled).getByText("–")).toBeInTheDocument();
    expect(within(unsettled).getByText("10.00")).toBeInTheDocument();

    // table is sorted newest month first
    const table = settled.closest("table")!;
    const bodyRows = within(table).getAllByRole("row").slice(1); // drop header
    expect(bodyRows.map((r) => within(r).getByText(/2026-0\d/).textContent)).toEqual([
      "2026-08",
      "2026-07",
      "2026-06",
    ]);

    // hovering a month in the combined chart reveals its numbers
    const col = container.querySelector('rect[data-month="2026-08"]')!;
    fireEvent.mouseEnter(col);
    expect(await screen.findByText("ikke avregnet")).toBeInTheDocument();
    expect(screen.getByText(/10\.00 kWh · 1 økter/)).toBeInTheDocument();
  });

  it("shows a low-balance banner for a below-minimum forecast", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });
    seedLowBalanceForecast(memberId, "critical");

    renderApp(<AppRouter />, { route: "/" });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Lav saldo");
    expect(banner).toHaveTextContent(/Anbefalt innbetaling nå:/);
    expect(banner.className).toContain("rose");
  });

  it("shows the neutral no-forecast message when history is thin", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });

    renderApp(<AppRouter />, { route: "/" });

    expect(
      await screen.findByText(/Ikke nok historikk til å lage en prognose ennå\./),
    ).toBeInTheDocument();
  });

  it("shows a charging-access banner with a Zaptec portal link", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });
    seedAccessStatus("disabled");

    renderApp(<AppRouter />, { route: "/" });

    const alert = await screen.findByText("Ladetilgang stengt");
    expect(alert).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Åpne Zaptec-portalen" }),
    ).toHaveAttribute("href", "https://portal.zaptec.com");
  });

  it("sends an admin who lands on the root to the members list", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/" });

    expect(
      await screen.findByRole("heading", { name: /medlemmer/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /min konto/i }),
    ).not.toBeInTheDocument();
  });

  it("does not show a My-account nav link for an admin", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1 });
    renderApp(<AppRouter />, { route: "/medlemmer" });

    await screen.findByRole("heading", { name: /medlemmer/i });
    expect(
      screen.queryByRole("link", { name: /min konto/i }),
    ).not.toBeInTheDocument();
  });
});
