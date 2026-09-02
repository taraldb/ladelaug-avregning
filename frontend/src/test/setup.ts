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

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
});

afterAll(() => server.close());
