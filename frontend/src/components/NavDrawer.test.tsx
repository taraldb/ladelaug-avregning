import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("NavDrawer (mobile nav)", () => {
  beforeEach(() => setSession(ADMIN_USER));

  it("opens on the menu button and lists every admin destination", async () => {
    const user = userEvent.setup();
    renderApp(<AppRouter />, { route: "/medlemmer" });

    const toggle = await screen.findByRole("button", { name: "Meny" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const drawer = screen.getByRole("dialog", { name: "Meny" });
    for (const label of [
      "Medlemmer",
      "Forbruk",
      "Avregninger",
      "Bevegelser",
      "Revisjonslogg",
      "Prognose",
      "System",
    ]) {
      expect(within(drawer).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(within(drawer).getByRole("button", { name: "Logg ut" })).toBeInTheDocument();
  });

  it("closes again on Escape", async () => {
    const user = userEvent.setup();
    renderApp(<AppRouter />, { route: "/medlemmer" });

    await user.click(await screen.findByRole("button", { name: "Meny" }));
    expect(screen.getByRole("dialog", { name: "Meny" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Meny" })).not.toBeInTheDocument();
  });

  it("navigates and closes when a link is tapped", async () => {
    const user = userEvent.setup();
    renderApp(<AppRouter />, { route: "/medlemmer" });

    await user.click(await screen.findByRole("button", { name: "Meny" }));
    const drawer = screen.getByRole("dialog", { name: "Meny" });
    await user.click(within(drawer).getByRole("link", { name: "Avregninger" }));

    expect(await screen.findByRole("heading", { name: "Avregninger" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Meny" })).not.toBeInTheDocument();
  });

  it("keeps exactly one node per nav label while closed", async () => {
    renderApp(<AppRouter />, { route: "/medlemmer" });
    expect(await screen.findAllByRole("link", { name: "Medlemmer" })).toHaveLength(1);
  });
});
