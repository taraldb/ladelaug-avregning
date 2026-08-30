import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

describe("SystemHealth (admin)", () => {
  it("shows health tiles and can drain the email queue", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/system" });

    expect(await screen.findByText("OK")).toBeInTheDocument();
    expect(screen.getByText("0.2.0")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Send e-postkø" }));
    expect(await screen.findByText(/Sending av e-post fullført\./)).toBeInTheDocument();
  });
});
