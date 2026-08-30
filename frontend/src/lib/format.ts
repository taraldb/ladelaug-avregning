// Formatting helpers. Money always arrives from the API as a Decimal *string*
// (canonical integer øre on the backend) — never parse it to a Number for
// display math. `formatNok` groups/pads the string itself.

const NBSP = " ";

/**
 * Format a Decimal string as Norwegian kroner, e.g. `"1500.00"` -> `"1 500,00 kr"`,
 * `"-50.5"` -> `"-50,50 kr"`. Uses a plain space as the thousands separator.
 */
export function formatNok(value: string): string {
  const trimmed = (value ?? "").trim();
  if (trimmed === "") return "–";

  const negative = trimmed.startsWith("-");
  const unsigned = negative ? trimmed.slice(1) : trimmed;
  const [intRaw, fracRaw = ""] = unsigned.split(".");

  const intPart = intRaw.replace(/^0+(?=\d)/, "") || "0";
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const frac = (fracRaw + "00").slice(0, 2);

  const isZero = intPart === "0" && /^0*$/.test(frac);
  const sign = negative && !isZero ? "-" : "";

  return `${sign}${grouped},${frac}${NBSP}kr`;
}

/** Format a `YYYY-MM-DD` (or ISO datetime) as `DD.MM.YYYY` in nb-NO order. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return value;
  const [, y, mo, d] = m;
  return `${d}.${mo}.${y}`;
}

/** Format an ISO datetime as `DD.MM.YYYY HH:MM` (local time). */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${formatDate(value)} ${hh}:${mm}`;
}

/** Human label for a ledger transaction type. */
export function txnTypeLabel(type: string): string {
  switch (type) {
    case "payment":
      return "Innbetaling";
    case "payment_reversal":
      return "Reversering";
    case "adjustment_credit":
      return "Justering (kredit)";
    case "adjustment_debit":
      return "Justering (debet)";
    case "settlement_charge":
      return "Avregning";
    case "settlement_reversal":
      return "Avregning (reversert)";
    default:
      return type;
  }
}
