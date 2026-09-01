// Formatting helpers. Money always arrives from the API as a Decimal *string*
// (canonical integer øre on the backend) — never parse it to a Number for
// display math. `formatNok` groups/pads the string itself.

const NBSP = " ";

/**
 * Format a Decimal string as Norwegian kroner, e.g. `"1500.00"` -> `"kr 1 500,00"`,
 * `"-50.5"` -> `"kr -50,50"`. The currency symbol comes first (nb-NO), with a
 * plain space as the thousands separator.
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

  return `kr${NBSP}${sign}${grouped},${frac}`;
}

/**
 * Format an integer amount of øre as Norwegian kroner, e.g. `150000` -> `"kr 1 500,00"`.
 * Some endpoints (forecast) hand back canonical integer øre rather than a Decimal
 * string; convert losslessly and hand off to `formatNok`.
 */
export function formatOre(ore: number): string {
  const negative = ore < 0;
  const abs = Math.abs(Math.trunc(ore));
  const decimal = `${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
  return formatNok(negative ? `-${decimal}` : decimal);
}

/**
 * Split a formatted amount into its `"kr"` prefix and the numeric part, so a
 * table cell can pin the prefix left and the digits right (see `<Money>`). Pass
 * either a Decimal string (`value`) or canonical integer øre (`ore`). A blank
 * input yields `{ symbol: "", amount: "–" }`.
 */
export function splitNok(input: { value?: string; ore?: number }): {
  symbol: string;
  amount: string;
} {
  const text =
    input.ore != null ? formatOre(input.ore) : formatNok(input.value ?? "");
  const i = text.indexOf(NBSP);
  if (i === -1) return { symbol: "", amount: text };
  return { symbol: text.slice(0, i), amount: text.slice(i + 1) };
}

/**
 * Normalise a human-typed number so the backend can parse it: accept both
 * `"123,45"` and `"123.45"` as 123.45, and tolerate space / point thousands
 * separators (`"1 234,56"`, `"1.234,56"`, `"1,234.56"`). Whichever of `.` or `,`
 * appears last is the decimal point; the other is grouping. Mirrors
 * `money.normalise_decimal_input` on the backend. Apply it to the value of every
 * free-text numeric input before sending it to the API.
 */
export function normalizeDecimalInput(value: string): string {
  let s = value.replace(/\s/g, "");
  const commas = (s.match(/,/g) ?? []).length;
  if (s.includes(",") && s.includes(".")) {
    s =
      s.lastIndexOf(",") > s.lastIndexOf(".")
        ? s.replace(/\./g, "").replace(/,/g, ".")
        : s.replace(/,/g, "");
  } else if (commas === 1) {
    s = s.replace(",", ".");
  } else if (commas > 1) {
    s = s.replace(/,/g, "");
  }
  return s;
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
    case "settlement_correction":
      return "Korrigering";
    case "refund":
      return "Refusjon";
    default:
      return type;
  }
}
