import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  seedLedgerTxn,
  seedMember,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Movements (admin)", () => {
  it("lists ledger rows across members and filters by member", async () => {
    setSession(ADMIN_USER);
    const a = seedMember({ member_reference: "M-1", full_name: "Alice" });
    const b = seedMember({ member_reference: "M-2", full_name: "Bob" });
    seedLedgerTxn(a.id, { txn_type: "payment", amount_ore: 150000 });
    seedLedgerTxn(b.id, { txn_type: "adjustment_debit", amount_ore: -5000 });

    const { user } = renderApp(<AppRouter />, { route: "/bevegelser" });

    expect(
      await screen.findByRole("link", { name: "M-1 – Alice" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "M-2 – Bob" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Medlem"), String(a.id));

    expect(
      await screen.findByRole("link", { name: "M-1 – Alice" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "M-2 – Bob" }),
    ).not.toBeInTheDocument();
  });

  it("records a payment via the quick action and shows the new row", async () => {
    setSession(ADMIN_USER);
    const m = seedMember({ member_reference: "M-9", full_name: "Nina" });
    const { user } = renderApp(<AppRouter />, { route: "/bevegelser" });

    await user.click(
      await screen.findByRole("button", { name: /Registrer innbetaling/ }),
    );

    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Medlem"), String(m.id));
    // Value date is prefilled to today.
    const dateInput = within(dialog).getByLabelText(/Valørdato/) as HTMLInputElement;
    expect(dateInput.value).toBe(new Date().toISOString().slice(0, 10));
    await user.type(within(dialog).getByLabelText("Beløp (kr)"), "500");
    await user.click(within(dialog).getByRole("button", { name: "Registrer" }));

    expect(
      await screen.findByRole("link", { name: "M-9 – Nina" }),
    ).toBeInTheDocument();
    expect(screen.getByText("500,00")).toBeInTheDocument();
  });
});
