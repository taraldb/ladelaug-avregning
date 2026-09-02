import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  MEMBER_USER,
  seedMember,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Forbruk (admin page)", () => {
  it("renders all four sections", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    renderApp(<AppRouter />, { route: "/forbruk" });

    expect(
      await screen.findByRole("heading", { name: "Forbruk", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Nettforbruk over tid")).toBeInTheDocument();
    expect(screen.getByText("Strømkostnad og pris")).toBeInTheDocument();
    expect(screen.getByText("Forbruk per medlem")).toBeInTheDocument();
    // The session-history section (its member filter is unique on the page).
    expect(screen.getAllByText("Ladeøkter").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Medlem")).toBeInTheDocument();
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
