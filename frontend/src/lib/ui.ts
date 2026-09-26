/**
 * Shared class strings for the controls that repeat across every page.
 *
 * These existed as ~50 inlined copies and two local `inputClass` constants. The
 * reason to centralise them is touch sizing: a 44px minimum hit area has to be
 * set once, not 50 times, and `min-h-11` only ever needs to apply below `sm`
 * where a finger is the pointer.
 */

/** Text/date/number inputs and selects. */
export const inputClass =
  "w-full min-h-11 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-emerald-500 focus:outline-none sm:min-h-0";

/** The affirmative action on a form or page. */
export const btnPrimary =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60 sm:min-h-0";

/** The neutral/secondary action — cancel, refresh, export. */
export const btnSecondary =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60 sm:min-h-0";

/** A compact row-level action inside a table cell or card footer. */
export const btnRow =
  "inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-60 sm:min-h-0";

/** The bordered panel used for tables, cards and chart frames. */
export const cardFrame = "rounded-lg border border-slate-800";
