import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedMember,
  seedMonthConsumption,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Forbruk (admin page)", () => {
  it("defaults to the Oversikt view (aggregated trends only)", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    renderApp(<AppRouter />, { route: "/forbruk" });

    expect(
      await screen.findByRole("heading", { name: "Forbruk", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Nettforbruk over tid")).toBeInTheDocument();
    expect(screen.getByText("Strømkostnad og pris")).toBeInTheDocument();
    expect(screen.getByText("Kostnadsfordeling")).toBeInTheDocument();
    // Per-member sections are not mounted in this view.
    expect(screen.queryByText("Forbruk per medlem")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Medlem")).not.toBeInTheDocument();
  });

  it("swaps to the Per medlem view via the toggle", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    const { user } = renderApp(<AppRouter />, { route: "/forbruk" });

    await user.click(await screen.findByRole("button", { name: "Per medlem" }));

    expect(screen.getByText("Forbruk per medlem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Per medlem" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The session-history section and its member filter show up here.
    expect(screen.getAllByText("Ladeøkter").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Medlem")).toBeInTheDocument();
    // Aggregated trends are gone.
    expect(screen.queryByText("Nettforbruk over tid")).not.toBeInTheDocument();
    // One shared month picker drives both sub-sections, not one per component.
    expect(screen.getAllByLabelText("Måned")).toHaveLength(1);
  });

  it("shares one month picker across both per-member sections", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });
    seedMonthConsumption("2026-03", {
      total_kwh: "7.00",
      unassigned_kwh: "0",
      by_member: [{ member_id: 1, energy_kwh: "7.00" }],
    });

    const { user } = renderApp(<AppRouter />, { route: "/forbruk" });
    await user.click(await screen.findByRole("button", { name: "Per medlem" }));

    fireEvent.change(screen.getByLabelText("Måned"), {
      target: { value: "2026-03" },
    });

    // The shared picker feeds ConsumptionByMemberChart's caption.
    expect(await screen.findByText(/målt totalt i 2026-03/)).toBeInTheDocument();
  });

  it("gives Bruk over tid and Travleste timer their own independent pickers", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    renderApp(<AppRouter />, { route: "/forbruk" });

    await screen.findByText("Bruk over tid");
    await screen.findByText("Travleste timer");
    // Bruk over tid pages with arrows (no month `<input>`); only Travleste
    // timer's own picker shows up here.
    expect(screen.getAllByLabelText("Måned")).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("Måned"), {
      target: { value: "2026-03" },
    });

    // Only Travleste timer's fetch key moves — Bruk over tid is unaffected.
    expect(await screen.findByDisplayValue("2026-03")).toBeInTheDocument();
    expect(screen.getByText("Bruk over tid")).toBeInTheDocument();
  });

  it("is reachable from the admin nav", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/medlemmer" });

    const link = await screen.findByRole("link", { name: "Forbruk" });
    expect(link).toHaveAttribute("href", "/forbruk");
  });

  it("is admin-only — a member is redirected away", async () => {
    setSession(MEMBER_USER);
    renderApp(<AppRouter />, { route: "/forbruk" });

    // Redirected to the member dashboard; the admin page never mounts.
    await screen.findByText("Forbruk og kostnad");
    expect(screen.queryByText("Nettforbruk over tid")).not.toBeInTheDocument();
  });
});
