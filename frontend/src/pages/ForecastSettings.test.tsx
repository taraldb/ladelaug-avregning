import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedForecast,
  seedLowBalanceForecast,
  seedMember,
  server,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("ForecastSettings (admin)", () => {
  it("saves the changed settings via PUT /api/forecast/settings", async () => {
    setSession(ADMIN_USER);
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.put("/api/forecast/settings", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          rate_override_ore_per_kwh: sent.rate_override_ore_per_kwh ?? null,
          buffer_months: sent.buffer_months ?? 2,
          notify_cooldown_days: sent.notify_cooldown_days ?? 14,
          lookback_settlements: sent.lookback_settlements ?? 3,
          updated_at: "2026-08-30T12:00:00Z",
          updated_by_user_id: 1,
        });
      }),
    );

    const { user } = renderApp(<AppRouter />, { route: "/forecast" });

    const buffer = await screen.findByLabelText("Buffermåneder");
    await user.clear(buffer);
    await user.type(buffer, "3");
    await user.type(screen.getByLabelText(/Overstyrt sats/), "210");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    expect(await screen.findByText("Innstillinger lagret.")).toBeInTheDocument();
    expect(sent).toMatchObject({
      buffer_months: 3,
      rate_override_ore_per_kwh: 210,
      notify_cooldown_days: 14,
      lookback_settlements: 3,
    });
  });

  it("runs the low-balance scan and renders the returned counts", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 7, full_name: "Member Seven", member_reference: "M-7" });
    seedForecast(7);
    seedMember({ id: 8, full_name: "Member Eight", member_reference: "M-8" });
    seedLowBalanceForecast(8, "low");

    const { user } = renderApp(<AppRouter />, { route: "/forecast" });

    await user.click(
      await screen.findByRole("button", { name: "Kjør lavsaldo-varsling nå" }),
    );

    expect(
      await screen.findByText(
        "2 skannet · 1 under minimum · 1 lagt i kø · 0 undertrykt",
      ),
    ).toBeInTheDocument();
  });

  it("redirects a member session away from /forecast", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: MEMBER_USER.member_id ?? 7 });

    renderApp(<AppRouter />, { route: "/forecast" });

    expect(
      await screen.findByRole("link", { name: /min konto/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Kjør lavsaldo-varsling nå" }),
    ).not.toBeInTheDocument();
  });
});
