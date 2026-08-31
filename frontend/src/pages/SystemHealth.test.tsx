import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, server, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("SystemHealth (admin)", () => {
  it("shows health tiles and can drain the email queue", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/system" });

    expect(await screen.findByText("OK")).toBeInTheDocument();
    expect(screen.getByText("0.2.0")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Send e-postkø" }));
    expect(await screen.findByText(/Sending av e-post fullført\./)).toBeInTheDocument();
  });

  it("puts a failed email back on the queue", async () => {
    setSession(ADMIN_USER);
    let requeued: string | null = null;
    server.use(
      http.get("/api/notifications", () =>
        HttpResponse.json({
          stats: { queued: 0, sent: 1, failed: 1, next_attempt_at: null },
          messages: [
            {
              id: 42,
              to_address: "kari@example.test",
              subject: "Avregning 2026-07",
              template: "settlement_report",
              status: "failed",
              attempts: 5,
              max_attempts: 5,
              last_error: "smtp timeout",
              next_attempt_at: "2026-08-31T00:00:00+00:00",
              created_at: "2026-08-01T00:00:00+00:00",
              sent_at: null,
            },
          ],
        }),
      ),
      http.post("/api/notifications/:id/requeue", ({ params }) => {
        requeued = String(params.id);
        return HttpResponse.json({ message: { id: Number(params.id), status: "queued" } });
      }),
    );

    const { user } = renderApp(<AppRouter />, { route: "/system" });

    const row = (await screen.findByText("smtp timeout", { exact: false })).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "Legg i kø igjen" }));

    expect(await screen.findByText(/Legg e-post i kø igjen fullført\./)).toBeInTheDocument();
    expect(requeued).toBe("42");
  });

  it("lists the background jobs and can enable one", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/system" });

    expect(await screen.findByText("Bakgrunnsjobber")).toBeInTheDocument();
    const toggle = await screen.findByLabelText("Send e-postkø på");
    expect(toggle).not.toBeChecked();

    await user.click(toggle);
    expect(await screen.findByLabelText("Send e-postkø på")).toBeChecked();
  });

  it("can run a background job on demand", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/system" });

    const runButtons = await screen.findAllByRole("button", { name: "Kjør nå" });
    await user.click(runButtons[0]);
    expect(await screen.findByText(/· ok/)).toBeInTheDocument();
  });

  it("shows the correction and access counters", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/system" });

    expect(
      await screen.findByText("Korrigeringer venter"),
    ).toBeInTheDocument();
    expect(screen.getByText("Ladetilgang stengt")).toBeInTheDocument();
  });

  it("links to the user and charger config pages", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/system" });

    const users = await screen.findByRole("link", { name: "Brukerkontoer" });
    expect(users).toHaveAttribute("href", "/users");
    expect(screen.getByRole("link", { name: "Ladere" })).toHaveAttribute(
      "href",
      "/chargers",
    );
  });

  it("keeps the System nav tab active on the config pages", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/users" });

    const systemTab = await screen.findByRole("link", { name: "System" });
    expect(systemTab.className).toMatch(/bg-slate-100/);
    // Brukere/Ladere are no longer top-level nav entries
    expect(
      screen.queryByRole("link", { name: "Brukere" }),
    ).not.toBeInTheDocument();
  });
});
