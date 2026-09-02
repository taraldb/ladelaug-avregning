import { Fragment, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string;
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
}

export default function Table<T>({
  columns,
  rows,
  rowKey,
  empty = "Ingen rader",
  onRowClick,
  renderExpanded,
  isExpanded,
}: TableProps<T>) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
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
        <tbody className="divide-y divide-slate-800">
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-slate-500"
              >
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const expanded = renderExpanded != null && (isExpanded?.(row) ?? false);
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
                  {expanded && (
                    <tr className="bg-slate-900/40">
                      <td colSpan={columns.length} className="p-0">
                        {renderExpanded(row)}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
