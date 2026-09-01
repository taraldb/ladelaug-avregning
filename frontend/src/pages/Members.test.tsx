import { screen, within } from "@testing-library/react";
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

describe("Members (admin)", () => {
  it("creates a member and shows it in the list", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/medlemmer" });

    await screen.findByRole("button", { name: "Nytt medlem" });
    await user.click(screen.getByRole("button", { name: "Nytt medlem" }));

    await user.type(screen.getByLabelText(/^Referanse$/), "M-100");
    await user.type(screen.getByLabelText(/Fullt navn/), "Ada Lovelace");
    await user.type(screen.getByLabelText(/E-post/), "ada@example.com");
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("M-100")).toBeInTheDocument();
    // modal closed
    expect(
      screen.queryByRole("button", { name: "Opprett" }),
    ).not.toBeInTheDocument();
  });

  it("surfaces the 422 validation message inline for an invalid email", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/medlemmer" });

    await screen.findByRole("button", { name: "Nytt medlem" });
    await user.click(screen.getByRole("button", { name: "Nytt medlem" }));

    await user.type(screen.getByLabelText(/^Referanse$/), "M-101");
    await user.type(screen.getByLabelText(/Fullt navn/), "Bad Email");
    await user.type(screen.getByLabelText(/E-post/), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/valid email/i);
    // modal stays open
    expect(screen.getByRole("button", { name: "Opprett" })).toBeInTheDocument();
  });

  it("shows the member balance and records a payment from the header", async () => {
    setSession(ADMIN_USER);
    const m = seedMember({ member_reference: "M-200", full_name: "Grace Hopper" });
    seedLedgerTxn(m.id, { txn_type: "payment", amount_ore: 120000 });
    const { user } = renderApp(<AppRouter />, { route: "/medlemmer" });

    const row = (await screen.findByText("Grace Hopper")).closest("tr")!;
    expect(within(row).getByText("kr 1 200,00")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Registrer innbetaling/ }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Medlem"), String(m.id));
    await user.type(within(dialog).getByLabelText("Beløp (kr)"), "300");
    await user.click(within(dialog).getByRole("button", { name: "Registrer" }));

    expect(await within(row).findByText("kr 1 500,00")).toBeInTheDocument();
  });

  it("redirects a member session away from /medlemmer", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: MEMBER_USER.member_id ?? 7 });
    renderApp(<AppRouter />, { route: "/medlemmer" });

    expect(
      await screen.findByRole("link", { name: /min konto/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Nytt medlem" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Ingen medlemmer ennå")).not.toBeInTheDocument();
  });
});
