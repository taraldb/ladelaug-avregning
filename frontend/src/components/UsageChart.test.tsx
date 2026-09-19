import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADMIN_USER, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";
import UsageChart from "./UsageChart";

describe("UsageChart", () => {
  it("summarises peak power and session count, defaulting to the 7d window", async () => {
    setSession(ADMIN_USER);
    renderApp(<UsageChart />);

    expect(await screen.findByText("Bruk over tid")).toBeInTheDocument();
    expect(
      await screen.findByText(/maks 7,2 kW · maks 1 samtidige økter/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "7d" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Lader aktivt")).toBeInTheDocument();
    expect(screen.getByText("Tilkoblet, ikke lading")).toBeInTheDocument();
  });

  it("switches window on click", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    await user.click(screen.getByRole("button", { name: "2d" }));

    expect(screen.getByRole("button", { name: "2d" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "7d" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("shows a plain day-to-day range with no time of day", async () => {
    setSession(ADMIN_USER);
    renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    await screen.findByText(/maks 7,2 kW/);

    const label = screen.getByTestId("usage-range").textContent ?? "";
    expect(label).toMatch(/^\d{2}\.\d{2} – \d{2}\.\d{2}$/);
  });

  it("collapses the x-axis to one tick per day for the 7d window (no hour ticks)", async () => {
    setSession(ADMIN_USER);
    const { container } = renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    // Default is 7d — wait for that fetch's rows to actually render.
    await screen.findByText(/maks 7,2 kW/);

    const labels = Array.from(
      container.querySelectorAll(".recharts-cartesian-axis-tick-value"),
    ).map((el) => el.textContent);
    expect(labels.some((l) => /^\d{2}:00$/.test(l ?? ""))).toBe(false);
    expect(labels.filter((l) => /^\d{2}\.\d{2}$/.test(l ?? "")).length).toBeGreaterThan(1);
  });

  it("pages the hours window back and forward with the arrows", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    await screen.findByText(/maks 7,2 kW/);

    const back = screen.getByRole("button", { name: "Forrige periode" });
    const forward = screen.getByRole("button", { name: "Neste periode" });
    expect(forward).toBeDisabled(); // starts live

    const liveRange = screen.getByTestId("usage-range").textContent;

    await user.click(back);
    await screen.findByText(/maks 7,2 kW/); // wait for the re-fetch to land

    expect(forward).not.toBeDisabled();
    expect(screen.getByTestId("usage-range").textContent).not.toBe(liveRange);

    await user.click(forward);
    await screen.findByText(/maks 7,2 kW/);

    expect(forward).toBeDisabled(); // back to live
    expect(screen.getByTestId("usage-range").textContent).toBe(liveRange);
  });

  it("resets paging to live when a window-size button is clicked", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    await user.click(screen.getByRole("button", { name: "Forrige periode" }));
    expect(screen.getByRole("button", { name: "Neste periode" })).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: "2d" }));
    expect(screen.getByRole("button", { name: "Neste periode" })).toBeDisabled();
  });

  it("shows the month name (not a date range) and fetches that whole month when 'Måned' is picked", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    await user.click(screen.getByRole("button", { name: "Måned" }));

    expect(screen.getByRole("button", { name: "Måned" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // A full month still reconciles to the same per-hour fixture pattern.
    expect(
      await screen.findByText(/maks 7,2 kW · maks 1 samtidige økter/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("usage-range").textContent).toMatch(
      /^[A-ZÆØÅ][a-zæøå]+ \d{4}$/,
    );
    // Can't page into the future.
    expect(screen.getByRole("button", { name: "Neste periode" })).toBeDisabled();
  });

  it("pages by month back and forward when 'Måned' is picked", async () => {
    setSession(ADMIN_USER);
    const { user } = renderApp(<UsageChart />);

    await screen.findByText("Bruk over tid");
    await user.click(screen.getByRole("button", { name: "Måned" }));
    await screen.findByText(/maks 7,2 kW/);

    const currentMonth = screen.getByTestId("usage-range").textContent;
    const back = screen.getByRole("button", { name: "Forrige periode" });
    const forward = screen.getByRole("button", { name: "Neste periode" });

    await user.click(back);
    await screen.findByText(/maks 7,2 kW/);
    expect(screen.getByTestId("usage-range").textContent).not.toBe(currentMonth);
    expect(forward).not.toBeDisabled();

    await user.click(forward);
    await screen.findByText(/maks 7,2 kW/);
    expect(screen.getByTestId("usage-range").textContent).toBe(currentMonth);
    expect(forward).toBeDisabled();
  });
});
