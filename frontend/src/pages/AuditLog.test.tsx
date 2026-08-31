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
    const { user } = renderApp(<AppRouter />, { route: "/revisjonslogg" });

    expect(await screen.findByText("Member row")).toBeInTheDocument();
    expect(screen.getByText("Ledger row")).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText("Objekttype"),
      "ledger_transaction",
    );

    expect(await screen.findByText("Ledger row")).toBeInTheDocument();
    expect(screen.queryByText("Member row")).not.toBeInTheDocument();
  });

  it("opens a detail panel with before/after, ip and user-agent on row click", async () => {
    setSession(ADMIN_USER);
    seedAuditEvent({
      summary: "Renamed member",
      detail: { before: { name: "Kari" }, after: { name: "Kari N" } },
      ip: "10.0.0.9",
      user_agent: "Firefox/1",
    });
    const { user } = renderApp(<AppRouter />, { route: "/revisjonslogg" });

    await user.click(await screen.findByText("Renamed member"));

    expect(await screen.findByText(/Hendelse #/)).toBeInTheDocument();
    expect(screen.getByText("10.0.0.9")).toBeInTheDocument();
    expect(screen.getByText("Firefox/1")).toBeInTheDocument();
    expect(screen.getByText(/"after"/)).toBeInTheDocument();
  });

  it("offers a CSV export link", async () => {
    setSession(ADMIN_USER);
    seedAuditEvent({ summary: "Any row" });
    renderApp(<AppRouter />, { route: "/revisjonslogg" });

    const link = await screen.findByRole("link", { name: "Eksporter CSV" });
    expect(link).toHaveAttribute("href", expect.stringContaining("/api/audit-events/export.csv"));
  });

  it("paginates when there are more than one page of events", async () => {
    setSession(ADMIN_USER);
    for (let i = 0; i < 51; i += 1) seedAuditEvent({ summary: `Event ${i}` });
    const { user } = renderApp(<AppRouter />, { route: "/revisjonslogg" });

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
    renderApp(<AppRouter />, { route: "/revisjonslogg" });
    expect(
      await screen.findByRole("link", { name: /min konto/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Revisjonslogg" }),
    ).not.toBeInTheDocument();
  });
});
