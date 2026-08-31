import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, seedLedgerTxn, seedMember, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("MemberDetail (admin)", () => {
  it("records a status change and renders the new timeline entry", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 42, member_reference: "M-42", status: "active" });
    const { user } = renderApp(<AppRouter />, { route: "/members/42" });

    await screen.findByRole("heading", { name: "Status" });

    await user.selectOptions(screen.getByLabelText("Ny status"), "inactive");
    await user.type(screen.getByLabelText("Notat"), "Flyttet ut");
    await user.click(screen.getByRole("button", { name: "Endre status" }));

    expect(await screen.findByText(/Flyttet ut/)).toBeInTheDocument();
  });

  it("surfaces a 422 status_unchanged message", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 44, status: "active" });
    const { user } = renderApp(<AppRouter />, { route: "/members/44" });

    await screen.findByRole("heading", { name: "Status" });
    await user.selectOptions(screen.getByLabelText("Ny status"), "active");
    await user.click(screen.getByRole("button", { name: "Endre status" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /already has that status/i,
    );
  });

  it("creates a login for a member that has none", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 60, member_reference: "M-60", full_name: "Radia Perlman" });
    const { user } = renderApp(<AppRouter />, { route: "/members/60" });

    const card = (
      await screen.findByRole("heading", { name: "Pålogging" })
    ).closest("div")!;
    await user.click(screen.getByRole("button", { name: "Opprett pålogging" }));

    await user.type(
      await screen.findByLabelText("E-post"),
      "radia@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await within(card).findByText("radia@example.com")).toBeInTheDocument();
    expect(within(card).getByText("Aktiv")).toBeInTheDocument();
  });

  it("records a refund and shows the new balance movement", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 70, member_reference: "M-70" });
    seedLedgerTxn(70, {
      txn_type: "payment",
      amount_ore: 100000,
      amount_nok: "1000.00",
    });
    const { user } = renderApp(<AppRouter />, { route: "/members/70" });

    await user.click(await screen.findByRole("button", { name: "Refusjon" }));
    await user.type(await screen.findByLabelText("Beløp (kr)"), "250.00");
    await user.click(screen.getByRole("button", { name: "Bokfør refusjon" }));

    expect(await screen.findByText(/750,00\s?kr/)).toBeInTheDocument();
    expect(screen.getAllByText("Refusjon").length).toBeGreaterThan(1);
  });

  it("records a charging-access warning", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 71, member_reference: "M-71" });
    const { user } = renderApp(<AppRouter />, { route: "/members/71" });

    const heading = await screen.findByRole("heading", { name: "Ladetilgang" });
    const card = heading.closest("div")!;
    await user.type(within(card).getByLabelText("Årsak (valgfritt)"), "ubetalt saldo");
    await user.click(within(card).getByRole("button", { name: "Send varsel" }));

    expect(await within(card).findByText(/Varslet ·/)).toBeInTheDocument();
    expect(within(card).getByText(/Nåværende status:/)).toHaveTextContent("Varslet");
  });

  it("runs a departure check and processes the departure", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 72, member_reference: "M-72" });
    const { user } = renderApp(<AppRouter />, { route: "/members/72" });

    const heading = await screen.findByRole("heading", { name: "Utmelding" });
    const card = heading.closest("div")!;
    await user.click(within(card).getByRole("button", { name: "Sjekk utmelding" }));
    await user.click(await within(card).findByRole("button", { name: "Meld ut" }));

    expect(await within(card).findByText(/Utmeldt/)).toBeInTheDocument();
  });

  it("persists a participation change in the re-rendered history", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 43, participates: true });
    const { user } = renderApp(<AppRouter />, { route: "/members/43" });

    await screen.findByRole("heading", { name: "Deltakelse i avregning" });

    await user.selectOptions(screen.getByLabelText("Deltakelse"), "no");
    await user.type(screen.getByLabelText("Begrunnelse"), "Sluttet å lade");
    await user.click(screen.getByRole("button", { name: "Oppdater deltakelse" }));

    const entry = await screen.findByText(/Sluttet å lade/);
    expect(entry).toBeInTheDocument();
    expect(entry.closest("li")).toHaveTextContent("Deltar ikke");
  });
});
