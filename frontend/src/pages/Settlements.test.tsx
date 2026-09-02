import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AppRouter from "../router";
import { ADMIN_USER, seedSettlement, setSession } from "../test/handlers";
import { renderApp } from "../test/utils";

async function rowFor(month: string): Promise<HTMLElement> {
  const cell = await screen.findByText(month);
  return cell.closest("tr") as HTMLElement;
}

describe("Settlements (admin list)", () => {
  it("separates a shared draft from an unshared one", async () => {
    setSession(ADMIN_USER);
    seedSettlement({ period_month: "2026-07", status: "draft" });
    seedSettlement({
      period_month: "2026-06",
      status: "draft",
      usage_frozen_at: "2026-07-01T00:00:00+00:00",
      draft_shared_at: "2026-07-02T09:00:00+00:00",
    });

    renderApp(<AppRouter />, { route: "/avregninger" });

    expect(within(await rowFor("2026-07")).getByText("Utkast")).toBeInTheDocument();
    expect(
      within(await rowFor("2026-06")).getByText("Utkast · delt"),
    ).toBeInTheDocument();
  });

  it("chips a posted settlement with a correction available and any already booked", async () => {
    setSession(ADMIN_USER);
    seedSettlement({
      period_month: "2026-05",
      status: "posted",
      posted_at: "2026-06-01T00:00:00+00:00",
      correction_pending: true,
      correction_count: 2,
    });

    renderApp(<AppRouter />, { route: "/avregninger" });

    const row = await rowFor("2026-05");
    expect(within(row).getByText("Bokført")).toBeInTheDocument();
    expect(
      within(row).getByText("Endret forbruk – korrigering tilgjengelig"),
    ).toBeInTheDocument();
    expect(within(row).getByText("Korrigert ×2")).toBeInTheDocument();
  });

  it("chips a frozen draft whose consumption changed after the freeze", async () => {
    setSession(ADMIN_USER);
    seedSettlement({
      period_month: "2026-04",
      status: "draft",
      usage_frozen_at: "2026-05-01T00:00:00+00:00",
      consumption_changed: true,
    });

    renderApp(<AppRouter />, { route: "/avregninger" });

    expect(
      within(await rowFor("2026-04")).getByText("Forbruk endret – frys på nytt"),
    ).toBeInTheDocument();
  });

  it("shows no merknad chip for a clean draft", async () => {
    setSession(ADMIN_USER);
    seedSettlement({ period_month: "2026-03", status: "draft" });

    renderApp(<AppRouter />, { route: "/avregninger" });

    const row = await rowFor("2026-03");
    expect(within(row).getByText("Utkast")).toBeInTheDocument();
    expect(
      within(row).queryByText(/Korrigering|Korrigert|Forbruk endret/),
    ).toBeNull();
  });
});
