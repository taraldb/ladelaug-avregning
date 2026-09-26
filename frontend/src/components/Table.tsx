import { Fragment, type ReactNode } from "react";
import { useIsNarrow } from "../hooks/useMediaQuery";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string;

  // ---- card mode (below `sm`); all optional, all inert on desktop ----

  /** Label shown beside the value in a card. Defaults to `header` — supply
   *  this when `header` is empty or an icon. */
  cardLabel?: ReactNode;
  /** How this column takes part in the card.
   *  undefined — a labelled "label | value" row (the default)
   *  "title"   — on the card's header line, label suppressed; several are
   *              allowed and are joined in column order, first one emphasised
   *  "footer"  — a full-width strip at the foot of the card (row actions)
   *  "hidden"  — left out of the card entirely */
  card?: "title" | "footer" | "hidden";
}

interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  /** When set together with `isExpanded`, a full-width row is rendered directly
   *  beneath any row for which `isExpanded` returns true. */
  renderExpanded?: (row: T) => ReactNode;
  isExpanded?: (row: T) => boolean;
  /** Tailwind min-width for the table, so a wide one scrolls inside its own
   *  box between `sm` and `md` instead of squeezing. e.g. "min-w-[52rem]" */
  tableMinWidth?: string;
  /** With `renderExpanded`: the expansion *replaces* the row rather than
   *  following it. */
  replaceRow?: boolean;
}

const WRAPPER = "overflow-x-auto rounded-lg border border-slate-800";

/**
 * A data table that becomes a list of labelled cards below `sm`.
 *
 * The switch is made in JS (`useIsNarrow`) rather than with Tailwind's `hidden
 * sm:table`, so only one of the two ever exists in the DOM. Emitting both would
 * duplicate every row's text for screen readers and for Testing Library.
 */
export default function Table<T>({
  columns,
  rows,
  rowKey,
  empty = "Ingen rader",
  onRowClick,
  renderExpanded,
  isExpanded,
  tableMinWidth,
  replaceRow = false,
}: TableProps<T>) {
  const narrow = useIsNarrow();
  const expandedOf = (row: T) =>
    renderExpanded != null && (isExpanded?.(row) ?? false);

  if (rows.length === 0) {
    // Same frame either way, so an empty table and an empty card list read the
    // same and are found by the same query.
    if (narrow) {
      return (
        <div className={WRAPPER}>
          <p className="px-3 py-6 text-center text-slate-500">{empty}</p>
        </div>
      );
    }
    return (
      <div className={WRAPPER}>
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={`px-3 py-2 font-medium ${c.className ?? ""}`}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-slate-500"
              >
                {empty}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  if (narrow) {
    const titles = columns.filter((c) => c.card === "title");
    const footers = columns.filter((c) => c.card === "footer");
    const fields = columns.filter((c) => c.card == null);

    return (
      <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
        {rows.map((row) => {
          const expanded = expandedOf(row);
          return (
            <li
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`px-3 py-3 text-slate-200 ${
                onRowClick ? "cursor-pointer hover:bg-slate-800/50" : ""
              } ${expanded ? "bg-slate-800/40" : ""}`}
            >
              {titles.length > 0 && (
                <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  {titles.map((c, i) => (
                    <span
                      key={c.key}
                      className={
                        i === 0
                          ? "font-semibold text-slate-100"
                          : "text-xs text-slate-400"
                      }
                    >
                      {c.render(row)}
                    </span>
                  ))}
                </div>
              )}

              <dl className="space-y-1">
                {fields.map((c) => (
                  <div key={c.key} className="flex items-baseline justify-between gap-3">
                    <dt className="shrink-0 text-xs uppercase tracking-wide text-slate-400">
                      {c.cardLabel ?? c.header}
                    </dt>
                    <dd className="min-w-0 break-words text-right text-sm">
                      {c.render(row)}
                    </dd>
                  </div>
                ))}
              </dl>

              {footers.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-800 pt-3">
                  {footers.map((c) => (
                    <Fragment key={c.key}>{c.render(row)}</Fragment>
                  ))}
                </div>
              )}

              {expanded && (
                <div className="mt-3 border-t border-slate-800 pt-3">
                  {renderExpanded!(row)}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className={WRAPPER}>
      <table className={`w-full text-left text-sm ${tableMinWidth ?? ""}`}>
        <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={`px-3 py-2 font-medium ${c.className ?? ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => {
            const expanded = expandedOf(row);
            const expansion = expanded && (
              <tr className="bg-slate-900/40">
                <td colSpan={columns.length} className="p-0">
                  {renderExpanded!(row)}
                </td>
              </tr>
            );
            if (expanded && replaceRow) {
              return <Fragment key={rowKey(row)}>{expansion}</Fragment>;
            }
            return (
              <Fragment key={rowKey(row)}>
                <tr
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={
                    onRowClick
                      ? `cursor-pointer text-slate-200 hover:bg-slate-800/50 ${
                          expanded ? "bg-slate-800/40" : ""
                        }`
                      : "text-slate-200"
                  }
                >
                  {columns.map((c) => (
                    <td key={c.key} className={`px-3 py-2 ${c.className ?? ""}`}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
                {expansion}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
