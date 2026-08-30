import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { TEST_PASSWORD } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Login", () => {
  it("signs in and lands on the admin shell", async () => {
    const { user } = renderApp(<AppRouter />, { route: "/login" });

    await user.type(await screen.findByLabelText(/e-post/i), "admin@example.com");
    await user.type(screen.getByLabelText(/passord/i), TEST_PASSWORD);
    await user.click(screen.getByRole("button", { name: /logg inn/i }));

    expect(
      await screen.findByRole("link", { name: /medlemmer/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /logg inn/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the server error message on bad credentials", async () => {
    const { user } = renderApp(<AppRouter />, { route: "/login" });

    await user.type(await screen.findByLabelText(/e-post/i), "admin@example.com");
    await user.type(screen.getByLabelText(/passord/i), "wrong");
    await user.click(screen.getByRole("button", { name: /logg inn/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /invalid email or password/i,
    );
  });
});
