import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, seedMember, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("MemberDetail (admin)", () => {
  it("records a status change and renders the new timeline entry", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 42, member_reference: "M-42", status: "active" });
    const { user } = renderApp(<AppRouter />, { route: "/members/42" });

    await screen.findByRole("heading", { name: "Status" });

    await user.selectOptions(screen.getByLabelText("Ny status"), "inactive");
    await user.type(screen.getByLabelText("Notat"), "Flyttet ut");
    await user.click(screen.getByRole("button", { name: "Endre status" }));

    expect(await screen.findByText(/Flyttet ut/)).toBeInTheDocument();
  });

  it("surfaces a 422 status_unchanged message", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 44, status: "active" });
    const { user } = renderApp(<AppRouter />, { route: "/members/44" });

    await screen.findByRole("heading", { name: "Status" });
    await user.selectOptions(screen.getByLabelText("Ny status"), "active");
    await user.click(screen.getByRole("button", { name: "Endre status" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /already has that status/i,
    );
  });

  it("creates a login for a member that has none", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 60, member_reference: "M-60", full_name: "Radia Perlman" });
    const { user } = renderApp(<AppRouter />, { route: "/members/60" });

    const card = (
      await screen.findByRole("heading", { name: "Pålogging" })
    ).closest("div")!;
    await user.click(screen.getByRole("button", { name: "Opprett pålogging" }));

    await user.type(
      await screen.findByLabelText("E-post"),
      "radia@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Opprett" }));

    expect(await within(card).findByText("radia@example.com")).toBeInTheDocument();
    expect(within(card).getByText("Aktiv")).toBeInTheDocument();
  });

  it("persists a participation change in the re-rendered history", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 43, participates: true });
    const { user } = renderApp(<AppRouter />, { route: "/members/43" });

    await screen.findByRole("heading", { name: "Deltakelse i avregning" });

    await user.selectOptions(screen.getByLabelText("Deltakelse"), "no");
    await user.type(screen.getByLabelText("Begrunnelse"), "Sluttet å lade");
    await user.click(screen.getByRole("button", { name: "Oppdater deltakelse" }));

    const entry = await screen.findByText(/Sluttet å lade/);
    expect(entry).toBeInTheDocument();
    expect(entry.closest("li")).toHaveTextContent("Deltar ikke");
  });
});
