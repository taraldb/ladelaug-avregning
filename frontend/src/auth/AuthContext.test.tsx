import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("AuthProvider + route guards", () => {
  it("shows Login when /api/auth/me is 401", async () => {
    renderApp(<AppRouter />, { route: "/" });

    expect(
      await screen.findByRole("button", { name: /logg inn/i }),
    ).toBeInTheDocument();
  });

  it("renders the app shell when a session exists", async () => {
    setSession(ADMIN_USER);
    renderApp(<AppRouter />, { route: "/" });

    expect(
      await screen.findByRole("link", { name: /medlemmer/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /logg inn/i }),
    ).not.toBeInTheDocument();
  });
});
