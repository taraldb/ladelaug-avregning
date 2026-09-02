import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADMIN_USER, seedMember, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";
import SessionHistory from "./SessionHistory";

describe("SessionHistory", () => {
  it("lists sessions, joins member names, and labels unassigned rows", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    renderApp(<SessionHistory />);

    // Row 1 + row 3 belong to member 1 -> joined name.
    expect(await screen.findAllByText("Kari Nordmann")).toHaveLength(2);
    // Row 2 has member_id null and no Zaptec name.
    expect(screen.getByText("Ikke tilordnet")).toBeInTheDocument();
    // Duration is derived from started_at / ended_at (18:00 -> 20:30).
    expect(screen.getByText("2 t 30 min")).toBeInTheDocument();
    expect(screen.getByText("3 ladeøkter")).toBeInTheDocument();
  });

  it("filters the table by member", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    const { user } = renderApp(<SessionHistory />);
    await screen.findByText("Ikke tilordnet");

    await user.selectOptions(screen.getByLabelText("Medlem"), "1");

    expect(await screen.findByText("2 ladeøkter")).toBeInTheDocument();
    expect(screen.queryByText("Ikke tilordnet")).not.toBeInTheDocument();
  });

  it("renders the session-size sparkline for the month", async () => {
    setSession(ADMIN_USER);
    renderApp(<SessionHistory />);

    expect(
      await screen.findByText(/Fordeling etter øktstørrelse/),
    ).toBeInTheDocument();
  });

  it("opens a drill-down modal with the intra-session month split", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    const { user } = renderApp(<SessionHistory />);
    // Newest row first = the cross-month session "z-3".
    await user.click((await screen.findAllByText("Kari Nordmann"))[0]);

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Fordelt på måned")).toBeInTheDocument();
    // It crosses a boundary, so the month-shift marker note shows.
    expect(within(dialog).getByText(/månedsskifte/)).toBeInTheDocument();

    const partsTable = within(dialog).getByRole("table");
    expect(within(partsTable).getByText("2026-03")).toBeInTheDocument();
    expect(within(partsTable).getByText("2026-04")).toBeInTheDocument();
    expect(
      within(partsTable).getAllByText("delt etter intervaller"),
    ).toHaveLength(2);
  });

  it("notes when a session has no imported interval data", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });

    const { user } = renderApp(<SessionHistory />);
    // The unassigned row is session "z-2", which has no intervals.
    await user.click(await screen.findByText("Ikke tilordnet"));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/Ingen intervalldata importert/),
    ).toBeInTheDocument();
  });

  it("shows an empty table when the member has no sessions", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });
    seedMember({ id: 2, member_reference: "M-2", full_name: "Ola Hansen" });

    const { user } = renderApp(<SessionHistory />);
    await screen.findByText("Ikke tilordnet");

    await user.selectOptions(screen.getByLabelText("Medlem"), "2");

    const table = screen.getByRole("table");
    expect(within(table).getByText(/Ingen ladeøkter/)).toBeInTheDocument();
  });
});
