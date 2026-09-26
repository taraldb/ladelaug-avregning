import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedCharger,
  seedMember,
  seedUnassigned,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Chargers (admin)", () => {
  it("creates a charger and lists it", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/ladere" });

    await user.click(await screen.findByRole("button", { name: "Ny lader" }));
    await user.type(screen.getByLabelText(/^Navn$/), "Garasje 1");
    await user.type(screen.getByLabelText(/Serienummer/), "ZAP-001");
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await screen.findByText("Garasje 1")).toBeInTheDocument();
    expect(screen.getByText("ZAP-001")).toBeInTheDocument();
  });

  it("edits a charger row", async () => {
    setSession(ADMIN_USER);
    seedCharger({ name: "Gammelt navn", serial_no: "S-1" });
    const { user } = renderApp(<AppRouter />, { route: "/ladere" });

    await user.click(await screen.findByRole("button", { name: "Rediger" }));
    const nameField = screen.getByLabelText(/^Navn$/);
    await user.clear(nameField);
    await user.type(nameField, "Nytt navn");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    expect(await screen.findByText("Nytt navn")).toBeInTheDocument();
    expect(screen.queryByText("Gammelt navn")).not.toBeInTheDocument();
  });

  it("deletes a manual charger", async () => {
    setSession(ADMIN_USER);
    seedCharger({ name: "Duplikat" });
    const { user } = renderApp(<AppRouter />, { route: "/ladere" });

    await user.click(await screen.findByRole("button", { name: "Slett" }));
    // Deleting now goes through the app's own ConfirmModal, not window.confirm.
    const dialog = await screen.findByRole("dialog", { name: "Slett lader" });
    await user.click(within(dialog).getByRole("button", { name: "Slett" }));
    expect(await screen.findByText("Ingen ladere ennå")).toBeInTheDocument();
  });

  it("shows no Slett button for a Zaptec charger", async () => {
    setSession(ADMIN_USER);
    seedCharger({ name: "Zap", zaptec_id: "z-1" });
    renderApp(<AppRouter />, { route: "/ladere" });

    expect(await screen.findByText("Zap")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Slett" })).not.toBeInTheDocument();
  });

  it("shows no Slett button when the charger has usage", async () => {
    setSession(ADMIN_USER);
    seedCharger({ name: "Brukt", has_usage: true });
    renderApp(<AppRouter />, { route: "/ladere" });

    expect(await screen.findByText("Brukt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Slett" })).not.toBeInTheDocument();
  });

  it("shows the unassigned-consumption banner and re-runs allocation", async () => {
    setSession(ADMIN_USER);
    const month = new Date().toISOString().slice(0, 7);
    seedCharger({ name: "C1", zaptec_id: "z-1" });
    seedUnassigned(month, [
      {
        charger_zaptec_id: "z-1",
        charger_id: 1,
        charger_name: "C1",
        sessions: 3,
        energy_kwh: "12.500",
      },
    ]);
    const { user } = renderApp(<AppRouter />, { route: "/ladere" });

    expect(
      await screen.findByText(/12\.500 kWh i .* er ikke fordelt/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Kjør ny fordeling" }));
    expect(
      await screen.findByText(/Ny fordeling kjørt: 1 økt/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/er ikke fordelt/)).not.toBeInTheDocument();
  });

  it("is not reachable for a member session", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: MEMBER_USER.member_id ?? 7 });
    renderApp(<AppRouter />, { route: "/ladere" });
    expect(
      await screen.findByRole("link", { name: /min konto/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ny lader" })).not.toBeInTheDocument();
  });
});
