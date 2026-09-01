import { splitNok } from "../lib/format";

interface MoneyProps {
  /** Decimal string from the API, e.g. `"1500.00"`. */
  value?: string;
  /** Canonical integer øre, e.g. `150000` (forecast endpoints). */
  ore?: number;
  /** Extra classes for the wrapper (colour, etc.). */
  className?: string;
}

/**
 * Render a NOK amount for a table cell: `kr` sits a fixed hair-space to the left
 * of the digits, and the digits sit in a fixed-width, right-aligned box. In a
 * right-aligned column that keeps both the `kr` and the øre lined up down the
 * column, with only a small constant gap between them (no wide stretching).
 * Amounts past ~5 digits just nudge the `kr` left on that row.
 *
 * For amounts in running prose use `formatNok`/`formatOre` directly instead.
 */
export default function Money({ value, ore, className }: MoneyProps) {
  const { symbol, amount } = splitNok({ value, ore });
  if (!symbol) return <>{amount}</>;
  return (
    <span
      className={`whitespace-nowrap tabular-nums${className ? ` ${className}` : ""}`}
    >
      <span className="pr-[0.5ch]">{symbol}</span>
      <span className="inline-block min-w-[9ch] text-right">{amount}</span>
    </span>
  );
}
