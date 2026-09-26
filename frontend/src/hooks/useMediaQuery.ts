import { useCallback, useSyncExternalStore } from "react";

/**
 * True while `query` matches.
 *
 * Tailwind breakpoints are pure CSS, and a component that emitted BOTH a
 * desktop and a mobile branch would have both of them in the DOM under test
 * (vitest runs with `css: false`, so the stylesheet is never even parsed) — and
 * visible to screen readers on the hidden side. So the responsive decisions
 * that change *structure* rather than styling are made here, in JS, and exactly
 * one branch is ever rendered. Layout-only responsiveness stays in CSS.
 *
 * Safe when `window.matchMedia` is missing (jsdom provides none): reports
 * `fallback`. The `min-width` helpers below pass `true` for it, so an
 * environment without matchMedia degrades to the desktop layout rather than
 * silently serving everyone the phone one.
 */
export function useMediaQuery(query: string, fallback = false): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia?.(query);
      if (!mql) return () => {};
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    [query],
  );

  // Read during render rather than in an effect: the first paint is already
  // correct, so there is no flash of the wrong branch. (No SSR here — this is a
  // client-rendered Vite SPA — but getServerSnapshot is required by the API.)
  const getSnapshot = useCallback(
    () => window.matchMedia?.(query).matches ?? fallback,
    [query, fallback],
  );

  return useSyncExternalStore(subscribe, getSnapshot, () => fallback);
}

/** Below Tailwind `sm` (640px) — where a table becomes a list of cards. */
export function useIsNarrow(): boolean {
  return !useMediaQuery("(min-width: 640px)", true);
}

/** Below Tailwind `md` (768px) — where the nav becomes a drawer. */
export function useIsCompact(): boolean {
  return !useMediaQuery("(min-width: 768px)", true);
}

/**
 * Chart height for the current viewport.
 *
 * Recharts wants a number, not a CSS class, so this is one of the few places a
 * layout value has to come through JS. A 260px chart eats most of a phone
 * screen; shrinking it keeps the surrounding context visible.
 */
export function useChartHeight(base: number, narrowBase = Math.round(base * 0.75)) {
  return useIsNarrow() ? narrowBase : base;
}
