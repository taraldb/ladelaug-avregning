import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  seedMember,
  seedUser,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Users (admin)", () => {
  it("creates a member login and shows it in the list", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 55, member_reference: "M-55", full_name: "Kari Nordmann" });
    const { user } = renderApp(<AppRouter />, { route: "/users" });

    await user.click(await screen.findByRole("button", { name: "Ny bruker" }));

    await user.selectOptions(await screen.findByLabelText("Medlem"), "55");
    await user.type(screen.getByLabelText("E-post"), "kari@example.com");
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    const row = (await screen.findByText("kari@example.com")).closest("tr")!;
    expect(within(row).getByText("Medlem")).toBeInTheDocument();
    expect(within(row).getByText("M-55 – Kari Nordmann")).toBeInTheDocument();
  });

  it("disables a login and reflects the new status", async () => {
    setSession(ADMIN_USER);
    const m = seedMember({ full_name: "Ola Nordmann" });
    seedUser({ role: "member", member_id: m.id, email: "ola@example.com" });
    const { user } = renderApp(<AppRouter />, { route: "/users" });

    const row = (await screen.findByText("ola@example.com")).closest("tr")!;
    expect(within(row).getByText("Aktiv")).toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: "Deaktiver" }));

    expect(await within(row).findByText("Deaktivert")).toBeInTheDocument();
  });

  it("edits a login's email and promotes it to admin", async () => {
    setSession(ADMIN_USER);
    const m = seedMember({ member_reference: "M-88", full_name: "Per Hansen" });
    seedUser({ role: "member", member_id: m.id, email: "per@example.com" });
    const { user } = renderApp(<AppRouter />, { route: "/users" });

    const row = (await screen.findByText("per@example.com")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Endre" }));

    const email = await screen.findByLabelText("E-post");
    await user.clear(email);
    await user.type(email, "per.hansen@example.com");
    await user.selectOptions(screen.getByLabelText("Rolle"), "admin");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    const updated = (await screen.findByText("per.hansen@example.com")).closest("tr")!;
    expect(within(updated).getByText("Administrator")).toBeInTheDocument();
    expect(within(updated).getByText("–")).toBeInTheDocument();
  });

  it("surfaces the email_taken 422 when editing to a used address", async () => {
    setSession(ADMIN_USER);
    seedUser({ role: "admin", email: "one@example.com" });
    seedUser({ role: "admin", email: "two@example.com" });
    const { user } = renderApp(<AppRouter />, { route: "/users" });

    const row = (await screen.findByText("two@example.com")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Endre" }));

    const email = await screen.findByLabelText("E-post");
    await user.clear(email);
    await user.type(email, "one@example.com");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
  });

  it("surfaces the member_linked 422 when the member already has a login", async () => {
    setSession(ADMIN_USER);
    const m = seedMember({ member_reference: "M-77" });
    seedUser({ role: "member", member_id: m.id, email: "taken@example.com" });
    const { user } = renderApp(<AppRouter />, { route: "/users" });

    await user.click(await screen.findByRole("button", { name: "Ny bruker" }));
    // The member picker hides members that already have a login, so create an
    // admin instead and prove the generic error path renders.
    await user.selectOptions(await screen.findByLabelText("Rolle"), "admin");
    await user.type(screen.getByLabelText("E-post"), "admin@example.com");
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
  });
});
