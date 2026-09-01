import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ROUTES } from "../routes";
import { ADMIN_USER, MEMBER_USER, seedMember, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

const memberId = MEMBER_USER.member_id ?? 7;

describe("MyProfile (member self-service)", () => {
  it("prefills the form and saves name + email changes", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: memberId, full_name: "Kari Hansen", email: "kari@example.com" });

    const { user } = renderApp(<AppRouter />, { route: ROUTES.profile });

    const name = await screen.findByLabelText("Navn");
    expect(name).toHaveValue("Kari Hansen");
    const email = screen.getByLabelText(/e-post/i);
    expect(email).toHaveValue("kari@example.com");

    await user.clear(name);
    await user.type(name, "Kari Nordmann");
    await user.clear(email);
    await user.type(email, "kari.n@example.com");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    expect(await screen.findByText("Endringene er lagret.")).toBeInTheDocument();
  });

  it("rejects a blank (whitespace-only) name", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: memberId, full_name: "Kari Hansen" });

    const { user } = renderApp(<AppRouter />, { route: ROUTES.profile });

    const name = await screen.findByLabelText("Navn");
    await user.clear(name);
    await user.type(name, "   ");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Navn kan ikke være tomt.",
    );
  });

  it("blocks a password change when the two fields differ", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: memberId });

    const { user } = renderApp(<AppRouter />, { route: ROUTES.profile });

    await user.type(
      await screen.findByLabelText(/Nytt passord/),
      "a-strong-secret-1",
    );
    await user.type(screen.getByLabelText(/Gjenta/), "a-different-secret-1");
    await user.click(screen.getByRole("button", { name: "Endre passord" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Passordene er ikke like.",
    );
  });

  it("blocks a password shorter than 10 characters", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: memberId });

    const { user } = renderApp(<AppRouter />, { route: ROUTES.profile });

    await user.type(await screen.findByLabelText(/Nytt passord/), "short");
    await user.type(screen.getByLabelText(/Gjenta/), "short");
    await user.click(screen.getByRole("button", { name: "Endre passord" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Passordet må ha minst 10 tegn.",
    );
  });

  it("changes the password and clears the fields on success", async () => {
    setSession(MEMBER_USER);
    seedMember({ id: memberId });

    const { user } = renderApp(<AppRouter />, { route: ROUTES.profile });

    const pw = await screen.findByLabelText(/Nytt passord/);
    const pw2 = screen.getByLabelText(/Gjenta/);
    await user.type(pw, "a-brand-new-secret-2026");
    await user.type(pw2, "a-brand-new-secret-2026");
    await user.click(screen.getByRole("button", { name: "Endre passord" }));

    expect(
      await screen.findByText("Passordet er endret. Andre enheter er logget ut."),
    ).toBeInTheDocument();
    expect(pw).toHaveValue("");
    expect(pw2).toHaveValue("");
  });

  it("tells a pure admin the account has no linked member", async () => {
    setSession(ADMIN_USER);

    renderApp(<AppRouter />, { route: ROUTES.profile });

    expect(
      await screen.findByText("Denne kontoen er ikke knyttet til et medlem."),
    ).toBeInTheDocument();
  });
});
