import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import {
  ADMIN_USER,
  seedMember,
  seedMonthConsumption,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";

describe("Settlement flow (admin)", () => {
  it("creates a draft, adds a line, freezes, previews and posts", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/settlements" });

    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));

    // now on the detail page
    await screen.findByRole("heading", { name: /Avregning 20/ });

    await user.type(screen.getByLabelText(/Beskrivelse/), "Fastledd");
    await user.type(screen.getByLabelText(/Beløp/), "500");
    await user.click(screen.getByRole("button", { name: "Legg til" }));
    expect(await screen.findByText("Fastledd")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Fakturert kWh/), "10");
    await user.click(screen.getByRole("button", { name: "Lagre" }));

    // attachment
    const file = new File([new Uint8Array([1, 2, 3])], "faktura.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText("Fakturavedlegg"), file);
    await user.click(screen.getByRole("button", { name: "Last opp" }));
    expect(await screen.findByText(/Lastet opp: faktura.pdf/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Frys forbruk" }));

    // report preview is available before posting, from the frozen snapshot
    expect(
      await screen.findByRole("heading", { name: "Rapporter (forhåndsvisning)" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "PDF" }).length).toBeGreaterThan(0);

    await user.click(await screen.findByRole("button", { name: "Forhåndsvis" }));

    const previewHeading = await screen.findByRole("heading", { name: "Forhåndsvisning" });
    const previewSection = previewHeading.parentElement as HTMLElement;
    expect(within(previewSection).getByText("Member Seven")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Bokfør" }));
    expect(await screen.findByText(/Bokført\./)).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Rapporter" }),
    ).toBeInTheDocument();
  });

  it("shows a live month-consumption panel on a draft", async () => {
    setSession(ADMIN_USER);
    const month = new Date().toISOString().slice(0, 7);
    const kari = seedMember({ full_name: "Kari Nordmann" });
    seedMonthConsumption(month, {
      total_kwh: "42.000",
      unassigned_kwh: "3.500",
      by_member: [{ member_id: kari.id, energy_kwh: "38.500" }],
    });
    const { user } = renderApp(<AppRouter />, { route: "/settlements" });

    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));
    await screen.findByRole("heading", { name: /Avregning 20/ });

    const heading = await screen.findByRole("heading", {
      name: `Forbruk i ${month} (foreløpig)`,
    });
    const panel = heading.parentElement?.parentElement as HTMLElement;
    expect(panel).toHaveTextContent("Totalt 42.000 kWh");
    expect(panel).toHaveTextContent("3.500 kWh ikke fordelt");
    expect(within(panel).getByText("Kari Nordmann")).toBeInTheDocument();
    expect(within(panel).getByText("38.500 kWh")).toBeInTheDocument();
  });
});
