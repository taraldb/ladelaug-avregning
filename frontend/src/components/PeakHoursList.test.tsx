import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADMIN_USER, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";
import PeakHoursList from "./PeakHoursList";

// Mirrors the "2026-08" fixture in test/handlers.ts: 12 hours descending from
// kl. 20 at 7.50 kW by 0.30 kW/hour, of which the top 10 should render.
// Derived with `Date` rather than hardcoded so "kl. HH" is correct in
// whatever TZ the runner is in.
function labelForHour(hour: number): string {
  const d = new Date(`2026-08-09T${String(hour).padStart(2, "0")}:00:00+02:00`);
  return `09.08 kl. ${String(d.getHours()).padStart(2, "0")}`;
}

describe("PeakHoursList", () => {
  it("lists the top 10 busiest hours for the picked month, ranked by power", async () => {
    setSession(ADMIN_USER);
    renderApp(<PeakHoursList />);

    expect(await screen.findByText("Travleste timer")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Måned"), {
      target: { value: "2026-08" },
    });

    // #1: kl. 20, 7,5 kW.
    expect(await screen.findByText(labelForHour(20))).toBeInTheDocument();

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1); // drop the header row
    expect(rows).toHaveLength(10); // 12 fixture hours, capped at top 10

    const firstCells = within(rows[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(firstCells).toEqual(["1", labelForHour(20), "7,5 kW", "1"]);

    // #10: kl. 11, 4,8 kW — the 11th/12th fixture hours are cut off.
    const lastCells = within(rows[9]).getAllByRole("cell").map((c) => c.textContent);
    expect(lastCells).toEqual(["10", labelForHour(11), "4,8 kW", "1"]);
  });

  it("shows an empty state for a month with no charging", async () => {
    setSession(ADMIN_USER);
    renderApp(<PeakHoursList />);

    fireEvent.change(await screen.findByLabelText("Måned"), {
      target: { value: "2026-01" },
    });

    expect(await screen.findByText("Ingen lading denne måneden")).toBeInTheDocument();
  });
});
