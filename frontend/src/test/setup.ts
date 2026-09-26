import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { Children, cloneElement, createElement, isValidElement } from "react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { resetMockState, server } from "./handlers";

// Recharts' <ResponsiveContainer> measures its parent via ResizeObserver, which
// jsdom never sizes — charts would render at 0×0. Swap it for a fixed-size
// wrapper so the SVG actually renders under test.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => {
      const child = Children.only(children);
      return createElement(
        "div",
        { style: { width: 800, height: 300 } },
        isValidElement(child)
          ? cloneElement(child as React.ReactElement, { width: 800, height: 300 })
          : child,
      );
    },
  };
});

// Node's global fetch (undici) can't resolve the relative URLs our client uses
// ("/api/..."), and jsdom doesn't provide fetch. Normalise to an absolute URL
// against the jsdom origin BEFORE MSW wraps fetch in `server.listen()`.
const origin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost";
const realFetch = globalThis.fetch;
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  if (typeof input === "string" && input.startsWith("/")) {
    return realFetch(origin + input, init);
  }
  return realFetch(input, init);
}) as typeof fetch;

// jsdom implements no CSSOM media matching — window.matchMedia is undefined.
// Tailwind breakpoints are pure CSS and this suite runs with `css: false`
// (vite.config.ts), so a component emitting BOTH a desktop and a mobile branch
// would have both visible to Testing Library. Every *structural* responsive
// decision is therefore made in JS (src/hooks/useMediaQuery.ts) and stubbed
// here. Default is DESKTOP: the suite asserts on <table>/<tr> throughout.
let viewport: "desktop" | "mobile" = "desktop";

/**
 * Flip the layout for one test. Call BEFORE render, like `setSession()`.
 * Deliberately does not notify subscribers — firing them outside `act()` warns,
 * and every test follows the configure-then-render idiom. A test that needs a
 * live flip should wrap this call in `act()`.
 */
export function setViewport(kind: "desktop" | "mobile") {
  viewport = kind;
}

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: (query: string) =>
    ({
      // A getter, not a captured boolean: useSyncExternalStore re-reads
      // `matches` on every render, so a snapshot taken at construction time
      // would go stale as soon as setViewport() ran.
      get matches() {
        return viewport === "desktop"
          ? /min-width/.test(query)
          : !/min-width/.test(query);
      },
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {}, // legacy, still probed by some deps
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList,
});

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
  setViewport("desktop");
});

afterAll(() => server.close());
