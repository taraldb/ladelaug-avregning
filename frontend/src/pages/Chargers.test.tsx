import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, MEMBER_USER, seedMember, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Chargers (admin)", () => {
  it("creates a charger and lists it", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/chargers" });

    await user.click(await screen.findByRole("button", { name: "Ny lader" }));
    await user.type(screen.getByLabelText(/^Navn$/), "Garasje 1");
    await user.type(screen.getByLabelText(/Serienummer/), "ZAP-001");
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await screen.findByText("Garasje 1")).toBeInTheDocument();
    expect(screen.getByText("ZAP-001")).toBeInTheDocument();
  });

  it("is not reachable for a member session", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: MEMBER_USER.member_id ?? 7 });
    renderApp(<AppRouter />, { route: "/chargers" });
    expect(
      await screen.findByRole("link", { name: /min konto/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ny lader" })).not.toBeInTheDocument();
  });
});
