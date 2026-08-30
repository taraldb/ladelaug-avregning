import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedLedgerTxn,
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
