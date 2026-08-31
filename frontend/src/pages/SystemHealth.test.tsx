import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, setSession } from "../test/handlers";
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
