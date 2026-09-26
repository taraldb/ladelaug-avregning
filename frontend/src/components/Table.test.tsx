import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { setViewport } from "../test/setup";
import Table, { type Column } from "./Table";

interface Row {
  id: number;
  name: string;
  ref: string;
  amount: string;
}

const ROWS: Row[] = [
  { id: 1, name: "Grace Hopper", ref: "H12", amount: "kr 1 500,00" },
  { id: 2, name: "Ada Lovelace", ref: "H14", amount: "kr -90,00" },
];

function columns(onAct?: (r: Row) => void): Column<Row>[] {
  return [
    { key: "name", header: "Navn", card: "title", render: (r) => r.name },
    { key: "ref", header: "Referanse", card: "title", render: (r) => r.ref },
    { key: "amount", header: "Saldo", render: (r) => r.amount },
    { key: "secret", header: "Skjult", card: "hidden", render: () => "ikke i kort" },
    {
      key: "actions",
      header: "",
      card: "footer",
      render: (r) => (
        <button type="button" onClick={() => onAct?.(r)}>
          Se {r.name}
        </button>
      ),
    },
  ];
}

const base = { rows: ROWS, rowKey: (r: Row) => r.id };

describe("Table", () => {
  it("renders a real table on desktop", () => {
    render(<Table columns={columns()} {...base} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + 2
    expect(within(table).getAllByText("ikke i kort")).toHaveLength(2);
  });

  it("renders labelled cards and no table when narrow", () => {
    setViewport("mobile");
    render(<Table columns={columns()} {...base} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(2);

    const grace = cards[0];
    expect(within(grace).getByText("Grace Hopper")).toBeInTheDocument();
    expect(within(grace).getByText("H12")).toBeInTheDocument();
    // a non-title column keeps its header as the field label
    expect(within(grace).getByText("Saldo")).toBeInTheDocument();
    expect(within(grace).getByText("kr 1 500,00")).toBeInTheDocument();
    // card: "hidden" is left out
    expect(within(grace).queryByText("ikke i kort")).not.toBeInTheDocument();
    // card: "footer" still renders and still works
    expect(within(grace).getByRole("button", { name: "Se Grace Hopper" })).toBeInTheDocument();
  });

  it("uses cardLabel when the header is unsuitable", () => {
    setViewport("mobile");
    render(
      <Table
        columns={[{ key: "x", header: "", cardLabel: "På", render: () => "Ja" }]}
        {...base}
      />,
    );
    expect(screen.getAllByText("På")).toHaveLength(2);
  });

  it("fires onRowClick from the card", async () => {
    setViewport("mobile");
    const onRowClick = vi.fn();
    const user = userEvent.setup();
    render(<Table columns={columns()} {...base} onRowClick={onRowClick} />);

    await user.click(screen.getByText("Ada Lovelace"));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[1]);
  });

  it("renders the expansion inside the card", () => {
    setViewport("mobile");
    render(
      <Table
        columns={columns()}
        {...base}
        isExpanded={(r) => r.id === 1}
        renderExpanded={() => <p>detaljer</p>}
      />,
    );
    const grace = screen.getAllByRole("listitem")[0];
    expect(within(grace).getByText("detaljer")).toBeInTheDocument();
  });

  it("replaces the row when replaceRow is set", () => {
    render(
      <Table
        columns={columns()}
        {...base}
        replaceRow
        isExpanded={(r) => r.id === 1}
        renderExpanded={() => <p>skjema</p>}
      />,
    );
    expect(screen.getByText("skjema")).toBeInTheDocument();
    expect(screen.queryByText("Grace Hopper")).not.toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("keeps the same empty message in both modes", () => {
    const { unmount } = render(
      <Table columns={columns()} rows={[]} rowKey={(r: Row) => r.id} empty="Ingen rader" />,
    );
    expect(screen.getByText("Ingen rader")).toBeInTheDocument();
    unmount();

    setViewport("mobile");
    render(
      <Table columns={columns()} rows={[]} rowKey={(r: Row) => r.id} empty="Ingen rader" />,
    );
    expect(screen.getByText("Ingen rader")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
