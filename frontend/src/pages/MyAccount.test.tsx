import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedConsumption,
  seedForecast,
  seedLedgerTxn,
  seedLowBalanceForecast,
  seedMember,
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

    renderApp(<AppRouter />, { route: "/my-account" });

    expect(await screen.findByText(/1\s?500,00\s?kr/)).toBeInTheDocument();
    expect(screen.getByText("Innbetaling")).toBeInTheDocument();
    expect(screen.getByText(/Deltar i avregning:/)).toHaveTextContent("Ja");
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

    renderApp(<AppRouter />, { route: "/my-account" });

    expect(
      await screen.findByRole("heading", { name: "Prognose neste måned" }),
    ).toBeInTheDocument();
    expect(screen.getByText("120.5 kWh")).toBeInTheDocument();
    expect(screen.getByText(/472,93\s?kr/)).toBeInTheDocument();
    expect(screen.getByText(/945,86\s?kr/)).toBeInTheDocument();
    expect(
      screen.getByText("2026-08: 42.75 kWh over 6 ladeøkter."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a low-balance banner for a below-minimum forecast", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });
    seedLowBalanceForecast(memberId, "critical");

    renderApp(<AppRouter />, { route: "/my-account" });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Lav saldo");
    expect(banner).toHaveTextContent(/Anbefalt innbetaling nå:/);
    expect(banner.className).toContain("rose");
  });

  it("shows the neutral no-forecast message when history is thin", async () => {
    setSession(MEMBER_USER);
    const memberId = MEMBER_USER.member_id ?? 7;
    seedMember({ id: memberId });

    renderApp(<AppRouter />, { route: "/my-account" });

    expect(
      await screen.findByText(/Ikke nok historikk til å lage en prognose ennå\./),
    ).toBeInTheDocument();
  });

  it("shows an empty state for an admin with no linked member", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/my-account" });

    expect(
      await screen.findByText(/ikke knyttet til et medlem/i),
    ).toBeInTheDocument();
  });

  it("does not show a My-account nav link for an admin", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1 });
    renderApp(<AppRouter />, { route: "/members" });

    await screen.findByRole("heading", { name: /medlemmer/i });
    expect(
      screen.queryByRole("link", { name: /min konto/i }),
    ).not.toBeInTheDocument();
  });
});
