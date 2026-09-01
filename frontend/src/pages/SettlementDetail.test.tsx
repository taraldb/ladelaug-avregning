import { screen, waitFor, within } from "@testing-library/react";
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
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });

    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));

    // now on the detail page
    await screen.findByRole("heading", { name: /Avregning 20/ });

    await user.type(screen.getByLabelText(/Beskrivelse/), "Fastledd");
    await user.click(screen.getByRole("button", { name: "Likt" }));
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
    expect(
      await screen.findByRole("link", { name: "faktura-1.pdf" }),
    ).toHaveAttribute("href", expect.stringMatching(/\/attachments\/\d+$/));

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

  it("defaults to Forbruk, adds a line, then edits it to a negative Likt line", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });
    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));
    await screen.findByRole("heading", { name: /Avregning 20/ });

    const linesPanel = (
      await screen.findByRole("heading", { name: "Fakturalinjer" })
    ).closest("div")!;

    // "Forbruk" is the pre-selected option on the segmented toggle
    expect(
      within(linesPanel).getByRole("button", { name: "Forbruk" }),
    ).toHaveAttribute("aria-pressed", "true");

    await user.type(within(linesPanel).getByLabelText(/Beskrivelse/), "Strøm");
    await user.type(within(linesPanel).getByLabelText(/Beløp/), "1200");
    await user.click(within(linesPanel).getByRole("button", { name: "Legg til" }));

    const row = (await within(linesPanel).findByText("Strøm")).closest("tr")!;
    expect(within(row).getByText("Forbruk")).toBeInTheDocument();
    expect(within(row).getByText(/1\s?200,00\s?kr/)).toBeInTheDocument();

    // edit — flip to "Likt" and set a negative (credit) amount
    await user.click(within(row).getByRole("button", { name: "Endre" }));
    const editForm = await within(linesPanel).findByRole("form", {
      name: /Endre linje Strøm/,
    });
    await user.click(within(editForm).getByRole("button", { name: "Likt" }));
    const amountField = within(editForm).getByLabelText(/Beløp/);
    await user.clear(amountField);
    await user.type(amountField, "-150");
    await user.click(within(editForm).getByRole("button", { name: "Lagre" }));

    const editedRow = (
      await within(linesPanel).findByText("Strøm")
    ).closest("tr")!;
    expect(within(editedRow).getByText("Likt")).toBeInTheDocument();
    expect(within(editedRow).getByText(/-150,00\s?kr/)).toBeInTheDocument();
  });

  it("returns focus to Beskrivelse after adding a line", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });
    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));
    await screen.findByRole("heading", { name: /Avregning 20/ });

    const linesPanel = (
      await screen.findByRole("heading", { name: "Fakturalinjer" })
    ).closest("div")!;
    const description = within(linesPanel).getByLabelText(/Beskrivelse/);

    await user.type(description, "Fastledd");
    await user.type(within(linesPanel).getByLabelText(/Beløp/), "500");
    await user.click(within(linesPanel).getByRole("button", { name: "Legg til" }));

    await within(linesPanel).findByText("Fastledd");
    // form cleared and the cursor is back in Beskrivelse for the next line
    expect(description).toHaveValue("");
    expect(description).toHaveFocus();
  });

  it("assesses and books a correction on a posted settlement", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });
    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));
    await screen.findByRole("heading", { name: /Avregning 20/ });

    await user.type(screen.getByLabelText(/Beskrivelse/), "Fastledd");
    await user.type(screen.getByLabelText(/Beløp/), "500");
    await user.click(screen.getByRole("button", { name: "Legg til" }));
    await user.type(screen.getByLabelText(/Fakturert kWh/), "10");
    await user.click(screen.getByRole("button", { name: "Lagre" }));
    const file = new File([new Uint8Array([1, 2, 3])], "faktura.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText("Fakturavedlegg"), file);
    await user.click(screen.getByRole("button", { name: "Last opp" }));
    await screen.findByRole("link", { name: "faktura-1.pdf" });
    await user.click(screen.getByRole("button", { name: "Frys forbruk" }));
    await user.click(await screen.findByRole("button", { name: "Bokfør" }));
    await screen.findByText(/Bokført\./);

    const heading = await screen.findByRole("heading", { name: "Korrigering" });
    const panel = heading.closest("div")!.parentElement as HTMLElement;
    await user.click(within(panel).getByRole("button", { name: "Vurder korrigering" }));
    expect(await within(panel).findByText(/Member Seven/)).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Bokfør korrigering" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Bokfør" }));

    expect(await screen.findByText(/Korrigering #1 bokført/)).toBeInTheDocument();
  });

  it("uploads several invoices and deletes one after confirming", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });
    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));
    await screen.findByRole("heading", { name: /Avregning 20/ });

    const mk = (name: string) =>
      new File([new Uint8Array([1, 2, 3])], name, { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Fakturavedlegg"), [
      mk("faktura-1.pdf"),
      mk("faktura-2.pdf"),
    ]);
    await user.click(screen.getByRole("button", { name: "Last opp" }));

    expect(await screen.findByRole("link", { name: "faktura-1.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "faktura-2.pdf" })).toBeInTheDocument();

    // delete the first — a confirm dialog gates it
    const row1 = screen.getByRole("link", { name: "faktura-1.pdf" }).closest("li")!;
    await user.click(within(row1).getByRole("button", { name: "Slett" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("faktura-1.pdf");
    await user.click(within(dialog).getByRole("button", { name: "Slett vedlegg" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: "faktura-1.pdf" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "faktura-2.pdf" })).toBeInTheDocument();
  });

  it("re-queues the report emails from a posted settlement", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });
    await user.click(await screen.findByRole("button", { name: "Opprett utkast" }));
    await screen.findByRole("heading", { name: /Avregning 20/ });

    await user.type(screen.getByLabelText(/Beskrivelse/), "Fastledd");
    await user.type(screen.getByLabelText(/Beløp/), "500");
    await user.click(screen.getByRole("button", { name: "Legg til" }));
    await user.type(screen.getByLabelText(/Fakturert kWh/), "10");
    await user.click(screen.getByRole("button", { name: "Lagre" }));
    const file = new File([new Uint8Array([1, 2, 3])], "faktura.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText("Fakturavedlegg"), file);
    await user.click(screen.getByRole("button", { name: "Last opp" }));
    await screen.findByRole("link", { name: "faktura-1.pdf" });
    await user.click(screen.getByRole("button", { name: "Frys forbruk" }));
    await user.click(await screen.findByRole("button", { name: "Bokfør" }));
    await screen.findByRole("heading", { name: "Rapporter" });

    await user.click(
      screen.getByRole("button", { name: "Send rapport-e-post på nytt" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Legg i kø" }));

    expect(await screen.findByText(/2 e-poster lagt i kø/)).toBeInTheDocument();
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
    const { user } = renderApp(<AppRouter />, { route: "/avregninger" });

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
