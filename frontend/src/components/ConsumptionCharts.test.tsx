import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ADMIN_USER,
  seedMember,
  seedMonthConsumption,
  setSession,
} from "../test/handlers";
import { renderApp } from "../test/utils";
import ConsumptionByMemberChart from "./ConsumptionByMemberChart";
import ConsumptionHistoryChart from "./ConsumptionHistoryChart";
import CostSplitChart from "./CostSplitChart";
import GridRateChart from "./GridRateChart";

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

describe("ConsumptionHistoryChart", () => {
  it("summarises the window and reconciles the numbers in the details table", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<ConsumptionHistoryChart />);

    expect(await screen.findByText(/Siste 3 måneder/)).toBeInTheDocument();

    await user.click(screen.getByText("Vis tall"));

    const table = screen.getByRole("table");
    // 2026-06: 95 assigned + 5 unassigned = 100 metered.
    const june = within(table).getByRole("row", { name: /2026-06/ });
    expect(within(june).getByText("95 kWh")).toBeInTheDocument();
    expect(within(june).getByText("5 kWh")).toBeInTheDocument();
    expect(within(june).getByText("100 kWh")).toBeInTheDocument();
    // invoiced 101 kWh vs 100 metered -> +1 % drift on the right axis.
    expect(within(june).getByText("+1 %")).toBeInTheDocument();
  });
});

describe("CostSplitChart", () => {
  it("reports the latest month's forbruk-vs-fast split in kr and %", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<CostSplitChart />);

    // 2026-06 is the last settled fixture month: kr 1 521,00 consumption of
    // kr 2 121,00 invoiced -> ~71,7 % consumption, ~28,3 % fixed.
    expect(await screen.findByText(/kr\s?1\s?521,00 forbruk \(71,7 %\)/)).toBeInTheDocument();

    await user.click(screen.getByText("Vis tall"));
    const june = within(screen.getByRole("table")).getByRole("row", { name: /2026-06/ });
    expect(within(june).getByText(/kr\s?1\s?521,00 · 71,7 %/)).toBeInTheDocument();
    expect(within(june).getByText(/kr\s?600,00 · 28,3 %/)).toBeInTheDocument();
  });

  it("draws a consumption-share % line and no kr/% toggle", async () => {
    setSession(ADMIN_USER);
    renderApp(<CostSplitChart />);

    // The % line only shows up in the legend (not a column header).
    expect(await screen.findByText("Forbruksandel")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "%" })).not.toBeInTheDocument();
  });

  it("stacks faste kostnader below forbrukskostnader in the details table", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<CostSplitChart />);

    await user.click(await screen.findByText("Vis tall"));
    const headers = within(screen.getByRole("table"))
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Måned",
      "Faste kostnader",
      "Forbrukskostnader",
      "Sum faktura",
    ]);
  });
});

describe("GridRateChart", () => {
  it("reports the latest settled cost + kr/kWh and ignores unsettled months", async () => {
    setSession(ADMIN_USER);
    renderApp(<GridRateChart />);

    // 2026-06 is the last settled month in the fixture (kr 2121,00 total, 2,10/kWh);
    // 2026-07 is not settled.
    expect(
      await screen.findByText(/Siste: kr\s?2\s?121,00 · kr\s?2,10\/kWh/),
    ).toBeInTheDocument();
  });
});

describe("ConsumptionByMemberChart", () => {
  it("shows a bar per member for the picked month, unassigned included", async () => {
    setSession(ADMIN_USER);
    seedMember({ id: 1, member_reference: "M-1", full_name: "Kari Nordmann" });
    seedMember({ id: 2, member_reference: "M-2", full_name: "Ola Hansen" });
    seedMonthConsumption(thisMonth(), {
      total_kwh: "40.00",
      unassigned_kwh: "5.00",
      by_member: [
        { member_id: 1, energy_kwh: "25.00" },
        { member_id: 2, energy_kwh: "10.00" },
      ],
    });

    renderApp(<ConsumptionByMemberChart />);

    // Axis category ticks render the member names + the unassigned bucket.
    expect(await screen.findByText("Kari Nordmann")).toBeInTheDocument();
    expect(screen.getByText("Ola Hansen")).toBeInTheDocument();
    expect(screen.getByText("Ikke tilordnet")).toBeInTheDocument();
  });

  it("shows an empty state when nothing is metered", async () => {
    setSession(ADMIN_USER);
    renderApp(<ConsumptionByMemberChart />);

    expect(
      await screen.findByText(/Ingen registrert forbruk/),
    ).toBeInTheDocument();
  });
});
