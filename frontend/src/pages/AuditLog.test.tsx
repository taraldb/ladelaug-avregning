import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, seedAuditEvent, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("AuditLog (admin)", () => {
  it("lists events and filters by entity type", async () => {
    setSession(ADMIN_USER);
    seedAuditEvent({ entity_type: "member", summary: "Member row" });
    seedAuditEvent({ entity_type: "ledger_transaction", summary: "Ledger row" });
    const { user } = renderApp(<AppRouter />, { route: "/audit" });

    expect(await screen.findByText("Member row")).toBeInTheDocument();
    expect(screen.getByText("Ledger row")).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText("Objekttype"),
      "ledger_transaction",
    );

    expect(await screen.findByText("Ledger row")).toBeInTheDocument();
    expect(screen.queryByText("Member row")).not.toBeInTheDocument();
  });

  it("paginates when there are more than one page of events", async () => {
    setSession(ADMIN_USER);
    for (let i = 0; i < 51; i += 1) seedAuditEvent({ summary: `Event ${i}` });
    const { user } = renderApp(<AppRouter />, { route: "/audit" });

    await screen.findByText(/51 hendelser/);
    expect(screen.getByText("Side 1 av 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Neste" }));
    expect(await screen.findByText("Side 2 av 2")).toBeInTheDocument();
  });

  it("keeps a member session out", async () => {
    setSession({
      id: 9,
      email: "m@example.com",
      role: "member",
      member_id: 3,
      disabled: false,
    });
    renderApp(<AppRouter />, { route: "/audit" });
    expect(
      await screen.findByRole("link", { name: /min konto/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Revisjonslogg" }),
    ).not.toBeInTheDocument();
  });
});
